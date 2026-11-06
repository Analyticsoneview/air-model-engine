import unittest

import httpx

from app.brokers.upstox import UpstoxAPIError, UpstoxClient, upstox_login_url


class UpstoxClientTests(unittest.IsolatedAsyncioTestCase):
    def test_login_url_requires_state_and_encodes_redirect(self):
        url = upstox_login_url("client", "https://air.example/callback", "nonce-123")
        self.assertIn("response_type=code", url)
        self.assertIn("state=nonce-123", url)
        with self.assertRaises(ValueError):
            upstox_login_url("client", "https://air.example/callback", "")

    async def test_oauth_code_exchange_sets_bearer_token(self):
        seen = {}
        def handler(request):
            seen["body"] = request.read().decode()
            return httpx.Response(200, json={"status": "success", "data": {"access_token": "token-123", "user_id": "AB123"}})
        client = UpstoxClient(transport=httpx.MockTransport(handler))
        data = await client.exchange_code("one-time-code", "client", "secret", "https://air.example/callback")
        self.assertEqual(data["user_id"], "AB123")
        self.assertIn("grant_type=authorization_code", seen["body"])
        self.assertEqual(client._http.headers["Authorization"], "Bearer token-123")
        await client.close()

    async def test_historical_request_and_validation(self):
        seen = {}
        def handler(request):
            seen["path"] = request.url.path
            return httpx.Response(200, json={"status": "success", "data": {"candles": []}})
        client = UpstoxClient("token", transport=httpx.MockTransport(handler))
        await client.historical("NSE_EQ|INE002A01018", "minutes", 5, "2026-11-06", "2026-11-01")
        self.assertIn("/v3/historical-candle/", seen["path"])
        with self.assertRaises(ValueError):
            await client.intraday("key", "days", 1)
        await client.close()

    async def test_api_error_raises(self):
        client = UpstoxClient("token", transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"status":"error","errors":"Unauthorized"})
        ))
        with self.assertRaises(UpstoxAPIError):
            await client.profile()
        await client.close()


if __name__ == "__main__":
    unittest.main()
