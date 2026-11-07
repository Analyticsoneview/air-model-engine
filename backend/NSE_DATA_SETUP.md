# NSE CM and F&O historical data bootstrap

AIR downloads the official NSE UDiFF Common Bhavcopy Final archives for both Capital Market (CM) and Futures & Options (FO).

## Initial bootstrap

On API service startup, `AIR_NSE_BOOTSTRAP_ENABLED=true` (default in Docker Swarm) queues a background bootstrap for the previous **three calendar months**. It refreshes the official NSE trading-holiday calendar for CM and FO, checks eligible weekdays, excludes notified CM holidays, imports available sessions, and retries transient HTTP errors. CM and FO holiday lists are stored separately because the segments can differ. CM and FO downloads are paired by trading date.

The original ZIP archives are retained under `/var/lib/air/nse_archives/{CM,FO}/YYYY-MM-DD.zip`. Normalized EOD rows, import status and coverage metadata are persisted in `/var/lib/air/nse_bhavcopy.sqlite3`, on the same persistent `air_data` volume as the rest of AIR. Each imported market/date stores the normalized unique-record count parsed from the official NSE CSV. Before a session is treated as complete, AIR compares that NSE source count with both the import ledger and the actual SQLite row count. If either CM or FO is missing or mismatched, AIR marks the session PARTIAL, removes both CM and FO rows for that date, and downloads/imports the eligible market archives again as one repair cycle. This also backfills a source-count baseline for older imports that predate the reconciliation feature.

The API performs the initial download in the background so health checks and login can come up while history is being prepared. A restart also performs missed-session recovery; already imported archives are skipped. The Home dashboard and Data tab show the bootstrap progress and coverage. The app polls progress while the bootstrap is running. The Data tab provides separate CM and FO views, symbol search, and FO Options/Futures filters.

## Automatic refresh and operator retry

- Daily post-market refresh: 21:00 Asia/Kolkata, Monday to Friday (only when the exchange calendar indicates a trading day).
- Startup recovery: every API restart queues an idempotent reconciliation. It resumes from the last paired CM+FO imported session while preserving the rolling three-calendar-month window, so missed sessions are backfilled after downtime.
- Calendar cache: NSE `holiday-master?type=trading` for CM and FO, persisted in the same SQLite metadata store and shown in the Data Center. If NSE is temporarily unreachable, the last persisted calendar is used and the refresh error is surfaced in status.
- Authenticated status: `GET /api/v1/nse-data/status`
- Authenticated rows: `GET /api/v1/nse-data/rows?market=CM|FO&symbol=NIFTY&limit=150`
- Operator-only retry: `POST /api/v1/nse-data/bootstrap`

The bootstrap status includes the number of sessions checked, partial sessions detected, automatic repairs triggered, and the per-market NSE-source-versus-app-DB counts for mismatches. After each successful bootstrap/reconciliation, AIR removes FO rows whose contract expiry is before the current India-local date from the active NSE FO table. Expiry-day contracts remain until the following day. Per-session removed-row counts are tracked so intentional cleanup does not trigger false partial-session repairs; the original daily NSE ZIP archives remain retained. This cleanup touches only the NSE market-data database: it does not delete or rewrite model strategy signals, lifecycle outcomes, daily-bar evidence, or P&L records. The Data Center shows the cleanup count. The Data Center refreshes visible rows when a reconciliation/download batch changes, even if the overall row count stays the same. The system reports READY only when at least 45 paired CM/FO sessions are present in the three-calendar-month window and there are no failed downloads. A PARTIAL/FAILED state is visible and can be retried; AIR must not represent incomplete coverage as ready.

## Expired-contract strategy and P&L history

The active FO table contains only contracts that have not passed their expiry date. Before expired rows are removed, AIR matches them to existing strategy ledger signals by symbol, expiry, strike and CE/PE, and snapshots missing daily option bars into each matching signal's `evidence.daily_option_bars`. The snapshot adds OHLC, traded quantity and underlying close through expiry. It does not overwrite the signal lifecycle, entry/exit fields, quantity or existing P&L values. If no matching strategy signal exists, original NSE ZIPs remain available for later reprocessing. The P&L calendar returns expired trade history separately and classifies known expiry outcomes as win, loss or breakeven; unknown quantity/valuation remains pending rather than being estimated.

## Data included

CM rows include symbol, instrument ID, ISIN, OHLC, previous close, last/settlement price, volume, turnover and trade count.

FO rows include symbol, contract type, expiry, strike, CE/PE, OHLC, previous close, last/settlement price, underlying price, volume, turnover, trade count, open interest, change in OI and lot size.

## Important scope and data-quality boundaries

These files are official **end-of-day bhavcopies**. They are suitable for historical daily price/volume/OI research, contract filtering, expiry studies and daily backtests. They are not intraday candles, tick-by-tick history, historical bid/ask quotes or a full intraday option-chain snapshot. Do not derive intraday liquidity/spread or premium acceleration from this source alone.

NSE can change archive availability, request throttling and file schema. The downloader validates ZIP/CSV content, retains the raw archives for reprocessing and records failed dates. The current implementation uses the post-08-Jul-2024 UDiFF CM and FO archive formats; legacy pre-UDiFF bhavcopy formats are not silently mixed into this dataset.

## Deployment settings

Docker Swarm configures:

```text
AIR_NSE_DB_PATH=/var/lib/air/nse_bhavcopy.sqlite3
AIR_NSE_ARCHIVE_DIR=/var/lib/air/nse_archives
AIR_NSE_BOOTSTRAP_ENABLED=true
```

Reserve several GB of free disk space for the normalized F&O history and retained archives. For a production node, monitor free disk and backup the AIR data volume.
