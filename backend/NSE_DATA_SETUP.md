# NSE CM and F&O historical data bootstrap

AIR downloads the official NSE UDiFF Common Bhavcopy Final archives for both Capital Market (CM) and Futures & Options (FO).

## Initial bootstrap

On API service startup, `AIR_NSE_BOOTSTRAP_ENABLED=true` (default in Docker Swarm) queues a background bootstrap for the previous **three calendar months**. It checks weekdays, imports available NSE sessions, skips weekends/holidays where NSE publishes no archive, and retries transient HTTP errors. CM and FO downloads are paired by trading date.

The original ZIP archives are retained under `/var/lib/air/nse_archives/{CM,FO}/YYYY-MM-DD.zip`. Normalized EOD rows, import status and coverage metadata are persisted in `/var/lib/air/nse_bhavcopy.sqlite3`, on the same persistent `air_data` volume as the rest of AIR. A service restart does not re-download successfully imported files. Failed dates can be retried by the operator.

The API performs the initial download in the background so health checks and login can come up while history is being prepared. The Home dashboard and Data tab show the bootstrap progress and coverage. The app polls progress while the bootstrap is running. The Data tab provides separate CM and FO views, symbol search, and FO Options/Futures filters.

## Automatic refresh and operator retry

- Daily refresh: 18:15 Asia/Kolkata, Monday to Friday.
- Authenticated status: `GET /api/v1/nse-data/status`
- Authenticated rows: `GET /api/v1/nse-data/rows?market=CM|FO&symbol=NIFTY&limit=150`
- Operator-only retry: `POST /api/v1/nse-data/bootstrap`

The system reports READY only when at least 45 paired CM/FO sessions are present in the three-calendar-month window and there are no failed downloads. A PARTIAL/FAILED state is visible and can be retried; AIR must not represent incomplete coverage as ready.

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
