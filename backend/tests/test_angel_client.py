import unittest

import httpx

from app.brokers.angel import AngelAPIError, AngelSmartAPI


def client(transport):
    return AngelSmartAPI("api-key", "A123", client_local_ip="10.0.0.2",
                         client_public_ip="203.0.113.5", mac_address="00:11:22:33:44:55",
                         transport=transport)


class AngelSmartAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_login_stores_jwt_and_returns_feed_tokens(self):
        seen = {}
        def handler(request):
            seen["payload"] = request.read().decode()
            return httpx.Response(200, json={"status":True,"data":{
                "jwtToken":"jwt","refreshToken":"refresh","feedToken":"feed"}})
        api = client(httpx.MockTransport(handler))
        data = await api.login("1234","123456","test")
        self.assertEqual(data["feedToken"],"feed")
        self.assertEqual(api._http.headers["Authorization"],"Bearer jwt")
        self.assertIn('"totp":"123456"',seen["payload"])
        await api.close()

    async def test_profile_requires_session_and_uses_bearer(self):
        seen = {}
        def handler(request):
            seen["authorization"] = request.headers.get("Authorization")
            return httpx.Response(200,json={"status":True,"data":{"clientcode":"A123"}})
        api = client(httpx.MockTransport(handler))
        with self.assertRaises(ValueError):
            await api.profile()
        api.set_access_token("jwt")
        profile = await api.profile()
        self.assertEqual(profile["clientcode"],"A123")
        self.assertEqual(seen["authorization"],"Bearer jwt")
        await api.close()

    async def test_historical_payload_and_order_validation(self):
        seen = {}
        def handler(request):
            seen["payload"] = request.read().decode()
            return httpx.Response(200,json={"status":True,"data":[]})
        api = client(httpx.MockTransport(handler))
        api.set_access_token("jwt")
        await api.historical("NSE","3045","FIVE_MINUTE","2026-11-06 09:15","2026-11-06 15:30")
        self.assertIn('"symboltoken":"3045"',seen["payload"])
        with self.assertRaises(ValueError):
            await api.historical("BAD","1","FIVE_MINUTE","a","b")
        with self.assertRaises(ValueError):
            await api.place_order({"quantity":0})
        await api.close()

    async def test_smartapi_error_raises(self):
        api = client(httpx.MockTransport(lambda request: httpx.Response(
            200,json={"status":False,"message":"Invalid TOTP","errorcode":"AB1010"}
        )))
        with self.assertRaises(AngelAPIError):
            await api.login("1234","000000")
        await api.close()


if __name__ == "__main__":
    unittest.main()
