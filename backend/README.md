# AIR Broker Integration Layer

AIR uses a broker-adapter architecture. The mobile app talks only to the AIR backend; broker credentials and tokens never belong in the APK or PWA.

## Supported adapter targets
- Angel One SmartAPI
- DhanHQ
- Zerodha Kite Connect
- Additional brokers can be added by implementing the BrokerAdapter contract.

## Integration contract
Each adapter must normalize:
- authentication/session lifecycle
- instrument master and symbol/token resolution
- quotes, WebSocket ticks and historical candles
- funds, positions, holdings and order book
- place, modify, cancel and order-status operations

Broker-specific differences remain inside adapters. AIR strategies consume normalized market data and order models.

## Execution safety
- Paper mode is the default.
- Live execution must be explicitly enabled per broker account on the backend.
- Every live order requires a valid authenticated account, resolved instrument, quantity/lot-size validation, funds/risk checks, idempotency key and a final user confirmation.
- The backend must persist the broker order ID and reconcile status/fills; an accepted API request is not treated as a fill.
- No strategy may place an order directly. Strategies produce a signal/order intent; the execution service validates and routes it.
- Credentials, PINs, TOTP seeds, API secrets and access tokens must be stored server-side in a secret manager or encrypted credential store. Never commit them or embed them in Flutter.

## Status
This is the integration foundation and contract, not a connected broker implementation. Live credentials, backend deployment, broker-specific adapters, and end-to-end sandbox/live verification are still required before orders can be sent.
