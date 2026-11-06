import hashlib
import unittest
from datetime import datetime

import httpx

from app.brokers.zerodha import (
    KiteAPIError, KiteConnectClient, kite_login_url, kite_session_checksum,
)


class KiteConnectTests(unittest.IsolatedAsyncioTestCase):
    def test_login_url_and_checksum(self):
        self.assertIn("api_key=test-key", kite_login_url("test-key"))
        expected = hashlib.sha256(b"keyrequestsecret").hexdigest()
        self.assertEqual(kite_session_checksum("key", "request", "secret"), expected)

    async def test_token_exchange_uses_checksum_and_sets_access_token(self):
        seen = {}
        def handler(request):
            seen["body"] = request.read().decode()
            return httpx.Response(200, json={"status": "success", "data": {"access_token": "access"}})
        client = KiteConnectClient("key", transport=httpx.MockTransport(handler))
        data = await client.exchange_request_token("request", "secret")
        self.assertEqual(data["access_token"], "access")
        self.assertIn(kite_session_checksum("key", "request", "secret"), seen["body"])
        self.assertEqual(client._http.headers["Authorization"], "token key:access")
        await client.close()

    async def test_profile_and_quotes_authenticated(self):
        seen = []
        def handler(request):
            seen.append((request.url.path, request.headers.get("Authorization")))
            return httpx.Response(200, json={"status": "success", "data": {"user_id": "AB123"}})
        client = KiteConnectClient("key", "access", transport=httpx.MockTransport(handler))
        await client.profile()
        await client.quotes(["NSE:INFY"], mode="ltp")
        self.assertEqual(seen[0][1], "token key:access")
        self.assertEqual(seen[1][0], "/quote/ltp")
        await client.close()

    async def test_historical_range_and_order_validation(self):
        client = KiteConnectClient("key", "access",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status":"success","data":{"candles":[]}})))
        with self.assertRaises(ValueError):
            await client.historical(1, "5minute", datetime(2026, 1, 2), datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            await client.place_order({"quantity": 0})
        await client.close()

    async def test_api_errors_are_not_silently_returned(self):
        client = KiteConnectClient("key", "access",
            transport=httpx.MockTransport(lambda request: httpx.Response(403, json={"message":"Forbidden"})))
        with self.assertRaises(KiteAPIError):
            await client.profile()
        await client.close()


if __name__ == "__main__":
    unittest.main()
