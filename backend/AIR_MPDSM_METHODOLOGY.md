# AIR MPDSM — Monthly Premium–Discount & Settlement Monitor

## Evaluation rules
- NSE reference date: session on the 23rd; otherwise the 21st; otherwise nearest earlier NSE trading session. Calendar must be supplied from an authoritative NSE session source; fail closed if absent.
- PML, PMH and EQ are calculated only from the previous completed month's OHLC bars. Never use partial or future monthly data.
- Two next completed NSE sessions must both hold above PML. Any intraday low strictly below PML invalidates the cycle. Insufficient sessions remain WAITING.
- Expiry metadata compares actual contract expiry with calendar month-end. Early expiry is descriptive, not proof of market participation.
- STRONG_PARTICIPATION requires at least four of five checks: option volume >=1.5x historical average, absolute OI change >=5%, absolute premium change >=5%, bid/ask spread <=2%, underlying volume >=1.2x baseline. Missing evidence fails a check.
- Forecast and actual values are separate dated snapshot fields. Historical replay must use only information available as of each snapshot date.

## Structure pattern semantics
- U: rounded basing/recovery candidate.
- V: sharp reversal/recovery candidate.
- N: rally, pullback and renewed-rise candidate.
- W: double-bottom candidate. Confirmation requires two comparable pivot lows and a completed close above the intervening neckline.
- DOUBLE_TOP: potential resistance/target-risk structure; never a guaranteed target.
- States: FORMING, CONFIRMED, FAILED or INCOMPLETE. The initial evaluator emits candidate states and INCOMPLETE; a subsequent-bar lifecycle evaluator must record FAILED when structure invalidates.

## Activation and data quality
The evaluator is deterministic and provider-independent. The caller must supply verified bars, official NSE trading sessions and actual exchange contract metadata. Existing MarketDataService and customer/account entitlements remain the only market-data access path. NSE EOD supports completed-bar evaluation; live options participation requires an authenticated live feed and valid contract master. Missing values must be surfaced as DATA_INSUFFICIENT, not imputed. No broker order action is exposed.

## Persistence
Migration 0019 creates monthly cycle and date-stamped forecast/actual/evidence snapshot tables. Preserve old cycles on monthly rollover; unique keys prevent duplicate cycle/snapshot records.
