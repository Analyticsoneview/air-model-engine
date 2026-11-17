# AIR initial market-data and contract-universe requirements

## Initial historical window

- The first-run NSE CM and FO UDiFF EOD bootstrap defaults to the latest **3 calendar months**.
- The installer must not silently expand the initial history window to 12 months.
- A later on-demand backfill accepts an explicit date range and extends coverage incrementally without overwriting validated sessions.
- The raw NSE archive, normalized rows, source URL, session date, import status, record counts and missing-session diagnostics remain auditable.
- Three months is a raw-data bootstrap setting; preserved September/October reference workbooks are imported independently and remain immutable.

## Contract universe is not limited by the historical window

- The contract universe is sourced from NSE's daily F&O MII contract file, not inferred only from contracts appearing in the three-month bhavcopy history.
- Import the NSE-exclusive contract file for the effective trading date and retain its original compressed source file, source URL, effective date, checksum and parser/schema version.
- Preserve every eligible NSE stock/index derivative contract and every published expiry, including far-month expiries such as December, January, February and March when present in the official file.
- Include both CE and PE options; retain futures separately for underlying/context use.
- Store symbol, exchange instrument/security identifier, instrument/segment type, expiry, strike, option type, lot size, tick size, contract start/listing state and source snapshot identity where supplied.
- Do not hardcode expiry months, month counts, or a November-only list. Future contracts become selectable as soon as they appear in a validated NSE contract-master snapshot.
- Preserve historical contract-master snapshots so a backtest can resolve the contract universe as it existed on the signal date. Do not use today's master to rewrite prior eligibility.
- Expired contracts remain queryable for historical research; current eligibility is derived from the date-effective snapshot and strategy rules.

## Bootstrap/readiness gates

- A successful initial market-data bootstrap requires the three-month CM/FO archive coverage checks and a validated current NSE F&O contract-master snapshot.
- Contract-master validation must reject empty files, malformed rows, duplicate instrument identifiers, invalid expiries and files with no eligible CE/PE contracts.
- The admin/data-readiness view must separately report EOD history coverage and contract-master snapshot date/count/expiry range. A complete bhavcopy download alone is not proof that future expiries are loaded.
- If NSE contract-master download or validation fails, retain the last known-good snapshot, report the precise failure, and do not report contract-universe readiness.
- A December/March expiry contract may qualify for a November signal if it exists in the signal-date contract-master snapshot and meets that strategy's configured DTE, liquidity and other evidence requirements.

## Data integrity boundaries

- Daily UDiFF bhavcopy supports daily OHLCV research only.
- ORB replay still requires timestamped intraday bars/ticks.
- EXPIRYSCAN/QOC historical replay still requires point-in-time option-chain observations with the necessary bid/ask, volume and OI evidence.
- Never fabricate unavailable data or substitute daily bhavcopy for intraday/point-in-time evidence.
- Signal date, contract expiry, entry date and exit date are independent fields.

## Official NSE reference

NSE's All Reports – Derivatives page publishes the daily F&O-MII contract file (.gz), separately identifies NSE-exclusive and NSE/BSE contract files, and lists the UDiFF bhavcopy. NSE circular FAOP73629 describes the F&O contract-file nomenclature and effective availability from 13-Apr-2026. AIR uses the NSE-exclusive file for NSE-only research unless a separately approved interop scope is requested.
