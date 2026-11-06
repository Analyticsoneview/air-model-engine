import hashlib
import unittest

import httpx

from app.brokers.fyers import FyersAPIError, FyersClient, fyers_app_id_hash, fyers_login_url


class FyersClientTests(unittest.IsolatedAsyncioTestCase):
    def test_login_url_and_hash(self):
        self.assertIn("response_type=code", fyers_login_url("app-100", "https://air.example/cb", "state123"))
        self.assertEqual(fyers_app_id_hash("app", "secret"),
                         hashlib.sha256(b"app:secret").hexdigest())
        with self.assertRaises(ValueError):
            fyers_login_url("app", "https://air.example/cb", "")

    async def test_auth_code_exchange_sets_authorization_header(self):
        seen = {}
        def handler(request):
            seen["payload"] = request.read().decode()
            return httpx.Response(200, json={"s":"ok","code":200,"access_token":"token"})
        client = FyersClient("app-100", transport=httpx.MockTransport(handler))
        await client.exchange_auth_code("auth-code", "secret")
        self.assertIn(fyers_app_id_hash("app-100","secret"), seen["payload"])
        self.assertEqual(client._http.headers["Authorization"], "app-100:token")
        await client.close()

    async def test_quotes_and_history(self):
        seen = []
        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json={"s":"ok","data":[]})
        client = FyersClient("app-100","token",transport=httpx.MockTransport(handler))
        await client.quotes(["NSE:SBIN-EQ"])
        await client.history("NSE:SBIN-EQ","5","1","2026-11-01","2026-11-06")
        self.assertEqual(seen, ["/data/quotes","/data/history"])
        with self.assertRaises(ValueError):
            await client.quotes([])
        await client.close()

    async def test_order_validation_and_api_errors(self):
        client = FyersClient("app-100","token",transport=httpx.MockTransport(
            lambda request: httpx.Response(401,json={"s":"error","message":"unauthorized"})
        ))
        with self.assertRaises(ValueError):
            await client.place_order({"qty":0})
        with self.assertRaises(FyersAPIError):
            await client.profile()
        await client.close()


if __name__ == "__main__":
    unittest.main()
