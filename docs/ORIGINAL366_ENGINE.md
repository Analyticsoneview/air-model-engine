# AIR RECOVERED Section (ORIGINAL366 reference cohort)

## Cohort meaning

ORIGINAL366 is a **reference filter**, not an independent expiry-winner strategy. It identifies the 366 records with full-expiry coverage from the original 534-entry population in the AIR QOC conservative ledger.

| Cohort metric | Verified count |
|---|---:|
| Original entries | 534 |
| Full-expiry-coverage cohort (ORIGINAL366) | 366 |
| Partial-coverage records excluded | 83 |
| No post-entry data excluded | 85 |
| Original 5% SL hits in the 366 cohort | 366 |
| Same-day SL hits | 274 |
| Later-session SL hits | 69 |
| Gap/open SL hits | 23 |

The workbook's `shelf_sessions` field confirms a minimum of 10 sessions for the covered cohort. Stock entries were ₹1–₹10; index contracts are exempt from that stock premium cap. CE and PE remain separately identified. The source MFE/MAE workbook has maximum premium high and low summaries; a maximum high above entry is not sufficient to trigger RECOVERED.

## RECOVERED watch logic

1. Preserve the original entry and original 5% SL event. The contract remains classified SLHIT.
2. After the SL exit date, inspect verified daily option candles.
3. If a subsequent daily option **CLOSE** is strictly greater than the original entry premium, add the contract to the `RECOVERED` watch-only section.
4. A high or intraday touch above entry without a close above entry does not qualify.
5. Keep the original SLHIT lifecycle unchanged. RECOVERED is not a re-entry, not an open position, not an order, and not a P&L event.
6. The separate RECOVERY strategy remains independent and retains its own re-entry, shelf-life and +50% target-qualified expiry-hold rules.

## API

GET /api/v1/model-engine/original366

The response display name is `RECOVERED` and its cohort reference is `ORIGINAL366`. It exposes `SLHIT` and `RECOVERED` separately. The RECOVERED watch rows contain the post-stop close date, close price and original entry premium. No broker orders are placed.

## Evidence contract

Each row must be explicitly tagged with ORIGINAL366 membership and include actual entry/expiry/strike/CE-PE details, `shelf_sessions` (or `remaining_trading_sessions`), and verified daily option OHLCV. The daily close after the SL exit date is mandatory for a RECOVERED watch. No MFE high-only inference is used.
