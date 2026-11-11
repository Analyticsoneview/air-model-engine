import unittest
from decimal import Decimal

from app.brokers.base import BrokerCredentials, Instrument, OrderRequest
from app.brokers.dhan_adapter import DhanBrokerAdapter


class FakeDhanClient:
    def __init__(self):
        self.placed = None
        self.modified = None
        self.cancelled = None
        self.quote_payload = {"data": {"NSE_FNO": {"12345": {
            "last_price": 101.25, "ohlc": {"open": 99, "high": 103, "low": 98, "close": 100},
            "volume": 5000, "oi": 1200, "last_trade_time": "2026-11-12T09:20:00"
        }}}}

    def set_access_token(self, token):
        self.token = token

    async def profile(self):
        return {"dhanClientId": "1000000001"}

    async def market_feed(self, mode, instruments):
        assert mode == "quote"
        return self.quote_payload

    async def positions(self):
        return [{"securityId": "12345", "netQty": 25}]

    async def holdings(self):
        return [{"securityId": "54321", "quantity": 10}]

    async def order_book(self):
        return [{"orderId": "D-1", "orderStatus": "TRANSIT"}]

    async def place_order(self, **kwargs):
        self.placed = kwargs
        return {"orderId": "D-2", "orderStatus": "PENDING"}

    async def modify_order(self, order_id, changes):
        self.modified = (order_id, changes)
        return {"orderId": order_id, "orderStatus": "PENDING"}

    async def cancel_order(self, order_id):
        self.cancelled = order_id
        return {"orderId": order_id, "orderStatus": "CANCELLED"}


class DhanBrokerAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = FakeDhanClient()
        self.adapter = DhanBrokerAdapter(client=self.client)
        await self.adapter.authenticate(BrokerCredentials(
            account_id="1000000001", api_key="1000000001", access_token="test-token"
        ))

    async def test_authentication_and_account_isolation(self):
        self.assertEqual(self.adapter.account_id, "1000000001")
        with self.assertRaises(PermissionError):
            await self.adapter.get_positions("another-account")

    async def test_quotes_are_normalized(self):
        instrument = Instrument(
            broker="dhan", exchange="NSE", trading_symbol="NIFTY",
            token="12345", segment="NSE_FNO", lot_size=25, tick_size=Decimal("0.05")
        )
        quotes = await self.adapter.get_quotes([instrument])
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].ltp, Decimal("101.25"))
        self.assertEqual(quotes[0].volume, 5000)
        self.assertEqual(quotes[0].open_interest, 1200)

    async def test_missing_or_invalid_ltp_is_not_fabricated_as_zero(self):
        self.client.quote_payload = {"data": {"NSE_FNO": {"12345": {"last_price": None}}}}
        instrument = Instrument(
            broker="dhan", exchange="NSE", trading_symbol="NIFTY",
            token="12345", segment="NSE_FNO", lot_size=25, tick_size=Decimal("0.05")
        )
        self.assertEqual(await self.adapter.get_quotes([instrument]), [])

    async def test_positions_holdings_and_order_book(self):
        self.assertEqual((await self.adapter.get_positions("1000000001"))[0]["netQty"], 25)
        self.assertEqual((await self.adapter.get_holdings("1000000001"))[0]["quantity"], 10)
        orders = await self.adapter.get_order_book("1000000001")
        self.assertEqual(orders[0].broker_order_id, "D-1")
        self.assertEqual(orders[0].status, "TRANSIT")

    async def test_order_lifecycle_normalizes_provider_responses(self):
        order = OrderRequest(
            account_id="1000000001", exchange="NSE_FNO", symbol="NIFTY",
            token="12345", side="BUY", order_type="LIMIT", product="INTRADAY",
            quantity=25, price=Decimal("101.25"), trigger_price=None,
            validity="DAY", tag="AIR", idempotency_key="air-test-123"
        )
        placed = await self.adapter.place_order(order)
        self.assertEqual(placed.broker_order_id, "D-2")
        self.assertEqual(self.client.placed["correlation_id"], "air-test-123")
        modified = await self.adapter.modify_order(
            "1000000001", "D-2", {"price": 102, "validity": "DAY"}
        )
        self.assertEqual(modified.broker_order_id, "D-2")
        self.assertEqual(self.client.modified[1]["price"], 102)
        cancelled = await self.adapter.cancel_order("1000000001", "D-2")
        self.assertEqual(cancelled.status, "CANCELLED")
        self.assertEqual(self.client.cancelled, "D-2")

    async def test_long_idempotency_key_is_rejected_without_truncation(self):
        order = OrderRequest(
            account_id="1000000001", exchange="NSE_FNO", symbol="NIFTY",
            token="12345", side="BUY", order_type="LIMIT", product="INTRADAY",
            quantity=25, price=Decimal("101.25"), trigger_price=None,
            validity="DAY", tag="AIR", idempotency_key="this-key-is-longer-than-thirty-chars"
        )
        with self.assertRaisesRegex(ValueError, "1 to 30"):
            await self.adapter.place_order(order)
        self.assertIsNone(self.client.placed)

    async def test_account_mismatch_rejected_before_authentication(self):
        adapter = DhanBrokerAdapter(client=self.client)
        with self.assertRaises(ValueError):
            await adapter.authenticate(BrokerCredentials(
                account_id="wrong", api_key="1000000001", access_token="token"
            ))


if __name__ == "__main__":
    unittest.main()
