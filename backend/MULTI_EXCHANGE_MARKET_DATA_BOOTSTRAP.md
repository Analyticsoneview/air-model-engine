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


## Global markets extension — United States and GIFT City

US-listed instruments are a separate market-data domain, not an extension of Indian exchange bhavcopy files. An Indian broker's ability to offer a US security does not make that security an NSE/BSE listing, and broker availability must not be treated as proof of exchange-wide coverage.

### Initial coverage targets

| Market / venue | Required catalogue and data | Implementation boundary |
|---|---|---|
| Nasdaq-listed venues | All eligible listed common stocks, depositary receipts, ETFs and other explicitly supported instrument types | Use a licensed US-market data/reference-data provider or authorized exchange feed; preserve listing venue and US ticker |
| NYSE | All eligible listed equities and supported ETFs | Independent venue mapping, sessions, holidays, corporate actions and symbol lifecycle |
| NYSE Arca and other US venues | Eligible listed ETFs/equities where provider coverage and licence permit | Explicit venue allow-list and coverage reporting; do not imply every US venue is covered by Nasdaq/NYSE adapters |
| NSE IX / GIFT City | US-stock receipts and other supported NSE IX instruments | Treat each receipt as a distinct exchange-traded instrument; retain underlying-security mapping and receipt ratio/corporate-action metadata |
| India-broker global-access catalogues | US instruments available to each connected broker/account type | Broker-specific tradability catalogue only; never use it as the canonical US exchange instrument master |

### US-market data requirements

1. Maintain a global instrument identity with MIC/venue, ticker, issuer, instrument type, currency, listing/delisting dates, primary listing and stable provider/exchange identifiers. Preserve ticker changes and delisted instruments for historical resolution.
2. Ingest daily OHLCV and available turnover/volume fields, split/dividend-adjusted series or adjustment factors, corporate actions, security master/reference data and venue trading calendars. Store raw and adjusted values distinctly.
3. Keep US exchange-local timestamps and America/New_York session calendars, including daylight-saving transitions and market holidays. Do not assume India trading dates align with US sessions.
4. Store native USD prices and FX observations (including source and timestamp) separately. Convert to INR only as a derived valuation; never overwrite native prices.
5. Keep live, delayed and EOD feeds as separate data products with explicit provider, entitlement, latency/freshness and licence metadata. EOD availability does not imply live or intraday entitlement.
6. Use provider/exchange agreements that explicitly permit AIR's intended storage, analytics, display, derived-data and redistribution use. A public webpage, broker screen or downloadable file is not by itself a commercial data licence.
7. Report readiness independently by provider, venue, instrument type and data frequency. If coverage, history depth, fees, entitlement or redistribution rights are unresolved, mark the relevant scope BLOCKED/DEFERRED with a reason; never label the whole US market READY.
8. Broker catalogues must include broker, country/account eligibility, instrument identifier, tradability state, restrictions, effective dates and last refresh. A security may exist in the global master while unavailable to a particular Indian broker.
9. Add tests for symbol changes, delistings, splits, dividends, ADR/receipt mappings, duplicate tickers across venues, daylight-saving transitions, US holidays, missing sessions, provider outages, entitlement denial, stale broker catalogues and FX timestamp alignment.

### GIFT City receipt identity

NSE IX-listed US-stock receipts are not the same instrument as the underlying Nasdaq/NYSE shares. Store separate instrument records linked by an explicit underlying relationship, receipt ratio, currency, venue, trading calendar and corporate-action mapping. Do not merge their prices, volumes, liquidity or trading eligibility with the underlying US share.

### Licensing and delivery gates

Before enabling any US venue in a production installation, record the selected provider, supported venues/instrument classes, historical depth, update frequency, commercial usage rights, display/redistribution permissions, user-count constraints, fees and credentials/entitlements. Use adapter contract tests and sandbox/sample datasets until the provider agreement and credentials are approved. Live feed acceptance remains a separate gate from EOD bootstrap.

### Research universe separation

US equities/ETFs, GIFT City receipts and broker-accessible US instruments are independent filterable universes over the global instrument directory. They must not be limited by the Nifty 500 universe or by an Indian broker's current catalogue. Strategy eligibility may filter instruments; it must never constrain raw market-data ingestion.
