# mysite/tasks/demand/compute_series_profiles.py

"""
grain encodes WHAT was aggregated and HOW:

'item_loc_dc_cust' — item x leaf location x channel x customer (shape a, atomic) '
'item_loc_dc' — item x leaf location x channel (shape b)
'item_loc' — item x leaf location only (link shape c) 
'item_salesnode_{node_id}' — item rolled up to a SalesNode ancestor 
'item_salesnode_top_{period}'— item at the root SalesNode, coarser period
'taxon_{node_id}_loc' — item-hierarchy-rolled variants of all the above, 
'taxon_{node_id}_salesnode_{sn_id}'
'taxon_{node_id}_salesnode_top_{period}'
 'manual' — entire item hierarchy exhausted, no forecastable level found


    'item_loc'                  — item x leaf location only (link shape c)
    'item_loc_dc'                — item x leaf location x channel (shape b)
    'item_loc_dc_cust'           — item x leaf location x channel x customer (shape a, atomic)
    'item_salesnode_{node_id}'   — item rolled up to a SalesNode ancestor
    'item_salesnode_top_{period}'— item at the root SalesNode, coarser period
    'taxon_{node_id}_loc'        — item-hierarchy-rolled variants of all the above,
    'taxon_{node_id}_loc_dc'       prefixed with the TaxonomyNode id in place of item
    'taxon_{node_id}_loc_dc_cust'
    'taxon_{node_id}_salesnode_{sn_id}'
    'taxon_{node_id}_salesnode_top_{period}'
    'manual'                     — entire item hierarchy exhausted, no forecastable level found
"""
# mysite/tasks/demand/compute_series_profiles.py
#
# This is the THIN CELERY TASK ORCHESTRATOR, mirroring run_forecast.py's
# structure exactly. The actual classification engine (run_for_client,
# persist_results, find_grain_for_series, and every DuckDB helper) lives in
# a SEPARATE file: utils/demand/compute_series_profiles.py — same name,
# different directory, on purpose, matching how run_forecast.py imports its
# logic from utils/demand/forecast_engine.py rather than containing it
# inline. This file REPLACES whatever was previously in
# mysite/tasks/demand/compute_series_profiles.py (the old Part A/B/C
# algorithm) — it does not sit alongside it.

from __future__ import annotations
import logging
from celery import shared_task
logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def compute_series_profiles(self, client_id: int, period_type: str):
    """
    Recompute SeriesProfile / SeriesLevelEvaluation for every series of this
    client at this period_type, using ALL available actuals history (not
    tied to any single ForecastVersion — SeriesProfile is a client+period_type
    -level artifact, reused across versions).

    Chained ahead of run_forecast via ForecastVersionRunView / version_run:
        chain(compute_series_profiles.si(client_id, period_type),
              run_forecast.si(version_id))
    Called with .si() (immutable signature) — this task's return value is
    discarded by the chain either way, but raising on a genuine failure
    (e.g. no actuals at all) aborts the chain before run_forecast runs
    against stale/missing profiles, which is the behavior we want.

    Does NOT touch ForecastVersion.run_status — this task only knows
    client_id/period_type, not which version(s) are waiting on it.
    run_status transitions ('PROFILING' etc.) happen inside run_forecast
    itself, which does have the version.
    """
    from mysite.models.demand.actuals import ActualSale
    from utils.demand.compute_series_profiles import run_for_client, persist_results

    earliest = (
        ActualSale.objects
        .filter(client_id=client_id, period_type=period_type)
        .order_by('period_start')
        .values_list('period_start', flat=True)
        .first()
    )
    latest = (
        ActualSale.objects
        .filter(client_id=client_id, period_type=period_type)
        .order_by('-period_start')
        .values_list('period_start', flat=True)
        .first()
    )
    if earliest is None or latest is None:
        # Matches run_forecast's own "no actuals" check — raise so the chain
        # aborts here instead of proceeding to run_forecast with nothing to work with.
        raise ValueError(
            f'compute_series_profiles: no ActualSale rows for client_id={client_id}, '
            f'period_type={period_type!r} — cannot classify or forecast.'
        )

    try:
        run_output = run_for_client(client_id, period_type, earliest, latest)
        persist_results(client_id, period_type, earliest, latest, run_output)
    except Exception as exc:
        logger.exception(
            f'compute_series_profiles failed for client_id={client_id}, '
            f'period_type={period_type!r}: {exc}'
        )
        raise  # re-raise: let the chain abort, don't silently proceed to run_forecast

    n_series = len(run_output['results'])
    n_manual = sum(1 for r in run_output['results'] if r['grain'] == 'manual')
    logger.info(
        f'compute_series_profiles: client_id={client_id}, period_type={period_type!r} — '
        f'{n_series} series classified ({n_manual} fell through to MANUAL).'
    )
    return {'client_id': client_id, 'period_type': period_type,
            'n_series': n_series, 'n_manual': n_manual}


