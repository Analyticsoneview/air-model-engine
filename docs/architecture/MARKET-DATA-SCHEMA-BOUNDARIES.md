# AIR market-data PostgreSQL schema boundaries

## Decision

AIR uses one PostgreSQL database per deployment, with separate PostgreSQL schemas for each market-data domain. This is logical isolation, not a separate database or separate application per exchange. The API and workflow workers share the database connection pool; ingestion and research code must qualify domain tables by schema.

## Schemas

| Schema | Responsibility |
|---|---|
| nse_cm | NSE cash-market daily observations |
| nse_fo | NSE futures/options observations and date-effective F&O contract-master snapshots |
| nse_com | NSE commodity derivatives observations |
| nse_cd | NSE currency derivatives observations |
| us_market | US-market observations from an explicitly configured and validated provider |
| market_ref | Cross-market instrument directory and exchange/segment trading sessions |
| ingestion | Feed runs, immutable source-artifact metadata, checkpoints and dataset coverage |
| research | Reserved for cross-market research views/materializations; raw feed ownership stays in its market schema |

## Data ownership and integrity

- Each market schema owns its own daily_bars table. The canonical daily shape is shared, but physical tables and write paths are isolated by market.
- Source files are retained in configured local/object storage. ingestion.source_artifacts stores URL, storage URI, SHA-256, byte size, parser version, record counts and validation state.
- Feed runs, checkpoints and coverage are shared operational metadata. A failed feed or partition must not block another feed.
- market_ref.instruments is the cross-market identity directory; it does not replace provider/exchange-specific raw contract records.
- NSE F&O contract-master snapshots and contract rows are stored under nse_fo, keyed by snapshot. Historical signal-date eligibility is resolved against the snapshot effective on that date; later masters must not rewrite old eligibility.
- The three-calendar-month initial history applies to historical observations only. It does not limit contract expiry months.
- US provider selection and licensing/availability must be resolved before enabling the US feed. No provider or data is assumed by this schema migration.

## Operational constraints

- Migrations create schema/table structures only. They do not download market data.
- One-click installation owns initial contract-master ingestion and background historical backfill.
- CI uses synthetic fixtures and disposable PostgreSQL only; it must never download live market data.
- research remains a consumer boundary; do not copy raw rows into it as a second source of truth.
