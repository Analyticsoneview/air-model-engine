import unittest

import httpx

from app.brokers.dhan import DhanAPIError, DhanHQClient


class DhanHQClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_verifies_client_id_and_auth_header(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("access-token")
            return httpx.Response(200, json={"dhanClientId": "10001", "dataPlan": "Active"})

        client = DhanHQClient("10001", "test-token", transport=httpx.MockTransport(handler))
        profile = await client.profile()
        self.assertEqual(profile["dataPlan"], "Active")
        self.assertEqual(seen["auth"], "test-token")
        await client.close()

    async def test_profile_rejects_wrong_account(self):
        def handler(request):
            return httpx.Response(200, json={"dhanClientId": "other"})
        client = DhanHQClient("10001", "test-token", transport=httpx.MockTransport(handler))
        with self.assertRaises(DhanAPIError):
            await client.profile()
        await client.close()

    async def test_historical_request_and_quote_validation(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["payload"] = request.read().decode()
            return httpx.Response(200, json={"open": [], "close": [], "timestamp": []})

        client = DhanHQClient("10001", "test-token", transport=httpx.MockTransport(handler))
        await client.historical_intraday(
            security_id="123", exchange_segment="NSE_EQ", instrument="EQUITY",
            interval=5, from_date="2026-11-01 09:15:00",
            to_date="2026-11-01 15:30:00",
        )
        self.assertEqual(seen["path"], "/v2/charts/intraday")
        self.assertIn('"interval":"5"', seen["payload"])
        with self.assertRaises(ValueError):
            await client.historical_intraday(
                security_id="123", exchange_segment="NSE_EQ", instrument="EQUITY",
                interval=3, from_date="2026-11-01 09:15:00",
                to_date="2026-11-01 15:30:00",
            )
        await client.close()

    async def test_order_input_validation_happens_before_network(self):
        client = DhanHQClient(
            "10001", "test-token",
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )
        with self.assertRaises(ValueError):
            await client.place_order(
                security_id="123", exchange_segment="NSE_EQ",
                transaction_type="BUY", product_type="INTRADAY",
                order_type="LIMIT", quantity=1, correlation_id="AIR-1",
            )
        await client.close()


    async def test_option_chain_and_expired_options_payloads(self):
        seen = []

        def handler(request):
            seen.append((request.url.path, request.read().decode()))
            if request.url.path.endswith("/optionchain/expirylist"):
                return httpx.Response(200, json={"data": ["2026-11-26"]})
            if request.url.path.endswith("/optionchain"):
                return httpx.Response(200, json={"status": "success", "data": {"oc": {}}})
            return httpx.Response(200, json={"data": {"ce": {"close": [12.5]}}})

        client = DhanHQClient("10001", "test-token", transport=httpx.MockTransport(handler))
        expiries = await client.option_expiry_list(underlying_scrip=13, underlying_segment="IDX_I")
        chain = await client.option_chain(
            underlying_scrip=13, underlying_segment="IDX_I", expiry="2026-11-26"
        )
        expired = await client.expired_options(
            underlying_scrip=13, interval=5, instrument="OPTIDX",
            expiry_flag="WEEK", expiry_code=1, strike="ATM",
            option_type="CALL", from_date="2026-10-01", to_date="2026-10-15",
        )
        self.assertEqual(expiries, ["2026-11-26"])
        self.assertIn("oc", chain)
        self.assertIn("ce", expired["data"])
        self.assertEqual([item[0] for item in seen], [
            "/v2/optionchain/expirylist", "/v2/optionchain", "/v2/charts/rollingoption"
        ])
        self.assertIn('"drvOptionType":"CALL"', seen[2][1])
        with self.assertRaises(ValueError):
            await client.expired_options(
                underlying_scrip=13, interval=3, instrument="OPTIDX",
                expiry_flag="WEEK", expiry_code=1, strike="ATM",
                option_type="CALL", from_date="2026-10-01", to_date="2026-10-15",
            )
        await client.close()



if __name__ == "__main__":
    unittest.main()
