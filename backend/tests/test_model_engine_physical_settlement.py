from app.model_engine_physical_settlement import (
    build_physical_settlement_review,
    classify_stock_option_delivery,
)


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



def test_full_long_short_call_put_delivery_matrix_and_otm():
    assert classify_stock_option_delivery("CE", "LONG_OPTION", 100, 110, 50)["delivery_direction"] == "TAKE_SHARES"
    assert classify_stock_option_delivery("CE", "SHORT_OPTION", 100, 110, 50)["delivery_direction"] == "GIVE_SHARES"
    assert classify_stock_option_delivery("PE", "LONG_OPTION", 100, 90, 50)["delivery_direction"] == "GIVE_SHARES"
    assert classify_stock_option_delivery("PE", "SHORT_OPTION", 100, 90, 50)["delivery_direction"] == "TAKE_SHARES"
    assert classify_stock_option_delivery("CE", "LONG_OPTION", 100, 95, 50)["delivery_direction"] == "NO_DELIVERY"
