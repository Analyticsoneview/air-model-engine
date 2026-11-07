# AIR market-data provider selection

AIR keeps historical and live market-data sources independent. An administrator can
select a different provider for each channel from **AIR Admin → Market Data Sources**.
Selections are persisted in `AIR_MARKET_SOURCE_DB_PATH` (default
`data/air_market_sources.sqlite3`) and Dhan feed selections are reconnected on API
startup when the operator account and encrypted credentials are available.

## Current adapter readiness

| Provider | Historical | Live | Current integration status |
|---|---:|---:|---|
| NSE official CM/FO Bhavcopy | Ready | — | Official EOD daily history already imported and reconciled by AIR |
| DhanHQ | Ready | Ready | Existing REST historical and WebSocket market-feed adapter |
| Zerodha Kite Connect | Pending | Pending | Broker account/OAuth integration exists; normalized market-data adapter is not wired into the source router |
| Upstox API | Pending | Pending | Broker account/OAuth integration exists; normalized market-data adapter is not wired into the source router |
| FYERS API | Pending | Pending | Broker account/OAuth integration exists; normalized market-data adapter is not wired into the source router |
| Angel One SmartAPI | Pending | Pending | Broker login integration exists; normalized market-data adapter is not wired into the source router |
| External vendor adapter | Extension point | Extension point | Vendor-specific contract, credentials, SDK/API and entitlement checks are required |

The provider catalog separates account/login support from market-data adapter readiness.
Dhan, Zerodha, Upstox, FYERS and Angel One now have native streaming adapter
implementations in the codebase alongside normalized historical REST adapters. The
implementations use the brokers' supported WebSocket SDKs and reconnect features.
They are not yet certified against the user's actual accounts. A source becomes
authenticated when the profile handshake succeeds; actual quote delivery is only
confirmed after valid instrument subscriptions produce fresh ticks. AIR never treats
an account assignment or saved API key alone as a connected feed. Upstox V3 uses its
official Protobuf-aware SDK, not an assumed JSON feed.

## Scope of the first provider-selection milestone

The admin source selector and router now persist and apply independent historical/live
choices for the market-data gateway. The NSE Bhavcopy choice identifies the existing
official EOD store; Dhan can be authenticated independently for historical and live
gateway requests. The existing strategy EOD import/replay remains anchored to the NSE
CM/FO archive pipeline, and AIR QOC option-chain capture remains on its Dhan-specific
workflow. A later source-normalization step is still required before every strategy
can consume arbitrary selected vendor history/live ticks through one provider-neutral
ingestion path. Do not assume that changing a gateway source changes the NSE EOD
backfill or QOC capture source.

## Admin API

- `GET /api/v1/operator/market-data/sources` — provider catalog, saved selections and runtime state.
- `PUT /api/v1/operator/market-data/sources/historical` — select/enable/disable the historical source.
- `PUT /api/v1/operator/market-data/sources/live` — select/enable/disable the live source.

Example historical source:

```json
{
  "provider": "nse_bhavcopy",
  "account_id": null,
  "enabled": true
}
```

Example Dhan live source:

```json
{
  "provider": "dhan",
  "account_id": "YOUR_DHAN_CLIENT_ID",
  "enabled": true
}
```

Dhan must already be assigned to the operator and its credentials must be stored in
the encrypted credential vault. Enabling a source performs a real provider
authentication handshake. Failed authentication leaves the runtime channel offline.
Historical and live channels can point to different accounts/providers. No automatic
provider failover is performed.

## External vendor connector contract

AIR includes a configurable JSON vendor adapter. Add an **External Market-Data Vendor**
account in AIR Admin and save encrypted `base_url`, `websocket_url`, and `api_key`.
The vendor must expose this contract:

- `GET /health` — authenticated JSON success response.
- `GET /instruments?q=...&limit=...&segment=...` — `{"instruments":[{"exchange","symbol","token","segment"}]}`.
- `GET /history?token=...&symbol=...&from=...&to=...&interval=...` — `{"candles":[{"time","open","high","low","close","volume","open_interest"}]}`.
- WSS — accepts `{"action":"subscribe","tokens":["..."]}` and `{"action":"unsubscribe","tokens":["..."]}`; emits JSON ticks with `token`, `ltp`, optional OHLCV/OI, bid/ask and timestamp.

The connector defaults to `Authorization: Bearer <api_key>`. Vendor-specific paths and
auth header/prefix can be stored in the encrypted credential record. Vendors with a
different protocol require a dedicated subclass/mapper and must not be marked verified
until tested against their actual API. This generic connector does not mean that
unidentified data vendors are already integrated.

## Instrument-token mapping

Broker instrument tokens are account/provider-specific. The admin UI supports a
single mapping at a time; for full broker masters, the operator API also supports
bulk import:

- `GET /api/v1/operator/market-data/instruments?provider=zerodha&account_id=...`
- `POST /api/v1/operator/market-data/instruments`
- `POST /api/v1/operator/market-data/instruments/bulk` (up to 5,000 rows per request)
- `DELETE /api/v1/operator/market-data/instruments/{provider}/{account_id}/{token}`

Bulk import accepts provider account ID plus rows containing exchange, trading
symbol, provider token/key and segment. Optional expiry, strike, option type, lot
size and instrument type can also be stored in the directory. The common instrument
search endpoint checks this directory before asking the provider adapter for its
native instrument master.

## Vendor adapter contract

Every additional broker/vendor adapter must implement the common AIR
`MarketDataAdapter` contract: authentication, instrument search, historical bars,
live subscribe/unsubscribe and clean shutdown. Provider-specific timestamps,
instrument tokens, exchange segments, OHLCV, OI and quote depth must be normalized
before entering AIR strategy pipelines. Each adapter must include:
- Credential and entitlement validation with no secret logging.
- Instrument-master mapping and symbol/expiry/strike/option-type normalization.
- Historical range/interval support and pagination/rate-limit handling.
- Live WebSocket reconnect, heartbeat, stale-feed and disconnect status.
- Source timestamps, exchange timezone normalization and duplicate protection.
- Contract tests using sanitized fixtures plus an opt-in live handshake test.

Vendor-specific implementations are not marked READY until these checks and an
operator-controlled live verification have passed. The generic custom-vendor entry
is an extension point only; no unnamed third-party vendor is falsely advertised as
connected. Admins can save broker-specific instrument token mappings through
**AIR Admin → Market Data Sources**; broker tokens are not interchangeable. Until a
provider-specific master importer is implemented, those mappings must be sourced
from the broker's official instrument master. NSE official EOD bhavcopy remains
the historical fallback for supported daily CM/FO data; it is not a live feed and
does not provide intraday candles or bid/ask history.
