import os
import unittest
from unittest.mock import AsyncMock, patch

from app import air_telegram_scheduler as scheduler


class AirTelegramSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_polls_all_three_strategies_for_each_operator(self):
        with patch.dict(os.environ, {
            "AIR_TELEGRAM_SCHEDULER_ENABLED": "true",
            "AIR_OPERATOR_CUSTOMER_IDS": "operator-1,operator-2",
        }, clear=False), \
             patch.object(scheduler, "get_original366_engine", new=AsyncMock(
                 return_value={"telegram_notifications": {"sent": 1, "configured": True}})) as recovered, \
             patch.object(scheduler, "get_expiry78_engine", new=AsyncMock(
                 return_value={"telegram_notifications": {"sent": 2, "configured": True}})) as expiry78, \
             patch.object(scheduler, "get_expiry_scan", new=AsyncMock(
                 return_value={"telegram_notifications": {"sent": 0, "configured": True}})) as expiryscan:
            result = await scheduler.poll_air_strategy_alerts()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["results"]), 6)
        self.assertEqual(recovered.await_count, 2)
        self.assertEqual(expiry78.await_count, 2)
        self.assertEqual(expiryscan.await_count, 2)

    async def test_scheduler_disabled_by_default(self):
        with patch.dict(os.environ, {"AIR_TELEGRAM_SCHEDULER_ENABLED": "false"}, clear=False):
            result = await scheduler.poll_air_strategy_alerts()
        self.assertEqual(result, {"status": "disabled"})


if __name__ == "__main__":
    unittest.main()
