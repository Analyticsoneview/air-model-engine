from app.backtest_registry import registered_backtest_strategies


def test_backtest_registry_uses_existing_strategies_only():
    strategies = {item["id"]: item for item in registered_backtest_strategies()}
    assert {"EXPIRY78", "ORIGINAL366", "RECOVERY", "ORB_MORNING", "ORB_AFTERNOON"} == set(strategies)
    assert strategies["EXPIRY78"]["source"].endswith("evaluate_expiry78_contract")
    assert strategies["ORIGINAL366"]["source"].endswith("evaluate_original366_rows")
    assert strategies["RECOVERY"]["source"].startswith("app.model_engine_strategies")
    assert strategies["ORB_MORNING"]["available_for_daily_backtest"] is False
    assert strategies["ORB_AFTERNOON"]["available_for_daily_backtest"] is False
    assert "daily candles" in strategies["ORB_MORNING"]["unavailable_reason"]


def test_backtest_registry_exposes_daily_and_intraday_families():
    strategies = registered_backtest_strategies()
    daily = [item["id"] for item in strategies if item["available_for_daily_backtest"]]
    intraday = [item["id"] for item in strategies if not item["available_for_daily_backtest"]]
    assert daily == ["EXPIRY78", "ORIGINAL366", "RECOVERY"]
    assert intraday == ["ORB_MORNING", "ORB_AFTERNOON"]
