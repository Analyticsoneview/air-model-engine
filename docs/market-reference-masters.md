# AIR market reference masters

## Contract lot-size history

The broker instrument directory remains the current provider/account token lookup. Each validated
broker-master refresh also appends the normalized contract identity and lot size to
`market_instrument_lot_size_history`, keyed by provider, account, effective date and token.
The existing API scheduler runs the refresh at 07:00 Asia/Kolkata on weekdays. Failed or
undersized downloads do not replace the current master; the refresher validates the complete
source set before calling `replace_snapshot`.

Historical lookups use the latest snapshot effective on or before the signal/entry date.
The current master is a labelled fallback only when dated history is unavailable. Missing
historical values remain unresolved; current lot sizes are not silently backdated.

## Sector master

`market_equity_sector_history` is a stock-level, exchange-specific, effective-dated mapping.
Each record requires a source name and effective start date; an optional source reference and
end date preserve provenance and classification changes. Sector is not inferred from a company
name, trading symbol, index membership or option contract.

Use the NSE Indices Industry Classification source for the NSE classification hierarchy:
https://www.niftyindices.com/resources/industry-classification

The NSE Indices hierarchy has Macro-Economic Sector, Sector, Industry and Basic Industry
levels. AIR's `sector` field stores the Sector level; the other classification levels can be
retained in source files for later extension. The classification is reviewed annually, so
imports must carry their effective date. BSE listings use the same classification framework
but retain their own exchange-symbol mapping.

Operator API:
- `POST /api/v1/model-engine/reference/sectors` imports one source-attributed mapping.
- `POST /api/v1/model-engine/reference/sectors/bulk` imports up to 10,000 mappings.
- `GET /api/v1/model-engine/reference/sectors?exchange=NSE&symbol=...&as_of=YYYY-MM-DD`
  checks an effective-dated mapping.
- `POST /api/v1/model-engine/reference/backfill` backfills only missing historical sector and
  lot-size values for the operator-published ledger, using a broker/account selected by the
  operator. It does not overwrite recorded lot sizes, quantities, entry/exit prices or P&L.

All screens that hydrate through the shared market-data service use the same sector and
contract reference lookup. The reference import/backfill endpoints do not place orders or
alter strategy classification, entry/exit rules, or replay calculations.
