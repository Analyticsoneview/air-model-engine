import unittest

import httpx

from app.brokers.dhan_instruments import DhanInstrumentMaster


CSV = """SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_CUSTOM_SYMBOL,SM_SYMBOL_NAME,SEM_LOT_UNITS,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE
NSE,E,1333,EQUITY,HDFCBANK,HDFCBANK,HDFCBANK,1,,0,,0.05
NSE,D,90001,OPTIDX,NIFTY26NOV25000CE,NIFTY 26 Nov 25000 CE,NIFTY,65,2026-11-26,25000,CE,0.05
MCX,M,90001,OPTFUT,SILVERM26NOVPE,SILVERM 26 Nov PE,SILVERM,1,2026-11-26,100000,PE,1
"""


class DhanInstrumentMasterTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_returns_segment_safe_security_ids(self):
        client = DhanInstrumentMaster(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=CSV)
        ))
        options = await client.search("NIFTY")
        self.assertEqual(options[0]["token"], "90001")
        self.assertEqual(options[0]["segment"], "NSE_FNO")
        silver = await client.search("SILVERM")
        self.assertEqual(silver[0]["segment"], "MCX_COMM")  # no NSE M segment exists
        await client.close()

    async def test_segment_filter_and_cache(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(200, text=CSV)
        client = DhanInstrumentMaster(transport=httpx.MockTransport(handler))
        results = await client.search("HDFCBANK", exchange_segment="NSE_EQ")
        self.assertEqual(results[0]["token"], "1333")
        await client.search("HDFCBANK", exchange_segment="NSE_EQ")
        self.assertEqual(len(calls), 1)
        await client.close()

    async def test_invalid_csv_schema_is_rejected(self):
        client = DhanInstrumentMaster(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="wrong,columns\na,b")
        ))
        with self.assertRaises(ValueError):
            await client.refresh()
        await client.close()


if __name__ == "__main__":
    unittest.main()
