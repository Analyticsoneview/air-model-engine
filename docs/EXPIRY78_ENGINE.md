# AIR EXPIRY78 Engine

## Purpose

EXPIRY78 replays the seven-rule option-premium setup against verified daily option OHLCV observations. It is a research/backtest engine only; it does not place broker orders.

## Seven qualification and lifecycle rules

1. **Valid observations:** option daily open, high, low, close and traded quantity must all be positive; OHLC values must be internally consistent.
2. **Bullish engulfing:** the previous valid traded observation must be bearish and the current candle bullish; the current real body must engulf the previous real body.
3. **Limit price:** entry limit is exactly 40% of the bullish-engulfing candle HIGH (engulfing_high * 0.40). No candle-range interpolation is applied.
4. **Limit fill:** only a later daily LOW touching or crossing the limit, strictly before expiry, can fill the entry. The replay assumes a fill at the limit.
5. **Entry minimums:** entry premium must be at least ₹1 and entry-day option quantity at least 10. For stock CE/PE, entry premium must also be no more than ₹10. Index options are exempt from the ₹10 ceiling.
6. **Protected stop:** stop loss is 5% below actual entry. Daily LOW is checked from the entry day onward. A same-day breach is conservatively treated as stopped. On a later session opening below the stop, exit is at the observed OPEN (gap-through); otherwise exit is at the stop.
7. **Expiry survivor:** only a trade that never breached its stop and reaches expiry with a verified expiry-day underlying close and calculated intrinsic value is marked as an EXPIRY78 survivor. Stopped trades remain separately classified as SLHIT.

## Evidence contract

Submit a normal operator-authorized POST to /api/v1/model-engine/signals with classification WAIT, wait_verified=true, the contract fields, and the following evidence structure. The signal endpoint persists the evidence JSON used by the evaluator. Tag a ledger signal with evidence.strategy_memberships: ["EXPIRY78"] (or evidence.expiry78_candidate: true) and attach evidence.daily_option_bars:

~~~json
{
  "strategy_memberships": ["EXPIRY78"],
  "daily_option_bars": [
    {"date": "2026-11-03", "open": 12.0, "high": 13.0, "low": 9.0, "close": 10.0, "quantity": 100},
    {"date": "2026-11-04", "open": 9.0, "high": 20.0, "low": 8.0, "close": 15.0, "quantity": 120},
    {"date": "2026-11-05", "open": 9.0, "high": 10.0, "low": 7.8, "close": 8.5, "quantity": 90},
    {"date": "2026-11-10", "open": 8.2, "high": 12.0, "low": 8.1, "close": 10.0, "quantity": 150, "underlying_close": 110.0}
  ],
  "position_quantity": 50,
  "charges_rupees": 20.0
}
~~~

position_quantity is the actual traded option quantity used for rupee P&L; it is not inferred from daily traded volume. charges_rupees is subtracted only when explicitly supplied. Missing size or charges remain null rather than guessed.

## API

- GET /api/v1/model-engine/expiry78
- Optional query parameters: limit (1–2000), as_of (YYYY-MM-DD).

The endpoint evaluates only explicitly tagged contracts that include daily bars. The MASTER EXPIRY78 strategy tab uses the same replay evaluator. Records without source bars are not promoted to engine-qualified trades.

## Lifecycle output

- NEW: limit filled on the replay cutoff date and protected stop remains intact.
- HOLD: filled before the replay cutoff and protected stop remains intact.
- WAIT: no later limit touch yet, or expiry valuation evidence is missing.
- SLHIT: same-day stop, normal stop or gap-through-stop exit.
- EXPIRED: expiry settlement is available; expiry_survivor is true only when no stop was hit.
- OPEN: aggregate of NEW and HOLD in the strategy tab.

REENTRY is not inferred from a second candle pattern. It remains available only through a separately verified lifecycle record; the seven-rule source definition does not specify an automatic re-entry rule.


## Execution boundary

The expiry intrinsic result is a historical model outcome, not a live instruction to carry a position overnight. AIR QOC's separate live execution rule remains: do not carry positions overnight into expiry. The T-3 expiry-entry gate belongs to the AIR QOC live-entry workflow and is not silently applied to this seven-rule historical replay.
