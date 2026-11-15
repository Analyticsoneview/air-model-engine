import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import telegram_notifications as telegram
from app import telegram_destinations as destinations


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True}


class FakeClient:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json):
        self.sent.append((url, json))
        return FakeResponse()


class TelegramNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_candidates_sends_once_per_candidate_and_chat(self):
        FakeClient.sent = []
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(telegram.httpx, "AsyncClient", FakeClient), \
             patch.dict(os.environ, {
                 "AIR_TELEGRAM_BOT_TOKEN": "test-token",
                 "AIR_TELEGRAM_CHAT_IDS": "111,-100222",
                 "AIR_TELEGRAM_DEDUPE_DB_PATH": str(Path(folder) / "telegram.sqlite3"),
             }, clear=False):
            row = {
                "signal_id": "EXP78-001", "symbol": "TEST", "option_type": "CE",
                "strike": 100, "expiry": "2026-11-27", "classification": "NEW",
                "entry_price": 12.5, "stop_loss": 10.0,
            }
            first = await telegram.notify_candidates("EXPIRY78", [row])
            second = await telegram.notify_candidates("EXPIRY78", [row])

        self.assertEqual(first["sent"], 2)
        self.assertEqual(second["sent"], 0)
        self.assertEqual(len(FakeClient.sent), 2)
        self.assertTrue(all("AIR STRATEGY:</b> EXPIRY78" in item[1]["text"] for item in FakeClient.sent))
        self.assertTrue(all("PRICE LEVELS" in item[1]["text"] for item in FakeClient.sent))
        self.assertTrue(all(item[1]["parse_mode"] == "HTML" for item in FakeClient.sent))

    async def test_expiryscan_message_is_not_misrepresented_as_qoc_trade(self):
        FakeClient.sent = []
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(telegram.httpx, "AsyncClient", FakeClient), \
             patch.dict(os.environ, {
                 "AIR_TELEGRAM_BOT_TOKEN": "test-token",
                 "AIR_TELEGRAM_CHAT_IDS": "111",
                 "AIR_TELEGRAM_DEDUPE_DB_PATH": str(Path(folder) / "telegram.sqlite3"),
             }, clear=False):
            await telegram.notify_candidates("EXPIRYSCAN", [{
                "symbol": "TEST", "option_type": "PE", "strike": 200,
                "expiry": "2026-11-27", "scan_status": "LIQUIDITY_SCREEN_PASSED",
            }])

        self.assertEqual(len(FakeClient.sent), 1)
        self.assertIn("Liquidity-screen pass only", FakeClient.sent[0][1]["text"])
        self.assertIn("SCREEN PASSED", FakeClient.sent[0][1]["text"])


    async def test_stale_pending_delivery_is_retried_after_interrupted_send(self):
        FakeClient.sent = []
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(telegram.httpx, "AsyncClient", FakeClient), \
             patch.dict(os.environ, {
                 "AIR_TELEGRAM_BOT_TOKEN": "test-token",
                 "AIR_TELEGRAM_CHAT_IDS": "111",
                 "AIR_TELEGRAM_DEDUPE_DB_PATH": str(Path(folder) / "telegram.sqlite3"),
             }, clear=False):
            row = {
                "signal_id": "EXP78-STALE", "symbol": "TEST", "option_type": "CE",
                "strike": 100, "expiry": "2026-11-27", "classification": "NEW",
            }
            event_key = telegram._candidate_key("EXPIRY78", row)
            db = telegram._connect()
            db.execute(
                "INSERT INTO telegram_deliveries(event_key, chat_id, status, created_at) "
                "VALUES (?, ?, 'PENDING', datetime('now', '-1 hour'))",
                (event_key, "111"),
            )
            db.commit()
            db.close()

            result = await telegram.notify_candidates("EXPIRY78", [row])

        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(FakeClient.sent), 1)

    def test_recovered_is_explicitly_watch_only_and_escaped(self):
        message = telegram._format_message("RECOVERED", {
            "symbol": "TEST<STOCK>", "option_type": "CE", "strike": 100,
            "expiry": "2026-12-31", "entry_price": 12.5, "stop_loss": 10,
            "target_1": 20, "reason": "Post-stop recovery",
        })
        self.assertIn("WATCH ONLY", message)
        self.assertIn("NOT a live position", message)
        self.assertIn("TEST&lt;STOCK&gt;", message)
        self.assertIn("🎯 Target 1", message)

    def test_settings_supports_docker_secret_file(self):
        with tempfile.TemporaryDirectory() as folder:
            token_file = Path(folder) / "telegram-token"
            token_file.write_text("secret-token", encoding="utf-8")
            with patch.dict(os.environ, {
                "AIR_TELEGRAM_BOT_TOKEN": "",
                "AIR_TELEGRAM_BOT_TOKEN_FILE": str(token_file),
                "AIR_TELEGRAM_CHAT_IDS": "111,-100222",
            }, clear=False):
                token, chat_ids = telegram._settings()

        self.assertEqual(token, "secret-token")
        self.assertEqual(chat_ids, ["111", "-100222"])


    async def test_managed_destinations_override_legacy_ids_per_strategy(self):
        FakeClient.sent = []
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(telegram.httpx, "AsyncClient", FakeClient), patch.dict(os.environ, {
                "AIR_TELEGRAM_BOT_TOKEN": "test-token",
                "AIR_TELEGRAM_CHAT_IDS": "legacy-chat",
                "AIR_TELEGRAM_DEDUPE_DB_PATH": str(Path(folder) / "dedupe.sqlite3"),
                "AIR_TELEGRAM_CONFIG_DB_PATH": str(Path(folder) / "config.sqlite3"),
            }, clear=False):
                destinations.upsert_destination(
                    "EXPIRY78 group", "-1009876543210", "GROUP", ["EXPIRY78"], True,
                )
                destinations.upsert_destination(
                    "RECOVERED private", "123456789", "PRIVATE", ["RECOVERED"], True,
                )
                result = await telegram.notify_candidates("EXPIRY78", [{
                    "signal_id": "EXP78-DYNAMIC", "symbol": "TEST",
                    "option_type": "CE", "strike": 100, "expiry": "2026-11-27",
                }])

        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(FakeClient.sent), 1)
        self.assertEqual(FakeClient.sent[0][1]["chat_id"], "-1009876543210")


    def test_air_qoc_orb_and_portfolio_risk_messages_are_explicitly_research_only(self):
        qoc = telegram._format_message("AIR_QOC", {
            "symbol": "NIFTY", "option_type": "CE", "strike": 25000,
            "classification": "HIGH_CONVICTION", "score": 93,
        })
        orb = telegram._format_message("ORB", {
            "symbol": "NIFTY", "status": "BREAKOUT", "entry_price": 25010,
            "stop_loss": 24980, "range_high": 25000,
        })
        risk = telegram._format_message("PORTFOLIO_RISK", {
            "summary": {"concentration_top_position_pct": 45, "data_quality": "COMPLETE"},
        })
        self.assertIn("AIR QOC QUALIFIED CANDIDATE", qoc)
        self.assertIn("does not place orders", qoc)
        self.assertIn("AIR ORB STRATEGY SIGNAL", orb)
        self.assertIn("Opening range high", orb)
        self.assertIn("AIR PORTFOLIO RISK ALERT", risk)
        self.assertIn("45", risk)
        self.assertIn("no trades are placed", risk)


    def test_customer_scoped_notifications_do_not_fall_back_to_global_routes(self):
        from app import telegram_destinations
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "AIR_TELEGRAM_CONFIG_DB_PATH": str(Path(folder) / "telegram-config.sqlite3"),
        }, clear=False):
            global_route = telegram_destinations.upsert_destination(
                "Global AIR QOC", "-1001000000001", "GROUP", ["AIR_QOC"], True,
            )
            customer_route = telegram_destinations.upsert_destination(
                "Customer AIR QOC", "-1001000000002", "GROUP", ["AIR_QOC"], True,
                customer_id="customer-123",
            )
            self.assertEqual(telegram._chat_ids("AIR_QOC", "customer-123"),
                             [customer_route["chat_id"]])
            self.assertEqual(telegram._chat_ids("AIR_QOC", "customer-other"), [])
            self.assertEqual(telegram._chat_ids("AIR_QOC", None), [global_route["chat_id"]])


if __name__ == "__main__":
    unittest.main()
