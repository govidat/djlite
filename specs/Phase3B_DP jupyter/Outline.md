Section 1 — Synthetic Dataset (20 Auto-Component SKUs × 36 months)
20 SKUs across 4 categories (Braking Systems, Filtration, Suspension, Electrical, Drivetrain) with realistic characteristics baked in — individual trend rates, seasonal amplitude (quarter-end surge in Mar-Apr, winter prep in Oct-Nov), and Gaussian noise. Each row has sku_code, sku_name, subcategory, category, ds, qty, unit_price, revenue. This mirrors what your ActualSale model will store.

Section 2 — Polars
Shows the three operations you'll run constantly in Celery tasks: category-level monthly rollups, trailing 12-month averages per SKU, and YoY growth by category. Notice how .over('category') gives window functions without groupby overhead — this is where Polars is noticeably faster than Pandas at 10K SKU scale.

Section 3 — DuckDB
Three queries that map directly to your Django use cases: best-selling SKU per category using QUALIFY RANK(), seasonality index calculation per SKU, and a full GROUPING SETS rollup that produces Category / Subcategory / SKU totals in a single SQL pass — the exact shape needed to populate ForecastAggregate.

Section 4 — StatsForecast
Fits AutoETS, AutoARIMA, SeasonalNaive, and CrostonSBA on all 20 SKUs in one vectorised call (not a Python loop). Then does cross-validation with 3 rolling windows and computes MAPE per model. Ends with a chart showing actuals + forecast + 80% prediction interval for SKU-006 (Engine Oil Filter).
One API nuance to note for your Django service: ConformalIntervals(h=6, n_windows=2) must be passed to forecast() rather than at StatsForecast() init — this changed in v2.x.

Section 5 — HierarchicalForecast
The full MinTrace pipeline: aggregate() builds the summing matrix S_df from your hierarchy spec (which in Django will be derived from TaxonomyNode), forecasts at all nodes simultaneously, then hrec.reconcile() ensures SKU-level forecasts add up exactly to subcategory and category totals. The coherence check at the end verifies this. Parameter name gotcha: it's S_df= not S= in v1.5+.

Section 6 — Django Mapping Table
A table mapping every notebook concept to its corresponding Django model or service class, so the path from this exploration to ForecastVersion / ForecastLine / ForecastAggregate is clear.