from app.model_engine_physical_settlement import build_physical_settlement_review


def test_expiry78_physical_settlement_cohort_is_provisional_until_underlying_close():
    result = build_physical_settlement_review()

    assert result["source_contract_count"] == 45
    assert result["expiry_intrinsic_rows"] == 13
    assert result["underlying_expiry_close_available"] is False
    assert result["verification_status"] == "PENDING_OFFICIAL_UNDERLYING_EXPIRY_CLOSE"
    assert len(result["rows"]) == 13
    assert all(row["itm_status"] == "PENDING_UNDERLYING_CLOSE" for row in result["rows"])
    assert all(row["settlement_status"] == "PROVISIONAL_NOT_CONFIRMED" for row in result["rows"])


def test_long_stock_option_delivery_direction_and_strike_notional():
    result = build_physical_settlement_review()
    calls = [row for row in result["rows"] if row["option_type"] == "CE"]
    puts = [row for row in result["rows"] if row["option_type"] == "PE"]

    assert len(calls) == 8
    assert len(puts) == 5
    assert all(row["delivery_direction_if_itm"] == "TAKE_SHARES" for row in calls)
    assert all(row["delivery_direction_if_itm"] == "GIVE_SHARES" for row in puts)
    assert result["summary"]["take_delivery_share_quantity_if_all_calls_itm"] == 7025
    assert result["summary"]["give_delivery_share_quantity_if_all_puts_itm"] == 9300
    assert result["summary"]["gross_strike_value_exposure_if_all_itm"] == 7770725.0
