import os
import unittest
from unittest.mock import AsyncMock, patch

from app import model_engine_api


class TelegramCustomerScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_operator_customer_cannot_trigger_global_telegram_alerts(self):
        with patch.dict(os.environ, {"AIR_OPERATOR_CUSTOMER_IDS": "operator-1"}, clear=False), \
             patch.object(model_engine_api, "notify_candidates", new=AsyncMock()) as notify:
            result = await model_engine_api._notify_operator_candidates(
                "EXPIRY78", [{"symbol": "PRIVATE-CUSTOMER-DATA"}], "customer-2"
            )

        self.assertEqual(result, {"configured": False, "attempted": 0, "sent": 0})
        notify.assert_not_awaited()

    async def test_operator_customer_can_trigger_telegram_alerts(self):
        expected = {"configured": True, "attempted": 1, "sent": 1}
        with patch.dict(os.environ, {"AIR_OPERATOR_CUSTOMER_IDS": "operator-1"}, clear=False), \
             patch.object(model_engine_api, "notify_candidates", new=AsyncMock(return_value=expected)) as notify:
            result = await model_engine_api._notify_operator_candidates(
                "EXPIRY78", [{"symbol": "AIR-TEST"}], "operator-1"
            )

        self.assertEqual(result, expected)
        notify.assert_awaited_once_with("EXPIRY78", [{"symbol": "AIR-TEST"}])


if __name__ == "__main__":
    unittest.main()
