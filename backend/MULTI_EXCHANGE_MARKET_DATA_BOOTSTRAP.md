# AIR multi-exchange market-data bootstrap scope

## Product requirement

AIR installation must bootstrap the full configured market-data catalogue for every enabled exchange and segment. The 500-symbol Nifty 100 + Nifty Midcap 150 + Nifty Smallcap 250 set is a **strategy/research universe**, not a download filter and not the boundary of the market-data store.

The ingestion catalogue and strategy universes are separate:
- Ingestion stores all eligible instruments/contracts published by enabled official exchange sources.
- Strategy universes (for example Nifty 500 constituents) are versioned filters over the broader instrument directory and may be expanded independently.
- No exchange-wide archive may be silently reduced to current index constituents.

## Initial exchange/segment coverage target

| Exchange | Segment | Required EOD data | Notes |
|---|---|---|---|
| NSE | CM / EQ | All available cash-market securities, including mainboard and SME where the official source provides them | Not limited to Nifty 500 |
| NSE | FO | All available futures and options contracts, including stock and index derivatives | Preserve expiry, strike, CE/PE, volume and OI |
| NSE | CD | Currency-derivative contracts | Separate exchange calendar and schema validation |
| NSE | COM | Commodity-derivative contracts | Separate exchange calendar and schema validation |
| BSE | CM | All available cash-market securities | Include BSE-only securities |
| BSE | FO | All available derivatives contracts | Preserve full contract identity |
| BSE | CD | Currency-derivative contracts | Separate segment |
| BSE | CO | Commodity-derivative contracts, when official daily files are available | Verify availability and retention limits |
| MCX | Commodity derivatives | All available commodity futures/options contracts and daily bhavcopy fields | Official MCX bhavcopy/history source |
| NCDEX | Agricultural/commodity derivatives | All available contracts and daily bhavcopy fields | Official NCDEX UDiFF and historical source |

The catalogue must be source-driven and extensible. A segment is marked READY only when its official source is configured, its expected trading sessions are reconciled, and instrument/contract coverage is validated. If a source has access restrictions, paid-data requirements, unavailable historical dates or format changes, expose that segment as BLOCKED/DEFERRED with the reason; do not silently report global market-data readiness.

## Ingestion and persistence requirements

1. Use exchange/segment-specific source adapters. Do not reuse the NSE CM/FO URL pattern for other segments.
2. Maintain independent exchange calendars, trading sessions, holidays, archive naming rules, parsers and source-count reconciliation for each exchange/segment.
3. Persist raw source files and normalized rows. Keep provenance: exchange, segment, trade date, source URL/provider, source file hash, schema version, import timestamp, source row count, normalized row count and validation result.
4. Use stable contract identity including exchange, segment, instrument ID, symbol, expiry, strike, option side and other source keys as applicable.
5. Make each exchange/segment/trade-date import idempotent and atomic. A failed or corrupt file must not leave stale or partial rows exposed as complete.
6. Resume missing/corrupt dates on restart; reconcile raw-file checksum, source row count and database row count.
7. Keep historical data retention configurable by exchange/segment and disk budget. Never delete expired derivatives history needed by AIR strategy evidence/backtests merely because a contract expired.
8. Download instrument/security/contract masters independently from daily bhavcopies. Master refresh must cover every enabled segment and retain snapshots for symbol mapping and delisted/expired contract resolution.
9. Expose progress and readiness by exchange and segment, plus an aggregate status. A partial segment must not be hidden by a successful NSE CM/FO import.
10. Installer performs initial bootstrap after persistent storage and services are healthy. API liveness may come up earlier, but data readiness stays pending until all required configured segments meet their declared policy.

## Research-universe separation

- Nifty 100 + Nifty Midcap 150 + Nifty Smallcap 250 (500 unique constituents) remains one AIR equity screening universe.
- Add independent universe definitions for all NSE/BSE cash securities, NSE/BSE derivatives, currency contracts, MCX commodities and NCDEX commodities.
- Strategy selection may filter the shared instrument directory by exchange, segment, instrument type, underlying, expiry, liquidity and strategy eligibility.
- A strategy universe must never control which raw bhavcopy rows are downloaded or retained.

## Data scope and acceptance boundaries

- Daily bhavcopy is EOD OHLC/volume/value/OI/settlement data according to the source schema. It is not tick history, intraday candles, order-book depth, historical bid/ask or a full intraday option-chain snapshot.
- Live and intraday data remain separate provider/broker channels with their own entitlements and freshness checks.
- Validate one representative date and a multi-session backfill for every enabled segment, including archive integrity, parser coverage, source-vs-database counts, restart recovery and queryability.
- Test source outages, holidays, no-file dates, schema drift, duplicate contracts, expired contracts, missing masters, disk exhaustion and partial installation restart.
- Do not claim a segment is supported solely because a broker instrument master contains its symbols; historical bhavcopy ingestion is a separate capability.

## Official source references to verify during adapter implementation

- NSE equity reports: https://www.nseindia.com/all-reports
- NSE derivatives reports (FO and commodity COM reports): https://www.nseindia.com/all-reports-derivatives
- BSE market bhavcopy: https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx
- MCX historical data: https://www.mcxindia.com/market-data/historical-data
- MCX bhavcopy: https://www.mcxindia.com/market-data/bhavcopy
- NCDEX bhavcopy: https://ncdex.com/markets/bhavcopy

Exchange sources, archive retention, history depth and access terms must be verified per segment before marking it production-ready.
