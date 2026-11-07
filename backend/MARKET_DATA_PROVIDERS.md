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

The provider catalog deliberately separates broker account/login support from actual
historical/live market-data adapter readiness. A catalog entry is not displayed as a
working feed until its adapter is implemented and verified. AIR currently allows
only verified adapters to be enabled. This prevents a saved API key or an account
assignment from being mistaken for a functioning data connection.

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
operator-controlled live verification have passed. NSE official EOD bhavcopy remains
the historical fallback for supported daily CM/FO data; it is not a live feed and
does not provide intraday candles or bid/ask history.
