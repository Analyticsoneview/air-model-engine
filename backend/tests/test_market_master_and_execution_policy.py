from app.market_data.master_refresh import parse_master
from app.market_data.instrument_registry import MarketInstrumentDirectory
from app.services.execution_policy import ExecutionPolicy


def test_provider_master_refresh_replaces_only_after_validation():
    directory = MarketInstrumentDirectory(":memory:")
    rows = [{
        "exchange": "NFO", "tradingsymbol": f"ABC{i}", "instrument_token": str(i + 1),
        "segment": "NFO-OPT", "expiry": "2027-01-28", "strike": "100",
        "instrument_type": "CE", "lot_size": "25", "tick_size": "0.05",
    } for i in range(120)]
    parsed = parse_master("zerodha", ("\n".join(
        ["exchange,tradingsymbol,instrument_token,segment,expiry,strike,instrument_type,lot_size,tick_size"]
        + [",".join(str(row[key]) for key in (
            "exchange","tradingsymbol","instrument_token","segment","expiry","strike",
            "instrument_type","lot_size","tick_size")) for row in rows]
    )).encode(), "instruments.csv")
    assert len(parsed) == 120
    assert directory.replace_snapshot("zerodha", "ACC1", parsed) == 120
    assert directory.get("zerodha", "ACC1", "1")["lot_size"] == 25
    assert directory.master_status()[0]["row_count"] == 120
    try:
        directory.replace_snapshot("zerodha", "ACC1", [])
    except ValueError:
        pass
    else:
        raise AssertionError("Empty master must not delete the previous snapshot")
    assert directory.get("zerodha", "ACC1", "1") is not None
    directory.close()


def test_execution_policy_defaults_to_manual_and_requires_both_switches():
    policy = ExecutionPolicy(":memory:")
    initial = policy.get()
    assert initial["master_auto_enabled"] is False
    assert initial["manual_orders_enabled"] is True
    assert not any(initial["effective_auto"].values())
    try:
        policy.authorize_mode("EXPIRY78", "AUTO")
    except PermissionError:
        pass
    else:
        raise AssertionError("AUTO must be blocked by default")
    updated = policy.update(True, {"EXPIRY78": True})
    assert updated["effective_auto"]["EXPIRY78"] is True
    assert updated["effective_auto"]["EXPIRYSCAN"] is False
    policy.update(False, {"EXPIRY78": True})
    assert policy.authorize_mode("EXPIRY78", "MANUAL") == "MANUAL"
    try:
        policy.authorize_mode("EXPIRY78", "AUTO")
    except PermissionError:
        pass
    else:
        raise AssertionError("Master OFF must force manual mode")
    policy.close()
