# AIR market-data provider selection

AIR keeps historical and live market-data sources independent. **AIR Admin → Market
Data Sources** manages the operator's global diagnostic gateway. Customer strategy
requests use the separate customer-isolated runtime described in Point 9 below; the
global diagnostic selector never changes another customer's strategy data source.
Global selections are persisted in `AIR_MARKET_SOURCE_DB_PATH` (default
`data/air_market_sources.sqlite3`) and restored on API startup.

## Current adapter readiness

| Provider | Historical | Live | Current integration status |
|---|---:|---:|---|
| NSE official CM/FO Bhavcopy | Ready | — | Official EOD daily history already imported and reconciled by AIR |
| DhanHQ | Ready | Ready | Existing REST historical and WebSocket market-feed adapter |
| Zerodha Kite Connect | Implemented | Implemented | Account-scoped historical REST and KiteTicker adapter; live account verification required |
| Upstox API | Implemented | Implemented | Account-scoped historical REST and MarketDataStreamerV3 adapter; live account verification required |
| FYERS API | Implemented | Implemented | Account-scoped historical REST and Data Socket adapter; live account verification required |
| Angel One SmartAPI | Implemented | Implemented | Account-scoped historical REST and SmartWebSocketV2 adapter; network identity and live verification required |
| External vendor adapter | Extension point | Extension point | Vendor-specific contract, credentials, SDK/API and entitlement checks are required |

FYERS master refresh uses the official ticker-keyed JSON symbol masters for NSE CM,
NSE FO, BSE CM and BSE FO. The importer normalizes FYERS Fytoken, ticker, exchange,
segment, underlying, option side, strike, expiry and lot-size fields into the AIR
instrument directory. FYERS documents one master file per exchange segment and
publishes the official NSE/BSE URLs at
https://fyers.in/api-docs/v3/api/market-information/symbol-master/symbol-master-json/.

The provider catalog separates account/login support from market-data adapter readiness.
Dhan, Zerodha, Upstox, FYERS and Angel One now have native streaming adapter
implementations in the codebase alongside normalized historical REST adapters. The
implementations use the brokers' supported WebSocket SDKs and reconnect features.
They are not yet certified against the user's actual accounts. A source becomes
authenticated when the profile handshake succeeds; actual quote delivery is only
confirmed after valid instrument subscriptions produce fresh ticks. AIR never treats
an account assignment or saved API key alone as a connected feed. Upstox V3 uses its
official Protobuf-aware SDK, not an assumed JSON feed.

## Customer strategy data paths (Point 9)

AIR exposes one shared strategy feed and two data-source paths. Strategy rules,
qualification criteria, scoring and result schemas are not forked by customer tier.

### Standard / normal customers

- NSE official CM/FO UDiFF bhavcopy is the default historical source.
- Initial load, scheduled daily refresh and recovery/retry continue through the
  existing NSE bootstrap pipeline.
- Strategy endpoints hydrate published signals from the NSE EOD store when data is
  available, then run the same deterministic strategy evaluators.
- No broker connection or paid entitlement is required for the standard NSE path.
- NSE bhavcopy is EOD only; it cannot supply live ticks or intraday bid/ask evidence.

### AIR operator and paid customers

- An AIR operator can activate broker data for an assigned customer account.
- A PAID entitlement must be explicitly enabled by an AIR operator. This repository
  currently provides operator-managed entitlement controls; it does not integrate a
  subscription billing/payment provider.
- The customer must have an assigned broker account and saved encrypted credentials.
  The selected account is authenticated before its source is activated.
- Each customer receives an isolated market-data router and tick hub. One customer's
  broker selection, tokens, feed or cache are not shared with another customer's
  strategy request.
- Historical strategy evidence is normalized into the same daily-bar contract used
  by the strategy evaluators. EXPIRYSCAN uses that customer's live broker source and
  remains unavailable when no live broker source is enabled.
- When a customer returns to STANDARD access, the broker selection is cleared and
  strategy hydration returns to the NSE EOD path.

The operator-published signal feed is shared with authenticated customers; customer-
owned records override matching signal IDs only within that customer's view. The
first identity in `AIR_OPERATOR_CUSTOMER_IDS` is the canonical publisher. Customer-
specific market data enriches the shared strategy evidence without changing strategy
rules or leaking another customer's broker feed.

Admin/customer endpoints:
- `GET /api/v1/customer/market-data/access` — effective entitlement and selected source.
- `PUT /api/v1/customer/market-data/selection` — paid customer selects an assigned broker account.
- `DELETE /api/v1/customer/market-data/selection` — return to NSE EOD source.
- `PUT /api/v1/operator/customers/{customer_id}/market-data-access` — grant/revoke PAID broker-data entitlement.
- `PUT /api/v1/operator/customers/{customer_id}/market-data-selection` — assign and activate the customer's broker source.
- `GET /api/v1/operator/broker-accounts` — shows entitlement and selected source alongside account ownership.

Daily broker instrument-master refresh now iterates all assigned customer accounts,
not only the operator's own account. Master snapshots remain keyed by provider and
account ID. Successful broker authentication still does not prove fresh market ticks;
run the provider verification during market hours before relying on live data.

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

## Native streaming and live verification

- Zerodha uses KiteTicker with the provider's binary tick decoder and reconnect.
- Upstox uses MarketDataStreamerV3 and its protobuf-decoding SDK.
- FYERS uses the Data Socket SymbolUpdate stream and SDK reconnect.
- Angel One uses SmartWebSocketV2 and its retry behavior.
- Dhan uses the AIR feed socket with reconnect and subscription restoration.

The admin verification API is `POST /api/v1/operator/market-data/verify/{channel}`.
It tests a mapped instrument. Historical verification requires recent candles. Live
verification requires a tick for the exact mapped token during the verification
window. Profile login alone is not proof of a working subscription. Run live
verification during market hours and with a valid data entitlement.

## Custom vendor connector

A generic encrypted-credential connector supports vendors exposing HTTPS JSON history
and a JSON WebSocket feed. Add a `custom_vendor` account and save `base_url`,
`websocket_url`, `api_key`, and optional `health_path`, `instruments_path`,
and `historical_path`. Endpoints must use HTTPS/WSS. Default JSON responses use
`data` or `instruments` for instrument lists, `candles`/`bars` for history,
and `token`, `ltp`, OHLCV, OI and quote fields for ticks. A vendor with a different
schema requires a provider-specific subclass. This generic connector does not claim
compatibility with an unnamed vendor or bypass its subscription/licensing terms.

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
