"""Broker catalog exposed to authenticated AIR clients.

The catalog is descriptive only. A provider is not marked connected or verified
until its provider-specific authorization adapter completes a real handshake.
"""

BROKER_CATALOG = [
    {
        "code": "angelone",
        "name": "Angel One SmartAPI",
        "auth_mode": "client_code_pin_totp",
        "market_data": "historical_rest_and_smart_stream",
        "execution": "orders_positions_holdings_rest",
        "authorization_ready": False,
    },
    {
        "code": "dhan",
        "name": "DhanHQ",
        "auth_mode": "access_token_or_totp_api",
        "market_data": "historical_rest_and_market_feed_websocket",
        "execution": "orders_positions_holdings_rest",
        "authorization_ready": False,
    },
    {
        "code": "zerodha",
        "name": "Zerodha Kite Connect",
        "auth_mode": "oauth_request_token_checksum_exchange",
        "market_data": "historical_rest_and_kite_ticker_websocket",
        "execution": "orders_positions_holdings_rest",
        "authorization_ready": False,
    },
    {
        "code": "upstox",
        "name": "Upstox API",
        "auth_mode": "oauth2_authorization_code",
        "market_data": "historical_rest_and_market_feed_v3_websocket",
        "execution": "orders_positions_holdings_rest",
        "authorization_ready": False,
    },
    {
        "code": "fyers",
        "name": "FYERS API v3",
        "auth_mode": "authorization_code_app_id_hash_exchange",
        "market_data": "historical_rest_and_data_socket",
        "execution": "orders_positions_holdings_rest_and_general_socket",
        "authorization_ready": False,
    },
]


def get_broker_catalog() -> list[dict]:
    return [dict(row) for row in BROKER_CATALOG]


def is_supported_broker(code: str) -> bool:
    normalized = code.strip().lower()
    return any(row["code"] == normalized for row in BROKER_CATALOG)
