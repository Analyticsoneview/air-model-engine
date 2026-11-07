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

## RECOVERED watch and alternative exit logic

1. Preserve the original ORIGINAL366 entry price and original 5% SLHIT event.
2. After the original 5% SL exit date, inspect verified daily option candles.
3. A subsequent daily option **CLOSE** strictly above the original entry premium qualifies a RECOVERED watch. A HIGH-only touch does not qualify.
4. For the RECOVERED alternative exit study, use the **same ORIGINAL entry price**; do not create a recovery-day entry or next-session fill.
5. From the original entry date, replay daily option OHLC with **10% SL** and **45% target**. A later gap through either level exits at observed OPEN. If both SL and target are touched in one daily candle, count SL first.
6. Route the alternative-model lifecycle into separate RECOVERED groups: **OPEN** while before expiry with no exit hit, **TARGETS** on the 45% target, **SLHIT** on the 10% stop, and **EXPIRED** after verified expiry settlement. If expiry has passed but the required expiry valuation is missing, use **WAIT**, never OPEN.
7. Preserve the original 5% SL event separately as **ORIGINAL_SLHIT** historical evidence; do not mix it with the alternative-model 10% SLHIT group.
8. Expose the alternative outcome, exit date/price, premium points and return percentage on each RECOVERED row. RECOVERED is a retrospective watch/backtest view, not a new live position, re-entry, order, or broker instruction. The separate RECOVERY strategy remains independent.

## API

GET /api/v1/model-engine/original366

The response display name is `RECOVERED` and its cohort reference is `ORIGINAL366`. It exposes `SLHIT` and `RECOVERED` separately. The RECOVERED watch rows contain the post-stop close date, close price and original entry premium. No broker orders are placed.

## Evidence contract

Each row must be explicitly tagged with ORIGINAL366 membership and include actual entry/expiry/strike/CE-PE details, `shelf_sessions` (or `remaining_trading_sessions`), and verified daily option OHLCV. The daily close after the SL exit date is mandatory for a RECOVERED watch. No MFE high-only inference is used.
