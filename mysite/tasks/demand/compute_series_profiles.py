# mysite/tasks/demand/compute_series_profiles.py

import logging
from collections import defaultdict
from decimal import Decimal

import duckdb
import pandas as pd
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from mysite.models.demand.actuals import ActualSale, get_higher_period_types
from mysite.models.demand.forecast import (
    AbcClassDefinition, ForecastingConfig,
    SeriesLevelEvaluation, SeriesProfile,
)

logger = logging.getLogger(__name__)

LUMPY_CLASSES = {'LUMPY', 'INSUFFICIENT', 'ZERO'}


@shared_task(bind=True)
def compute_series_profiles(self, client_id: int, period_type: str):
    """
    Full multi-level classification: dynamic location depth,
    dynamic product hierarchy, dynamic time horizons.
    """
    from mysite.models import Client
    from utils.demand.hierarchy_utils import (
        get_location_levels,
        get_product_hierarchy_levels,
    )

    client = Client.objects.get(pk=client_id)
    config = ForecastingConfig.get_for_client(client)
    abc_defs = AbcClassDefinition.get_or_create_defaults(client)

    adi_thr = float(config.adi_threshold)
    cv2_thr = float(config.cv2_threshold)
    min_nz  = config.min_nonzero_periods

    # ── Derive search space from client's actual hierarchies ──────────────────

    # Location levels: [{depth, level_label, location_ids, is_leaf}]
    loc_levels = get_location_levels(client_id)
    # loc_levels[0] is always Client Total (virtual).
    # loc_levels[1..n] are actual PlanningLocation levels from the DB.

    # Product levels: [{depth, level_label, node_ids}] — finest to coarsest
    prod_levels = get_product_hierarchy_levels(client_id)
    # prod_levels[0] is the level just above SKU (e.g. Brand or SubCategory).
    # prod_levels[-1] is the root (Category or similar).

    # Time horizons: list of period_type strings coarser than base
    time_horizons = get_higher_period_types(period_type, config.time_horizon_steps)

    logger.info(
        f'compute_series_profiles: client={client_id} period={period_type}\n'
        f'  location levels: {[l["level_label"] for l in loc_levels]}\n'
        f'  product levels: {[l["level_label"] for l in prod_levels]}\n'
        f'  time horizons: {time_horizons}\n'
        f'  ADI≥{adi_thr} CV²≥{cv2_thr} min_nz={min_nz}'
    )

    # ── Pull actuals ──────────────────────────────────────────────────────────
    qs = (
        ActualSale.objects
        .filter(client=client, period_type=period_type)
        .select_related(
            'item',
            'planning_location',
            'planning_customer',
        )
        .values(
            'item_id', 'item__item_id',
            'planning_customer_id', 'planning_customer__code',
            'planning_location_id', 'planning_location__code',
            'planning_location__path',    # materialized path for ancestor lookup
            'period_start', 'qty', 'revenue',
        )
        .order_by('period_start')
    )

    if not qs.exists():
        logger.info(f'compute_series_profiles: no actuals for client {client_id}')
        return

    df = pd.DataFrame(list(qs))
    df['qty']     = df['qty'].astype(float)
    df['revenue'] = df['revenue'].fillna(0).astype(float)
    df['cust_code'] = df['planning_customer__code'].fillna('__NULL__')

    # Build ancestor lookup from materialized path
    # path = "1/4/12/" → ancestors at depth 1 = node 1, depth 2 = node 4
    def _ancestor_at_depth(path: str, target_depth: int) -> int | None:
        """Return the location_id at target_depth in the path, or None."""
        parts = [p for p in path.split('/') if p]
        # parts[0] is depth-1 node, parts[1] is depth-2, etc.
        idx = target_depth - 1
        return int(parts[idx]) if idx < len(parts) else None

    # Build location_id → location_id-at-depth-n lookup
    # Used to group locations by their ancestor at each level
    loc_id_to_path = df.groupby('planning_location_id')['planning_location__path'].first().to_dict()

    def _loc_ancestor(loc_id: int, depth: int) -> int | None:
        path = loc_id_to_path.get(loc_id, '')
        return _ancestor_at_depth(path, depth)

    # For each location_id, build its ancestor at each location level depth
    all_loc_ids = df['planning_location_id'].unique()
    loc_ancestor: dict[int, dict[int, int | None]] = {}
    for loc_id in all_loc_ids:
        loc_ancestor[loc_id] = {
            level['depth']: _loc_ancestor(loc_id, level['depth'])
            for level in loc_levels[1:]  # skip virtual level 0
        }

    # Add ancestor columns to df
    for level in loc_levels[1:]:
        d = level['depth']
        col = f'anc_depth_{d}'
        df[col] = df['planning_location_id'].map(
            lambda lid, d=d: loc_ancestor.get(int(lid), {}).get(d)
        )

    # ── Build time spine ──────────────────────────────────────────────────────
    all_periods   = sorted(df['period_start'].unique().tolist())
    analysis_from = all_periods[0]
    analysis_to   = all_periods[-1]

    # ── DuckDB aggregations ───────────────────────────────────────────────────
    con = duckdb.connect()
    con.register('actuals', df)

    def _agg_sql(group_cols: list[str], extra_cols: str = '') -> str:
        """Build a GROUP BY aggregation SQL."""
        gc = ', '.join(group_cols)
        return f"""
            SELECT {gc},
                   period_start,
                   SUM(qty) AS qty,
                   SUM(revenue) AS revenue
                   {', ' + extra_cols if extra_cols else ''}
            FROM actuals
            GROUP BY {gc}, period_start
        """

    # Level 0: Item × Client (virtual — all locations)
    df_item_client = con.execute(_agg_sql(['item_id'])).df()

    # Levels 1..n: Item × Location ancestor at each depth
    df_by_depth: dict[int, pd.DataFrame] = {}
    for level in loc_levels[1:]:
        d = level['depth']
        anc_col = f'anc_depth_{d}'
        if anc_col in df.columns:
            df_by_depth[d] = con.execute(
                _agg_sql(['item_id', anc_col])
            ).df().rename(columns={anc_col: 'loc_ancestor_id'})

    # Item × Leaf Location (all customers)
    df_item_loc = con.execute(
        _agg_sql(['item_id', 'planning_location_id',
                  'planning_location__code'])
    ).df()

    # Atomic: Item × Customer × Leaf Location
    df_atomic = con.execute(
        _agg_sql(['item_id', 'cust_code', 'planning_customer_id',
                  'planning_location_id', 'planning_location__code'])
    ).df()

    # Quarterly aggregations for Part C time horizons
    df_time_agg: dict[str, pd.DataFrame] = {}
    for h_period in time_horizons:
        from mysite.models.demand.actuals import PERIOD_FREQ_MAP
        freq = PERIOD_FREQ_MAP.get(h_period)
        if not freq:
            continue
        try:
            tmp = df[['item_id', 'period_start', 'qty', 'revenue']].copy()
            tmp['period_start'] = pd.to_datetime(tmp['period_start'])
            agg = (
                tmp.groupby(['item_id', pd.Grouper(key='period_start', freq=freq)])
                .agg({'qty': 'sum', 'revenue': 'sum'})
                .reset_index()
            )
            agg['period_start'] = agg['period_start'].dt.date
            df_time_agg[h_period] = agg
        except Exception as exc:
            logger.warning(f'Time agg failed for {h_period}: {exc}')

    # ── Helper: build qty series from filtered DataFrame ──────────────────────
    def _qty_series(filtered: pd.DataFrame, periods: list) -> list[float]:
        pq = dict(zip(filtered['period_start'], filtered['qty']))
        return [pq.get(p, 0.0) for p in periods]

    def _value_series(filtered: pd.DataFrame) -> float:
        return float(filtered['revenue'].sum())

    # ── Helper: classify ──────────────────────────────────────────────────────
    def _classify(qty_list: list) -> dict:
        series = [Decimal(str(q)) for q in qty_list]
        return SeriesProfile.compute_syntetos_boylan(
            series, adi_thr, cv2_thr, min_nz
        )

    # ── Helper: ABC at a level ────────────────────────────────────────────────
    def _compute_abc_at_level(
        item_value: float,
        level_df: pd.DataFrame,
    ) -> dict:
        """
        Compute ABC for item_value given all items' values in level_df.
        level_df must contain a 'revenue' column grouped by item_id.
        """
        all_values = level_df.groupby('item_id')['revenue'].sum().sort_values(ascending=False).tolist()
        return AbcClassDefinition.compute_class(
            item_value, all_values, abc_defs
        )

    # ── Helper: build SeriesLevelEvaluation dict ──────────────────────────────
    def _eval_dict(
        grain: str,
        key: dict,
        eval_period: str,
        qty_list: list,
        item_value: float,
        level_df: pd.DataFrame,
    ) -> dict:
        m   = _classify(qty_list)
        abc = _compute_abc_at_level(item_value, level_df)
        return {
            'grain':           grain,
            'evaluation_key':  key,
            'eval_period':     eval_period,
            'metrics':         m,
            'abc':             abc,
            'total_value':     item_value,
            'is_forecastable': m['demand_class'] not in LUMPY_CLASSES,
        }

    # ── Main per-series loop ──────────────────────────────────────────────────
    evaluations_to_create: list[SeriesLevelEvaluation] = []
    profiles_to_upsert: list[dict] = []

    # Get unique atomic series
    atomic_groups = df_atomic.groupby(
        ['item_id', 'cust_code', 'planning_customer_id',
         'planning_location_id', 'planning_location__code']
    )

    for keys, _ in atomic_groups:
        item_id   = keys[0]
        cust_code = keys[1]
        cust_id   = keys[2]
        loc_id    = keys[3]
        loc_code  = keys[4]
        cust_id_int = None if pd.isna(cust_id) else int(cust_id)

        evals: list[dict] = []
        chosen: dict | None = None

        # ── Step 0: Item × Client ─────────────────────────────────────────────
        ic_rows = df_item_client[df_item_client['item_id'] == item_id]
        ic_qty  = _qty_series(ic_rows, all_periods)
        ic_val  = _value_series(ic_rows)
        e0 = _eval_dict(
            grain='item_client',
            key={'grain': 'item_client'},
            eval_period=period_type,
            qty_list=ic_qty,
            item_value=ic_val,
            level_df=df_item_client,
        )
        evals.append(e0)

        if e0['is_forecastable']:
            # ── PART A: drill DOWN location hierarchy ─────────────────────────
            prev_accepted = e0  # last forecastable level

            for level in loc_levels[1:]:
                d       = level['depth']
                anc_id  = loc_ancestor.get(int(loc_id), {}).get(d)
                if anc_id is None:
                    continue  # this location has no ancestor at this depth

                level_df_d = df_by_depth.get(d)
                if level_df_d is None:
                    continue

                rows_d = level_df_d[
                    (level_df_d['item_id'] == item_id) &
                    (level_df_d['loc_ancestor_id'] == anc_id)
                ]
                if rows_d.empty:
                    continue

                val_d = _value_series(rows_d)
                e_d = _eval_dict(
                    grain=f'item_loc_depth_{d}',
                    key={'grain': f'item_loc_depth_{d}',
                         'location_id': int(anc_id),
                         'level_label': level['level_label']},
                    eval_period=period_type,
                    qty_list=_qty_series(rows_d, all_periods),
                    item_value=val_d,
                    level_df=level_df_d,
                )
                evals.append(e_d)

                if e_d['is_forecastable']:
                    prev_accepted = e_d   # keep drilling
                else:
                    # Hit LUMPY — step back
                    chosen = prev_accepted
                    break

            else:
                # Finished all location levels without going LUMPY
                # Now try customer grain if config says so
                if config.evaluate_customer_grain:
                    leaf_rows = df_item_loc[
                        (df_item_loc['item_id'] == item_id) &
                        (df_item_loc['planning_location_id'] == loc_id)
                    ]
                    at_rows = df_atomic[
                        (df_atomic['item_id'] == item_id) &
                        (df_atomic['planning_location_id'] == loc_id) &
                        (df_atomic['cust_code'] == cust_code)
                    ]
                    if not at_rows.empty:
                        at_val = _value_series(at_rows)
                        e_at = _eval_dict(
                            grain='item_cust_location',
                            key={'grain': 'item_cust_location',
                                 'location_id': int(loc_id),
                                 'location_code': loc_code,
                                 'customer_code': cust_code},
                            eval_period=period_type,
                            qty_list=_qty_series(at_rows, all_periods),
                            item_value=at_val,
                            level_df=df_atomic[
                                df_atomic['planning_location_id'] == loc_id
                            ],
                        )
                        evals.append(e_at)
                        if e_at['is_forecastable']:
                            prev_accepted = e_at

                if chosen is None:
                    chosen = prev_accepted

        else:
            # ── PART B: Item is LUMPY at client level ─────────────────────────
            # Roll UP through product hierarchy

            for prod_level in prod_levels:
                # Build series: sum all items in the same product group
                # at this level that belong to this item
                # (requires ItemTaxonomyMapping join — simplified here)
                node_ids = prod_level.get('node_ids', [])
                if not node_ids:
                    continue

                # Placeholder: extend with actual taxonomy lookup
                # For each node in prod_level that contains item_id:
                # sum actuals of all items in that node
                node_id = None  # resolve item → node at this level
                if node_id is None:
                    continue

                # Build aggregated series for this product group
                # (requires a pre-built item → node_id mapping per level)
                # Omitted here — wire in your ItemTaxonomyMapping query
                pass  # replace with actual implementation

            # ── PART C: time aggregation ──────────────────────────────────────
            for h_period in time_horizons:
                if chosen:
                    break
                h_df = df_time_agg.get(h_period)
                if h_df is None:
                    continue
                h_periods = sorted(h_df['period_start'].unique().tolist())
                if len(h_periods) < min_nz:
                    continue

                # Step C-H-0: Item × Client × Time Horizon
                ic_h_rows = h_df[h_df['item_id'] == item_id]
                if not ic_h_rows.empty:
                    ic_h_qty = _qty_series(ic_h_rows, h_periods)
                    ic_h_val = _value_series(ic_h_rows)
                    e_ch = _eval_dict(
                        grain=f'item_client_{h_period}',
                        key={'grain': f'item_client_{h_period}',
                             'period_type': h_period},
                        eval_period=h_period,
                        qty_list=ic_h_qty,
                        item_value=ic_h_val,
                        level_df=h_df,
                    )
                    evals.append(e_ch)
                    if e_ch['is_forecastable']:
                        chosen = e_ch
                        break

                # Step C-H-n: product hierarchy × time horizon
                # (extend with actual taxonomy loop — same pattern as Part B)

            # Final fallback: MANUAL
            if not chosen:
                e_manual = {
                    'grain':          'item_client',
                    'evaluation_key': {'grain': 'item_client', 'note': 'MANUAL'},
                    'eval_period':    period_type,
                    'metrics': {
                        'demand_class': 'LUMPY', 'recommended_strategy': 'MANUAL',
                        'total_periods': len(all_periods), 'nonzero_periods': 0,
                        'total_qty': Decimal('0'), 'adi': None, 'cv2': None,
                        'zero_rate': Decimal('1'),
                    },
                    'abc':         e0['abc'],
                    'total_value': ic_val,
                    'is_forecastable': False,
                }
                evals.append(e_manual)
                chosen = e_manual

        # Mark chosen and build rejection reasons
        for ev in evals:
            ev['is_accepted'] = (ev is chosen)
            if not ev['is_accepted']:
                m = ev['metrics']
                ev['rejection_reason'] = (
                    f"{m['demand_class']} (ADI={m.get('adi','—')}, "
                    f"CV²={m.get('cv2','—')})"
                    if m['demand_class'] in LUMPY_CLASSES else ''
                )
            else:
                ev['rejection_reason'] = ''

        # Build SeriesLevelEvaluation objects
        for ev in evals:
            m = ev['metrics']
            evaluations_to_create.append(
                SeriesLevelEvaluation(
                    client_id=client_id,
                    item_id=item_id,
                    planning_customer_id=(
                        cust_id_int
                        if ev['grain'] == 'item_cust_location'
                        else None
                    ),
                    period_type=period_type,
                    grain=ev['grain'],
                    evaluation_key=ev['evaluation_key'],
                    eval_period_type=ev.get('eval_period', period_type),
                    analysis_from=analysis_from,
                    analysis_to=analysis_to,
                    total_periods=m['total_periods'],
                    nonzero_periods=m['nonzero_periods'],
                    total_qty=m['total_qty'],
                    total_value=Decimal(str(round(ev.get('total_value', 0), 2))),
                    adi=m.get('adi'),
                    cv2=m.get('cv2'),
                    zero_rate=m['zero_rate'],
                    abc_class=ev['abc'].get('abc_class', ''),
                    value_share_pct_at_level=ev['abc'].get('value_share_pct'),
                    demand_class=m['demand_class'],
                    is_accepted=ev.get('is_accepted', False),
                    rejection_reason=ev.get('rejection_reason', ''),
                    recommended_strategy=m.get('recommended_strategy', ''),
                )
            )

        # Build SeriesProfile summary
        chosen_m = chosen['metrics'] if chosen else {}
        atom_rows = df_atomic[
            (df_atomic['item_id'] == item_id) &
            (df_atomic['planning_location_id'] == loc_id) &
            (df_atomic['cust_code'] == cust_code)
        ]
        atom_qty = _qty_series(atom_rows, all_periods)
        atom_m   = _classify(atom_qty)
        atom_val = _value_series(atom_rows)
        atom_abc = _compute_abc_at_level(atom_val, df_atomic)

        profiles_to_upsert.append({
            'client_id':             client_id,
            'item_id':               item_id,
            'planning_customer_id':  cust_id_int,
            'planning_location_id':  int(loc_id),
            'period_type':           period_type,
            'analysis_from':         analysis_from,
            'analysis_to':           analysis_to,
            'total_periods':         atom_m['total_periods'],
            'nonzero_periods':       atom_m['nonzero_periods'],
            'total_qty':             atom_m['total_qty'],
            'total_value':           Decimal(str(round(atom_val, 2))),
            'adi':                   atom_m.get('adi'),
            'cv2':                   atom_m.get('cv2'),
            'zero_rate':             atom_m['zero_rate'],
            'demand_class_atomic':   atom_m['demand_class'],
            'abc_class_atomic':      atom_abc.get('abc_class', ''),
            'chosen_grain':          chosen['grain'] if chosen else '',
            'chosen_demand_class':   chosen_m.get('demand_class', ''),
            'chosen_strategy':       chosen_m.get('recommended_strategy', 'MANUAL'),
            'chosen_eval_period':    chosen.get('eval_period', period_type) if chosen else period_type,
        })

    # ── Persist ────────────────────────────────────────────────────────────────
    with transaction.atomic():
        SeriesLevelEvaluation.objects.filter(
            client_id=client_id, period_type=period_type
        ).delete()

        SeriesLevelEvaluation.objects.bulk_create(
            evaluations_to_create, batch_size=500, ignore_conflicts=True
        )

        # Re-query to get PKs (bulk_create doesn't return PKs on all DB backends)
        eval_pk_map = {
            (e.item_id, e.grain, str(e.evaluation_key)): e.pk
            for e in SeriesLevelEvaluation.objects.filter(
                client_id=client_id, period_type=period_type, is_accepted=True
            )
        }

        for p in profiles_to_upsert:
            update_fields = {k: v for k, v in p.items()
                             if k not in ('client_id', 'item_id',
                                          'planning_customer_id',
                                          'planning_location_id', 'period_type')}
            # Find chosen_evaluation FK
            # (match by item_id + chosen_grain from accepted evaluations)
            chosen_eval_pk = eval_pk_map.get(
                (p['item_id'], p['chosen_grain'],
                 str({'grain': p['chosen_grain']}))
            )
            if chosen_eval_pk:
                update_fields['chosen_evaluation_id'] = chosen_eval_pk

            SeriesProfile.objects.update_or_create(
                client_id=p['client_id'],
                item_id=p['item_id'],
                planning_customer_id=p['planning_customer_id'],
                planning_location_id=p['planning_location_id'],
                period_type=p['period_type'],
                defaults=update_fields,
            )

    from collections import Counter
    grain_counts = Counter(p['chosen_grain'] for p in profiles_to_upsert)
    class_counts = Counter(p['demand_class_atomic'] for p in profiles_to_upsert)
    logger.info(
        f'compute_series_profiles: client={client_id} '
        f'total={len(profiles_to_upsert)} '
        f'chosen_grain={dict(grain_counts)} '
        f'atomic_class={dict(class_counts)}'
    )