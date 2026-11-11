import unittest

from app.brokers.base import BrokerCredentials
from app.brokers.customer_accounts import CustomerTradingAccount
from app.brokers.session_runtime import BrokerSessionRuntime


class FakeDirectory:
    def __init__(self):
        self.accounts=[CustomerTradingAccount("C1","zerodha","K1",False),
                       CustomerTradingAccount("C1","dhan","D1",False),
                       CustomerTradingAccount("C2","zerodha","K2",False)]
    def list_for_customer(self, customer):
        return [a for a in self.accounts if a.customer_id==customer]


class FakeVault:
    def get(self, customer, broker, account):
        if customer=="C1" and broker=="zerodha" and account=="K1":
            return {"api_key":"key","access_token":"token"}
        if customer=="C1" and broker=="dhan" and account=="D1":
            return {"client_id":"D1","access_token":"token"}
        if customer=="C2" and broker=="zerodha" and account=="K2":
            return {"api_key":"key2","access_token":"token2"}
        raise KeyError("not found")


class FakeAdapter:
    def __init__(self, code):
        self.broker_code=code
        self.client=self
        self.account_id=None
        self.closed=False
    async def authenticate(self, credentials: BrokerCredentials):
        self.account_id=credentials.account_id
        return {"authenticated":True,"account_id":credentials.account_id}
    async def close(self): self.closed=True


class AdapterFactory:
    def __init__(self): self.created=[]
    def __call__(self, code):
        adapter=FakeAdapter(code); self.created.append(adapter); return adapter


class BrokerSessionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.factory=AdapterFactory()
        self.runtime=BrokerSessionRuntime(FakeDirectory(),FakeVault(),adapter_factory=self.factory)

    async def asyncTearDown(self):
        await self.runtime.close()

    async def test_activate_verifies_and_registers_only_after_auth(self):
        result=await self.runtime.activate("C1","zerodha","K1")
        self.assertTrue(result["active"])
        self.assertEqual(self.runtime.registry.active_accounts(),[{"broker":"zerodha","account_id":"K1"}])
        self.assertEqual(self.runtime.status_for_customer("C1")[0]["status"],"ACTIVE")

    async def test_activation_is_idempotent_and_does_not_duplicate_adapter(self):
        await self.runtime.activate("C1","zerodha","K1")
        result=await self.runtime.activate("C1","zerodha","K1")
        self.assertTrue(result["already_active"])
        self.assertEqual(len(self.factory.created),1)

    async def test_customer_cannot_activate_unowned_account(self):
        with self.assertRaises(PermissionError):
            await self.runtime.activate("C1","zerodha","K2")
        self.assertEqual(self.factory.created,[])

    async def test_deactivation_closes_client_and_removes_registry(self):
        await self.runtime.activate("C1","zerodha","K1")
        adapter=self.factory.created[0]
        result=await self.runtime.deactivate("C1","zerodha","K1")
        self.assertFalse(result["active"])
        self.assertTrue(adapter.closed)
        self.assertEqual(self.runtime.registry.accounts(),[])
        self.assertEqual(self.runtime.status_for_customer("C1"),[])

    async def test_other_customer_cannot_deactivate_session(self):
        await self.runtime.activate("C1","zerodha","K1")
        with self.assertRaises(PermissionError):
            await self.runtime.deactivate("C2","zerodha","K1")

    async def test_deactivate_customer_closes_all_sessions(self):
        await self.runtime.activate("C1","zerodha","K1")
        await self.runtime.activate("C1","dhan","D1")
        count=await self.runtime.deactivate_customer("C1")
        self.assertEqual(count,2)
        self.assertTrue(all(a.closed for a in self.factory.created))
        self.assertEqual(self.runtime.registry.accounts(),[])


if __name__=="__main__": unittest.main()
