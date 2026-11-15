# AIR Portfolio and Risk Foundation

## Scope

Gate 5 adds a customer-isolated, read-only consolidated portfolio view over the broker accounts already assigned to that customer. It captures broker-reported positions and holdings, normalizes instrument rows, stores immutable snapshots, and exposes portfolio-level summaries in the mobile Model Engine screen.

## Refresh and persistence

- POST /api/v1/customer/portfolio/refresh fetches profile, positions, holdings and order-book data from each owned broker account using existing broker adapters.
- The endpoint only calls read APIs. It does not place, modify or cancel orders.
- Successful account reads are stored independently. A failed account does not erase a previous successful snapshot from another account; the response reports per-account failures and a PARTIAL status.
- GET /api/v1/customer/portfolio returns the latest snapshot per broker account and consolidated metrics.
- GET /api/v1/customer/portfolio/history returns a bounded snapshot history.
- PostgreSQL is selected through AIR_PORTFOLIO_DATABASE_URL, AIR_CUSTOMER_DATABASE_URL or AIR_DATABASE_URL (and supported _FILE secret variants). SQLite remains a local-development compatibility fallback.
- Alembic revision 0010_portfolio_risk_foundation creates air_portfolio_snapshots and the PostgreSQL model_signals table.

## Metric definitions

- Gross market value: sum of known position/holding market values, using broker market value when present or absolute quantity × last price when both are present.
- Net exposure: market value signed by net quantity direction for positions; long holdings contribute positive exposure.
- Invested value: broker cost value when present, otherwise absolute quantity × average price.
- Unrealized P&L: broker-reported unrealized P&L or a transparent market-value minus invested-value calculation when both inputs are present.
- Realized and day P&L: broker-reported row/account fields only.
- Return percentage: unrealized P&L divided by observed invested value. It is explicitly not a time-weighted or money-weighted investor return.
- Concentration: largest known symbol market value divided by total known gross market value.
- Sector exposure: reported sector/industry classifications only. No sector is inferred from the ticker.
- Maximum drawdown: computed per broker account only when at least two positive broker-reported account-equity observations exist; consolidated value is the worst observed account drawdown. It is unavailable otherwise.
- Leverage: gross market value divided by broker-reported capital base, only when both are known.

Missing fields are returned as null and listed in missing_fields; no missing capital, equity, sector or P&L is fabricated. Partial snapshots are retained and marked. The current broker adapters do not all expose account equity/capital or sector classifications, so drawdown/leverage/sector coverage depends on the provider payload.

## Signal ledger storage and tenant boundary

The existing model-signal ledger now supports PostgreSQL via AIR_MODEL_LEDGER_DATABASE_URL, AIR_CUSTOMER_DATABASE_URL or AIR_DATABASE_URL; SQLite remains available for local tests/development. PostgreSQL schema is provisioned by Alembic. A signal ID collision from another customer cannot overwrite the original customer's row; tenant ownership is enforced in the upsert conflict clause.

## Operational limitations

- Portfolio refresh is customer-initiated; it is not a high-frequency market-data valuation feed.
- Snapshot history begins when Gate 5 is deployed and customers refresh their accounts; no historical equity curve is backfilled from unsupported estimates.
- Broker statement/P&L email delivery remains a separate feature and continues to require verified email and SMTP configuration.
- No automated order execution is introduced.
