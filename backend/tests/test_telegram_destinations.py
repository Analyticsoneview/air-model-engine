import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import telegram_destinations as destinations


class TelegramDestinationStoreTests(unittest.TestCase):
    def test_private_and_group_destinations_route_only_selected_strategies(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "AIR_TELEGRAM_CONFIG_DB_PATH": str(Path(folder) / "telegram-config.sqlite3"),
        }, clear=False):
            private = destinations.upsert_destination(
                "Admin private", "123456789", "PRIVATE",
                ["RECOVERED", "EXPIRY78"], True,
            )
            group = destinations.upsert_destination(
                "EXPIRYSCAN group", "-1001234567890", "GROUP",
                ["EXPIRYSCAN"], True,
            )

            self.assertEqual(private["destination_type"], "PRIVATE")
            self.assertEqual(group["destination_type"], "GROUP")
            self.assertEqual(destinations.destinations_for_strategy("RECOVERED"), ["123456789"])
            self.assertEqual(destinations.destinations_for_strategy("EXPIRYSCAN"), ["-1001234567890"])
            self.assertEqual(destinations.destinations_for_strategy("EXPIRY78"), ["123456789"])

    def test_disabled_destination_is_not_routed_and_can_be_deleted(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "AIR_TELEGRAM_CONFIG_DB_PATH": str(Path(folder) / "telegram-config.sqlite3"),
        }, clear=False):
            row = destinations.upsert_destination(
                "Disabled group", "-1001234567890", "GROUP",
                ["EXPIRY78"], False,
            )
            self.assertEqual(destinations.destinations_for_strategy("EXPIRY78"), [])
            self.assertTrue(destinations.delete_destination(row["id"]))
            self.assertTrue(destinations.has_managed_destinations())

    def test_destination_type_and_chat_id_must_match(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "AIR_TELEGRAM_CONFIG_DB_PATH": str(Path(folder) / "telegram-config.sqlite3"),
        }, clear=False):
            with self.assertRaises(ValueError):
                destinations.upsert_destination(
                    "Wrong group", "123456789", "GROUP", ["EXPIRY78"], True,
                )
            with self.assertRaises(ValueError):
                destinations.upsert_destination(
                    "Wrong private", "-1001234567890", "PRIVATE", ["EXPIRY78"], True,
                )

    def test_update_destination_changes_chat_id_and_strategy_selection(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "AIR_TELEGRAM_CONFIG_DB_PATH": str(Path(folder) / "telegram-config.sqlite3"),
        }, clear=False):
            row = destinations.upsert_destination(
                "AIR group", "-1001111111111", "GROUP", ["EXPIRY78"], True,
            )
            updated = destinations.update_destination(
                row["id"], name="AIR QOC group", chat_id="-1002222222222",
                destination_type="GROUP", strategies=["EXPIRY78", "RECOVERED"],
                enabled=True,
            )
            self.assertEqual(updated["name"], "AIR QOC group")
            self.assertEqual(destinations.destinations_for_strategy("RECOVERED"), ["-1002222222222"])
            self.assertEqual(destinations.destinations_for_strategy("EXPIRY78"), ["-1002222222222"])


if __name__ == "__main__":
    unittest.main()
