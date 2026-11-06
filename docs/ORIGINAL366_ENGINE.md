# AIR ORIGINAL366 Engine

## Historical baseline — immutable

The ORIGINAL366 historical Sep–Oct 2026 completed-expiry case study remains pinned as:

| Metric | Preserved baseline |
|---|---:|
| Completed trades | 366 |
| Expiry-settled winners | 32 |
| 5% stop-loss trades | 334 |
| Gross P&L | ₹10,71,850 |
| Charges | ₹21,602 |
| Net P&L | ₹10,50,248 |
| Premium capital | ₹15,14,362 |
| Return on premium capital | 69.35% |

These values are a historical reference, not output recalculated by the new-candidate engine. In the source sample, 168 of 534 entries lacked verified expiry settlement and were excluded. The historical 366-trade stop breakdown was 274 same-day, 69 later-session and 23 gap-through stops. The source simulation used daily bhavcopy evidence, not intraday execution. Physical-settlement funding/costs were not included.

## ORIGINAL366 lifecycle replay

The evaluator is independent from EXPIRY78 and RECOVERY.

1. **Membership:** only records explicitly tagged ORIGINAL366 are evaluated. No membership is copied from another strategy.
2. **Entry:** use the verified entry_date and entry_price recorded on the ORIGINAL366 signal. The evaluator does not invent or regenerate a missing historical entry signal.
3. **New stock candidates:** stock CE/PE entry premium must be ₹1–₹10 inclusive. Index options are exempt from the ₹10 ceiling. The filter does not modify the pinned historical baseline.
4. **Stop:** 5% below original entry premium. Check daily option LOW beginning on entry day. Same-day breach is stopped at the 5% level. On a later session opening below the stop, exit at the observed OPEN; otherwise exit at the stop.
5. **Expiry winner:** if the stop was never hit, use verified expiry-day underlying close to calculate CE/PE intrinsic value. Classify as EXPIRED_WIN only when intrinsic value is strictly greater than entry premium.
6. **Expiry loss:** if intrinsic value is equal to or below entry premium and the stop was not hit, classify as EXPIRED_LOSS.
7. **Missing evidence:** if expiry is reached without a verified expiry-day underlying close, classify WAIT; do not invent a settlement value.
8. **P&L:** point P&L is calculated from entry and actual stop/expiry exit. Rupee P&L requires explicit position_quantity; net P&L requires explicit charges_rupees. Traded volume is never used as position size.

## Evidence contract

Create an operator-authorized ledger signal with classification NEW, actual entry_date, entry_price, contract details, and evidence containing explicit ORIGINAL366 membership plus daily option bars.

~~~json
{
  "strategy": "ORIGINAL366",
  "evidence": {
    "strategy_memberships": ["ORIGINAL366"],
    "daily_option_bars": [
      {
        "date": "2026-11-03",
        "open": 8.0,
        "high": 8.5,
        "low": 7.8,
        "close": 8.2,
        "quantity": 100
      },
      {
        "date": "2026-11-06",
        "open": 8.0,
        "high": 9.0,
        "low": 7.9,
        "close": 8.5,
        "quantity": 100,
        "underlying_close": 115.0
      }
    ],
    "position_quantity": 50,
    "charges_rupees": 10.0
  }
}
~~~

position_quantity is actual position quantity, not option-market traded quantity.

## API

GET /api/v1/model-engine/original366

Optional query parameters:
- limit: 1–2000 (default 2000)
- as_of: replay cutoff date in YYYY-MM-DD

The response exposes independent OPEN, NEW, HOLD, WAIT, SLHIT, REENTRY, EXPIRED, EXPIRED_WIN and EXPIRED_LOSS groups, replay counts and P&L fields where position-size/charges evidence exists. It always returns the preserved historical baseline separately with baseline_status: PRESERVED_NOT_RECALCULATED.

The MASTER /master response also exposes the ORIGINAL366 strategy view. The mobile strategy tab consumes that strategy view; no broker order placement is performed.

## Explicit scope boundary

The original entry-signal generation formula/source-data pipeline is not reconstructed from the 366-trade outcome totals. The current replay consumes explicit ORIGINAL366 membership and verified entry fields already supplied to the ledger. Automatic full-universe daily option OHLCV ingestion and original signal regeneration remain separate data-pipeline work; no candidate is fabricated when those inputs are absent.
