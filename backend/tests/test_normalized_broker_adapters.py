import unittest
from decimal import Decimal

from app.brokers.base import BrokerCredentials, Instrument, OrderRequest
from app.brokers.dhan_adapter import DhanBrokerAdapter
from app.brokers.normalized_adapters import (
    ZerodhaBrokerAdapter, UpstoxBrokerAdapter, FyersBrokerAdapter, AngelBrokerAdapter,
)
from app.brokers.registry import build_broker_adapter


class FakeClient:
    def __init__(self, broker):
        self.broker=broker
        self.token=None
        self.placed=None
    def set_access_token(self, token): self.token=token
    async def profile(self):
        return {"user_id":"KITE1"} if self.broker=="zerodha" else (
            {"user_id":"UP1"} if self.broker=="upstox" else (
            {"fy_id":"FY1"} if self.broker=="fyers" else {"clientcode":"ANG1"}))
    async def quotes(self, keys, *args):
        if self.broker=="zerodha":
            return {keys[0]:{"last_price":101.5,"ohlc":{"open":99,"high":103,"low":98,"close":100},"volume":500,"oi":40}}
        if self.broker=="upstox":
            return {keys[0]:{"last_price":101.5,"ohlc":{"open":99,"high":103,"low":98,"close":100},"volume":500,"oi":40}}
        if self.broker=="fyers":
            return {"d":[{"n":keys[0],"v":{"lp":101.5,"open_price":99,"high_price":103,"low_price":98,"prev_close_price":100,"volume":500,"oi":40}}]}
        return {"fetched":[{"symbolToken":"123","ltp":101.5,"open":99,"high":103,"low":98,"close":100,"tradeVolume":500,"opnInterest":40}]}
    async def positions(self): return [{"netQty":1}]
    async def holdings(self): return [{"quantity":2}]
    async def orders(self): return [{"order_id":"O1","status":"OPEN"}]
    async def order_book(self): return [{"order_id":"O1","status":"OPEN"}]
    async def market_data(self, mode, grouped): return {"fetched":[{"symbolToken":"123","ltp":101.5,"open":99,"high":103,"low":98,"close":100,"tradeVolume":500,"opnInterest":40}]}
    async def place_order(self, *args, **kwargs):
        self.placed=(args,kwargs)
        return {"order_id":"O2","orderid":"O2","id":"O2","status":"PENDING"}
    async def modify_order(self, *args, **kwargs): return {"order_id":"O2","orderid":"O2","id":"O2","status":"PENDING"}
    async def cancel_order(self, *args, **kwargs): return {"order_id":"O2","orderid":"O2","id":"O2","status":"CANCELLED"}


class NormalizedAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def _check(self, code, account, cls, metadata=None):
        client=FakeClient(code)
        adapter=cls(client=client) if code!="angel" else cls(client=client)
        creds=BrokerCredentials(account_id=account,api_key="app-key",access_token="access",metadata=metadata)
        await adapter.authenticate(creds)
        self.assertEqual(adapter.account_id,account)
        instrument=Instrument(code,"NSE","ABC","123","NSE",1,Decimal("0.05"))
        quote=await adapter.get_quotes([instrument])
        self.assertEqual(len(quote),1)
        self.assertEqual(quote[0].ltp,Decimal("101.5"))
        self.assertEqual(await adapter.get_positions(account),[{"netQty":1}])
        self.assertEqual(await adapter.get_holdings(account),[{"quantity":2}])
        orders=await adapter.get_order_book(account)
        self.assertEqual(orders[0].broker_order_id,"O1")
        req=OrderRequest(account,"NSE","ABC","123","BUY","LIMIT","INTRADAY",1,Decimal("101"),None,"DAY","AIR","id-123")
        placed=await adapter.place_order(req)
        self.assertEqual(placed.broker_order_id,"O2")
        self.assertEqual((await adapter.modify_order(account,"O2",{"price":102})).broker_order_id,"O2")
        self.assertEqual((await adapter.cancel_order(account,"O2")).broker_order_id,"O2")
        with self.assertRaises(PermissionError):
            await adapter.get_positions("OTHER")

    async def test_factory_constructs_only_supported_adapters_without_registration(self):
        for code in ("zerodha", "upstox", "fyers", "angel", "dhan"):
            adapter = build_broker_adapter(code, client=FakeClient(code))
            self.assertEqual(adapter.broker_code, code)
            self.assertIsNone(adapter.account_id)
        with self.assertRaises(ValueError):
            build_broker_adapter("unsupported")

    async def test_zerodha(self): await self._check("zerodha","KITE1",ZerodhaBrokerAdapter)
    async def test_upstox(self): await self._check("upstox","UP1",UpstoxBrokerAdapter)
    async def test_fyers(self): await self._check("fyers","FY1",FyersBrokerAdapter)
    async def test_authentication_rejects_profile_mismatch_for_each_normalized_broker(self):
        for code, cls, wrong in (
            ("zerodha",ZerodhaBrokerAdapter,"WRONG"),
            ("upstox",UpstoxBrokerAdapter,"WRONG"),
            ("fyers",FyersBrokerAdapter,"WRONG"),
            ("angel",AngelBrokerAdapter,"WRONG"),
        ):
            adapter=cls(client=FakeClient(code))
            metadata={"client_local_ip":"127.0.0.1","client_public_ip":"127.0.0.1","mac_address":"00:00:00:00:00:00"} if code=="angel" else None
            with self.assertRaises(PermissionError):
                await adapter.authenticate(BrokerCredentials(wrong,"app-key","token",metadata))

    async def test_invalid_order_is_rejected_before_provider_call(self):
        for code, account, cls, metadata in (
            ("zerodha","KITE1",ZerodhaBrokerAdapter,None),
            ("upstox","UP1",UpstoxBrokerAdapter,None),
            ("fyers","FY1",FyersBrokerAdapter,None),
            ("angel","ANG1",AngelBrokerAdapter,{"client_local_ip":"127.0.0.1","client_public_ip":"127.0.0.1","mac_address":"00:00:00:00:00:00"}),
        ):
            client=FakeClient(code); adapter=cls(client=client)
            await adapter.authenticate(BrokerCredentials(account,"app-key","token",metadata))
            bad=OrderRequest(account,"NSE","ABC","123","BUY","LIMIT","INTRADAY",0,Decimal("101"),None,"DAY","AIR","id-123")
            with self.assertRaises(ValueError): await adapter.place_order(bad)
            self.assertIsNone(client.placed)

    async def test_angel_injected_client_receives_rotated_jwt(self):
        client=FakeClient("angel"); adapter=AngelBrokerAdapter(client=client)
        metadata={"client_local_ip":"127.0.0.1","client_public_ip":"127.0.0.1","mac_address":"00:00:00:00:00:00"}
        await adapter.authenticate(BrokerCredentials("ANG1","app-key","rotated-jwt",metadata))
        self.assertEqual(client.token,"rotated-jwt")

    async def test_dhan(self):
        class DhanFake(FakeClient):
            def __init__(self): super().__init__("dhan"); self.client_id="DH1"; self.placed=None
            def set_access_token(self, token): self.token=token
            async def profile(self): return {"dhanClientId":"DH1"}
            async def market_feed(self, mode, grouped):
                return {"data":{"NSE_FNO":{"123":{"last_price":101.5,"ohlc":{"open":99,"high":103,"low":98,"close":100},"volume":500,"oi":40}}}}
            async def positions(self): return [{"netQty":1}]
            async def holdings(self): return [{"quantity":2}]
            async def order_book(self): return [{"orderId":"O1","orderStatus":"OPEN"}]
            async def place_order(self, **kwargs): self.placed=kwargs; return {"orderId":"O2","orderStatus":"PENDING"}
            async def modify_order(self, order_id, changes): return {"orderId":order_id,"orderStatus":"PENDING"}
            async def cancel_order(self, order_id): return {"orderId":order_id,"orderStatus":"CANCELLED"}
        client=DhanFake(); adapter=DhanBrokerAdapter(client=client)
        await adapter.authenticate(BrokerCredentials("DH1","DH1","token"))
        instrument=Instrument("dhan","NSE_FNO","ABC","123","NSE_FNO",1,Decimal("0.05"))
        quotes=await adapter.get_quotes([instrument])
        self.assertEqual(quotes[0].ltp,Decimal("101.5"))
        self.assertEqual(await adapter.get_positions("DH1"),[{"netQty":1}])
        self.assertEqual(await adapter.get_holdings("DH1"),[{"quantity":2}])
        self.assertEqual((await adapter.get_order_book("DH1"))[0].broker_order_id,"O1")
        req=OrderRequest("DH1","NSE_FNO","ABC","123","BUY","LIMIT","INTRADAY",1,Decimal("101"),None,"DAY","AIR","dh-id-123")
        self.assertEqual((await adapter.place_order(req)).broker_order_id,"O2")
        self.assertEqual((await adapter.modify_order("DH1","O2",{"price":102})).broker_order_id,"O2")
        self.assertEqual((await adapter.cancel_order("DH1","O2")).status,"CANCELLED")
        with self.assertRaises(PermissionError): await adapter.get_positions("OTHER")
        with self.assertRaises(ValueError): await adapter.authenticate(BrokerCredentials("WRONG","DH1","token"))

    async def test_angel(self):
        await self._check("angel","ANG1",AngelBrokerAdapter, {
            "client_local_ip":"127.0.0.1","client_public_ip":"127.0.0.1","mac_address":"00:00:00:00:00:00"
        })


if __name__=="__main__": unittest.main()
