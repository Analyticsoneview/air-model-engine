from app.historical_month_replay import replay_expiry78_month


def _bars():
    return [
        {"trade_date": "2026-10-26", "symbol": "AAA", "instrument_type": "OPTSTK",
         "expiry": "2026-10-29", "strike": 100, "option_type": "CE",
         "open": 10, "high": 11, "low": 7, "close": 8, "volume": 100,
         "underlying_price": 105},
        {"trade_date": "2026-10-27", "symbol": "AAA", "instrument_type": "OPTSTK",
         "expiry": "2026-10-29", "strike": 100, "option_type": "CE",
         "open": 7, "high": 13, "low": 6, "close": 12, "volume": 100,
         "underlying_price": 106},
        {"trade_date": "2026-10-28", "symbol": "AAA", "instrument_type": "OPTSTK",
         "expiry": "2026-10-29", "strike": 100, "option_type": "CE",
         "open": 5.5, "high": 6.0, "low": 5, "close": 5.8, "volume": 100,
         "underlying_price": 108},
        {"trade_date": "2026-10-29", "symbol": "AAA", "instrument_type": "OPTSTK",
         "expiry": "2026-10-29", "strike": 100, "option_type": "CE",
         "open": 6, "high": 7, "low": 5, "close": 6, "volume": 100,
         "underlying_price": 110},
    ]


def test_month_replay_finds_and_settles_expired_contract():
    report = replay_expiry78_month(_bars(), month="2026-10", as_of="2026-11-19")

    assert report["status"] == "COMPLETED"
    assert report["contracts_examined"] == 1
    assert report["contracts_with_qualifying_entries"] == 1
    assert report["trade_count"] == 1
    trade = report["trades"][0]
    assert trade["signal_date"] == "2026-10-27"
    assert trade["entry_date"] == "2026-10-28"
    assert trade["classification"] == "EXPIRED"
    assert trade["expiry_survivor"] is True
    assert trade["expiry_underlying_close"] == 110


def test_month_replay_does_not_include_other_expiry_months():
    rows = _bars() + [{
        **_bars()[-1], "expiry": "2026-11-26",
        "trade_date": "2026-11-19",
    }]
    report = replay_expiry78_month(rows, month="2026-10", as_of="2026-11-19")

    assert report["contracts_examined"] == 1
    assert report["trades"][0]["expiry"] == "2026-10-29"


def test_month_replay_reports_empty_month_without_fabricating_signals():
    report = replay_expiry78_month([], month="2026-10", as_of="2026-11-19")

    assert report["contracts_examined"] == 0
    assert report["trade_count"] == 0
    assert report["trades"] == []
