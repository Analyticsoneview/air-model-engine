# AIR Historical Backtest — implementation notes

## Strategy selection contract

The backtest catalog is sourced from the existing AIR strategy implementations. It must not invent, rename into new logic, or silently change qualification/exit rules.

Daily-candle eligible strategies:
- **EXPIRY78** — existing `evaluate_expiry78_contract` seven-rule replay. Requires NSE FO option OHLCV, contract identity/expiry and expiry-day underlying close evidence. Rupee P&L requires historical position quantity/lot size and a separately validated charges model.
- **ORIGINAL366 / RECOVERED** — existing `evaluate_original366_rows` replay against the explicitly qualified ORIGINAL366 cohort. It must not be run across all NSE contracts.
- **RECOVERY** — existing verified recovery lifecycle. A plain RE-ENTRY classification is not sufficient proof.

Intraday-only strategies:
- **ORB Morning** — existing tick/3-minute-candle opening range, retest, confirmation and next-tick exit behavior.
- **ORB Afternoon** — existing 12:57–13:00 range and first-tick breakout behavior.

ORB must remain unavailable in a daily-only backtest. It can be enabled only when the historical source provides the required intraday observations and execution sequence.

## Current implementation in this branch

- Authenticated `GET /api/v1/backtest/strategies` exposes strategy definitions, data requirements and eligibility.
- The registry does not run a backtest or claim P&L. This is deliberate: no run may be marked complete until historical data validation, exact strategy replay, P&L/charges treatment and persistence are implemented and tested.

## Next implementation gates

1. Add monthly/quarterly NSE data coverage validation and dataset version/fingerprint.
2. Implement the EXPIRY78 adapter using the existing evaluator and NSE FO daily bars; preserve historical lot size and explicitly label unavailable quantity/charges rather than fabricating net rupee P&L.
3. Integrate ORIGINAL366 and RECOVERY only against their verified cohort/evidence inputs and existing evaluators.
4. Add durable run, selected-strategy, trade-ledger and summary persistence with tenant isolation and idempotent reuse for identical period + dataset + strategy version + parameters.
5. Add explicit force-rerun/versioning, monthly/quarterly result retrieval and UI checkboxes (single/multiple/all).
6. Add intraday historical data adapter before enabling ORB replay.
7. Test no look-ahead, missing sessions, same-candle ambiguity, charges, drawdown, reproducibility and no-order execution guard.

All historical runs are research-only and must never submit broker orders.

## EXPIRYSCAN historical report

- Authenticated `GET /api/v1/backtest/expiryscan?start_date=2026-10-01&end_date=2026-10-31` returns the preserved 27-Oct-2026 historical cohort when the requested period contains that expiry.
- The report returns the 11 preserved contract summaries, the recorded 191 daily-observation count, historical entry date/premium, low/high summary, last-traded close, expiry intrinsic and premium-point/percentage outcome.
- The expected pre-expiry review/closing date for this pinned cohort is 26-Oct-2026, grounded in the preserved 26-Oct option-bhavcopy source. It is a planned date, not evidence of an executed close.
- The strategy catalogue exposes `available_for_historical_report=true` separately from `available_for_daily_backtest=false`. EXPIRYSCAN is selectable for its historical cohort report but is not misrepresented as a complete daily-candle replay.
- The referenced `AIR_EXPIRYSCAN_EXPIRED_27Oct2026_11Contracts_DailyDetail.xlsx` is not present in this repository branch. Therefore this endpoint reports contract-level summary evidence and explicitly marks daily-detail rows pending. It does not reconstruct OHLC/qualification chronology or infer bid/ask liquidity from daily candles.
- No rupee P&L is claimed without verified quantity, lot-size treatment, charges and slippage. No broker orders are submitted.


## Month replay and shared lifecycle rules

- The historical month endpoint supports both signal-month and expiry-month selection. Signal-month replay includes eligible contracts expiring in the selected month or later, so a signal is not dropped because its contract expires in a future month.
- EXPIRY78 historical replay calls the same `evaluate_expiry78_contract` function used by the live strategy view. The strategy formula is not forked for historical reporting.
- A daily bar where the assumed entry touch and initial stop are both reached on the entry date is `UNRESOLVED`, not a confirmed stop-loss: daily OHLC does not prove intraday ordering.
- Trade ledger marks are per trade. Closed positions use their own exit/settlement price; open or unresolved positions use the latest retained valid EOD mark. Days to expiry is measured from the modelled entry date.
- The historical adapter labels daily-low fills as modelled, not broker-confirmed executions. It does not infer sector, entered quantity/lots, or rupee P&L without source evidence.
- Other strategy tabs are only replayable when their own existing evaluator and required historical evidence are connected; unsupported strategies remain explicitly `NOT_REPLAYED`.
