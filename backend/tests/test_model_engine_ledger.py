from datetime import date, timedelta

from app.model_engine_ledger import ModelEngineLedger


def record(**overrides):
    value = {
        "signal_id": "NIFTY-2027-01-28-25000-CE",
        "classification": "NEW",
        "signal_date": date.today().isoformat(),
        "symbol": "NIFTY",
        "instrument_type": "INDEX",
        "option_type": "CE",
        "expiry": (date.today() + timedelta(days=5)).isoformat(),
        "strike": 25000,
        "entry_price": 80,
        "latest_price": 92,
        "stop_loss": 60,
        "target_1": 110,
        "target_2": 140,
        "target_3": 180,
        "lot_size": 25,
        "quantity": 25,
        "score": 84,
        "shelf_life_days": 3,
        "evidence": {"underlying": "confirmed", "volume": "confirmed"},
    }
    value.update(overrides)
    return value


def test_upsert_and_customer_isolation():
    ledger = ModelEngineLedger(":memory:")
    ledger.upsert("customer-a", record())
    assert len(ledger.list_signals("customer-a")) == 1
    assert ledger.list_signals("customer-b") == []
    ledger.close()


def test_shelf_life_and_survivor_are_separate():
    ledger = ModelEngineLedger(":memory:")
    ledger.upsert("customer-a", record())
    row = ledger.list_signals("customer-a")[0]
    assert row["days_to_expiry"] == 5
    assert row["shelf_life_remaining_days"] == 3
    assert row["shelf_life_status"] == "SURVIVOR"
    ledger.close()


def test_missing_expiry_and_shelf_life_are_not_guessed():
    ledger = ModelEngineLedger(":memory:")
    ledger.upsert("customer-a", record(expiry=None, shelf_life_days=None))
    row = ledger.list_signals("customer-a")[0]
    assert row["days_to_expiry"] is None
    assert row["shelf_life_remaining_days"] is None
    assert row["shelf_life_status"] == "UNDEFINED"
    ledger.close()


def test_invalid_classification_rejected():
    ledger = ModelEngineLedger(":memory:")
    try:
        ledger.upsert("customer-a", record(classification="MAYBE"))
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid classification must be rejected")
    ledger.close()


def test_upsert_updates_existing_signal_without_duplicate():
    ledger = ModelEngineLedger(":memory:")
    ledger.upsert("customer-a", record())
    ledger.upsert("customer-a", record(classification="HOLD", latest_price=101))
    rows = ledger.list_signals("customer-a")
    assert len(rows) == 1
    assert rows[0]["classification"] == "HOLD"
    assert rows[0]["latest_price"] == 101
    ledger.close()



def test_common_position_fields_and_verified_reentry():
    ledger = ModelEngineLedger(":memory:")
    value = record(
        classification="RE-ENTRY",
        quantity=50,
        lot_size=25,
        pnl_pct=12.5,
        evidence={
            "sector": "BANKING",
            "pnl_points": 8.0,
            "reentry_verified": True,
            "underlying_confirmation": "3-candle reversal confirmed",
            "option_confirmation": "premium and volume confirmed",
        },
    )
    ledger.upsert("customer-a", value)
    row = ledger.list_signals("customer-a")[0]
    assert row["position_status"] == "OPEN"
    assert row["sector"] == "BANKING"
    assert row["pnl_points"] == 8.0
    assert row["pnl_rupees"] == 400.0
    assert row["days_to_expiry"] == 5
    ledger.close()


def test_reentry_without_verification_is_rejected():
    ledger = ModelEngineLedger(":memory:")
    try:
        ledger.upsert("customer-a", record(classification="RE-ENTRY"))
    except ValueError as exc:
        assert "reentry_verified" in str(exc)
    else:
        raise AssertionError("Unverified RE-ENTRY must be rejected")
    ledger.close()
