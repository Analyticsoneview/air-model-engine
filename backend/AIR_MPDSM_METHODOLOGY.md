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


## Current-month low/high extension
At the selected reference session (23rd when it is an NSE session; otherwise 21st when it is a session; otherwise the nearest earlier session), freeze the current-month extremes using completed daily candles dated no later than that reference session.

- CML and its occurrence date are the lowest low observed in the current month through the reference session. An ML candidate requires CML < PML and CML in the discount half of the PML–PMH range (at or below EQ).
- CMH and its occurrence date are the highest high observed in the current month through the reference session. An MH candidate requires CMH > PMH and CMH in the premium half of the PML–PMH range (at or above EQ).
- Keep PML, PMH and EQ unchanged and store CML/CMH separately. These are candidates for a potential new monthly low/high, not automatic reversal or trade signals.
- For an ML candidate, require two subsequent completed sessions with no intraday low below CML; then mark ML_CONFIRMED. Any wick below CML invalidates that candidate. For an MH candidate, require two subsequent completed sessions whose highs do not exceed CMH and whose closes remain below CMH; then mark REJECTION_CONFIRMED. A subsequent high above CMH or close at/above CMH invalidates the rejection candidate.
- Insufficient subsequent sessions remain WAITING. Missing or incomplete reference-session OHLC data returns DATA_INSUFFICIENT. Future bars are excluded from the frozen reference snapshot.
- These extension confirmations are separate from the original PML two-session support-acceptance test; neither substitutes for the other.
