# AIR ORIGINAL366 Engine

## Recovered cohort — immutable historical baseline

ORIGINAL366 is the 366 recovered contracts from the September–October 2026 cohort. The starting population was 534 entries. Selection used the actual filled entry date and price, stock-option premium ₹1–₹10 (index options exempt), and at least 10 NSE trading sessions remaining to expiry. CE and PE were evaluated separately. Of 534 entries, 366 had verified expiry outcomes; 168 unresolved entries were excluded from the completed historical baseline.

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

The historical 366-trade stop breakdown was 274 same-day, 69 later-session and 23 gap-through stops. The source simulation used daily bhavcopy evidence, not intraday execution. Physical-settlement funding/costs were not included. The historical baseline is preserved and is not recalculated by the live candidate engine.

## Qualification and lifecycle

1. Only explicitly tagged ORIGINAL366 contracts enter this strategy; EXPIRY78 and RECOVERY membership is never inherited.
2. Use actual filled entry date and premium. Evaluate CE and PE independently.
3. New stock CE/PE entries must be ₹1–₹10 inclusive. Index options are exempt from the ₹10 cap.
4. At least 10 verified NSE trading sessions must remain at actual entry. Supply `remaining_trading_sessions` on the contract or in evidence. The engine does not approximate NSE holidays using calendar days or weekdays.
5. Apply the original 5% stop below entry premium using daily option LOW. Same-day stop is conservatively at stop; a later gap-through exits at observed OPEN below stop; otherwise at stop.
6. If no stop occurs, settle from verified expiry-day underlying reference close and CE/PE intrinsic value. The expired contract is classified EXPIRED_WIN or EXPIRED_LOSS and appears only under EXPIRED.
7. Missing qualification evidence is REJECTED; missing daily bars or expiry reference is WAIT/UNRESOLVED, never a qualified active contract or completed historical trade.
8. Rupee P&L requires explicit actual position quantity; net P&L additionally requires explicit charges.

## Separation from other engines

- EXPIRYSCAN is a case-study and monthly scanner workbook, independent of AIR QOC Master.
- EXPIRY78 is the separate seven-rule expiry-survivor model (including 80% observed-high fall, close confirmation, and 1.5× volume).
- RECOVERY is the separate post-stop re-entry model with its own 10-session shelf life and +50% target-qualified hold-to-expiry rule.
- ORIGINAL366 is only the recovered 366-contract cohort and its original 5% stop / expiry-settlement outcome logic.

## API

GET /api/v1/model-engine/original366

Optional query parameters: `limit` (1–2000, default 2000) and `as_of` (YYYY-MM-DD).

The API exposes OPEN, NEW, HOLD, WAIT, SLHIT, REENTRY and EXPIRED groups, with EXPIRED_WIN and EXPIRED_LOSS breakdowns. Expired contracts are not included in OPEN. The immutable baseline is returned separately as PRESERVED_NOT_RECALCULATED. No broker orders are placed.

## Evidence contract

Each candidate needs explicit ORIGINAL366 membership, actual filled entry fields, contract details, verified remaining trading-session count, and daily option OHLCV. Expiry settlement additionally requires the expiry-day underlying reference close. Unverified records are not promoted to qualified contracts.
