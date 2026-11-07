import pytest

from app import telegram_notifications as telegram


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


@pytest.mark.asyncio
async def test_notify_candidates_sends_once_per_candidate_and_chat(monkeypatch, tmp_path):
    FakeClient.sent = []
    monkeypatch.setattr(telegram.httpx, "AsyncClient", FakeClient)
    monkeypatch.setenv("AIR_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("AIR_TELEGRAM_CHAT_IDS", "111,-100222")
    monkeypatch.setenv("AIR_TELEGRAM_DEDUPE_DB_PATH", str(tmp_path / "telegram.sqlite3"))

    row = {
        "signal_id": "EXP78-001",
        "symbol": "TEST",
        "option_type": "CE",
        "strike": 100,
        "expiry": "2026-11-27",
        "classification": "NEW",
        "entry_price": 12.5,
        "stop_loss": 10.0,
    }

    first = await telegram.notify_candidates("EXPIRY78", [row])
    second = await telegram.notify_candidates("EXPIRY78", [row])

    assert first["sent"] == 2
    assert second["sent"] == 0
    assert len(FakeClient.sent) == 2
    assert all("AIR EXPIRY78" in item[1]["text"] for item in FakeClient.sent)


@pytest.mark.asyncio
async def test_expiryscan_message_is_not_misrepresented_as_qoc_trade(monkeypatch, tmp_path):
    FakeClient.sent = []
    monkeypatch.setattr(telegram.httpx, "AsyncClient", FakeClient)
    monkeypatch.setenv("AIR_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("AIR_TELEGRAM_CHAT_IDS", "111")
    monkeypatch.setenv("AIR_TELEGRAM_DEDUPE_DB_PATH", str(tmp_path / "telegram.sqlite3"))

    await telegram.notify_candidates("EXPIRYSCAN", [{
        "symbol": "TEST", "option_type": "PE", "strike": 200,
        "expiry": "2026-11-27", "scan_status": "LIQUIDITY_SCREEN_PASSED",
    }])

    assert len(FakeClient.sent) == 1
    assert "Liquidity-screen pass only" in FakeClient.sent[0][1]["text"]


def test_settings_supports_docker_secret_file(monkeypatch, tmp_path):
    token_file = tmp_path / "telegram-token"
    token_file.write_text("secret-token", encoding="utf-8")
    monkeypatch.delenv("AIR_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("AIR_TELEGRAM_BOT_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("AIR_TELEGRAM_CHAT_IDS", "111,-100222")

    token, chat_ids = telegram._settings()

    assert token == "secret-token"
    assert chat_ids == ["111", "-100222"]
