from app.model_engine_physical_forecast import forecast_physical_settlement, physical_settlement_early_warning


def _bars(closes, start="2026-11-01"):
    from datetime import date, timedelta
    day = date.fromisoformat(start)
    rows = []
    for i, close in enumerate(closes):
        d = day + timedelta(days=i)
        rows.append({"date": d.isoformat(), "open": close, "high": close * 1.01,
                     "low": close * 0.99, "close": close, "volume": 10000 + i})
    return rows


def test_missing_underlying_history_is_unknown_not_a_guessed_probability():
    result = forecast_physical_settlement({
        "instrument_type": "STOCK", "option_type": "CE", "strike": 100,
        "expiry": "2026-12-31", "evidence": {"daily_option_bars": [{"close": 50}]}
    }, as_of="2026-11-10")
    assert result["physical_settlement_risk"] == "UNKNOWN"
    assert result["itm_probability_pct"] is None
    assert result["forecast_status"] == "INSUFFICIENT_UNDERLYING_OHLCV"


def test_stock_ce_and_pe_forecasts_use_underlying_prices_and_return_bounded_probability():
    bars = _bars([100, 101, 100, 102, 101, 103, 102, 104, 103, 105, 106])
    base = {"instrument_type": "STOCK", "expiry": "2026-11-30",
            "quantity": 50, "evidence": {"daily_underlying_bars": bars}}
    call = forecast_physical_settlement({**base, "option_type": "CE", "strike": 100}, as_of="2026-11-11")
    put = forecast_physical_settlement({**base, "option_type": "PE", "strike": 110}, as_of="2026-11-11")
    assert 0 <= call["itm_probability_pct"] <= 100
    assert 0 <= put["itm_probability_pct"] <= 100
    assert call["forecast_stock_price"] > 0
    assert call["delivery_direction_if_itm"] == "TAKE_SHARES"
    assert put["delivery_direction_if_itm"] == "GIVE_SHARES"
    assert call["forecast_status"] == "MODEL_ESTIMATE_UNCALIBRATED"


def test_verified_expiry_close_overrides_forecast_and_marks_delivery():
    bars = _bars([100, 101, 100, 102, 101, 103, 102, 104, 103, 104, 112],
                 start="2026-11-01")
    result = forecast_physical_settlement({
        "instrument_type": "STOCK", "option_type": "CE", "strike": 110,
        "expiry": "2026-11-11", "quantity": 25,
        "evidence": {"daily_underlying_bars": bars}
    }, as_of="2026-11-12")
    assert result["forecast_status"] == "VERIFIED_EXPIRY_CLOSE"
    assert result["forecast_itm"] == "YES"
    assert result["itm_probability_pct"] == 100.0
    assert result["delivery_quantity_if_itm"] == 25
    assert result["estimated_strike_notional_if_itm"] == 2750.0


def test_index_options_are_excluded_from_physical_delivery():
    result = forecast_physical_settlement({
        "instrument_type": "INDEX", "option_type": "CE", "strike": 25000,
        "expiry": "2026-11-30", "evidence": {}
    })
    assert result["physical_settlement_risk"] == "NOT_APPLICABLE"
    assert result["delivery_direction"] == "CASH_SETTLED_INDEX"


def test_early_warning_qualifies_stock_call_while_position_is_open():
    bars = _bars([100, 101, 100, 102, 101, 103, 102, 104, 103, 104, 101],
                 start="2026-11-01")
    result = physical_settlement_early_warning({
        "instrument_type": "STOCK", "option_type": "CE", "strike": 100,
        "expiry": "2026-11-26", "entry_date": "2026-11-11", "quantity": 50,
        "evidence": {"daily_underlying_bars": bars}
    }, as_of="2026-11-11")
    assert result["status"] == "QUALIFIED"
    assert result["qualified"] is True
    assert result["delivery_direction_if_itm"] == "TAKE_SHARES"


def test_early_warning_critical_near_expiry_and_highlights_put_delivery():
    bars = _bars([100, 101, 100, 102, 101, 103, 102, 104, 103, 104, 99],
                 start="2026-11-01")
    result = physical_settlement_early_warning({
        "instrument_type": "STOCK", "option_type": "PE", "strike": 100,
        "expiry": "2026-11-14", "quantity": 25,
        "evidence": {"daily_underlying_bars": bars}
    }, as_of="2026-11-11")
    assert result["status"] == "CRITICAL"
    assert result["icon"] == "🔴"
    assert result["delivery_direction_if_itm"] == "GIVE_SHARES"


def test_early_warning_requires_underlying_data_and_excludes_index_options():
    missing = physical_settlement_early_warning({
        "instrument_type": "STOCK", "option_type": "CE", "strike": 100,
        "expiry": "2026-11-30", "evidence": {}
    })
    index = physical_settlement_early_warning({
        "instrument_type": "INDEX", "option_type": "CE", "strike": 25000,
        "expiry": "2026-11-30", "evidence": {}
    })
    assert missing["status"] == "DATA_REQUIRED"
    assert index["status"] == "NOT_APPLICABLE"
