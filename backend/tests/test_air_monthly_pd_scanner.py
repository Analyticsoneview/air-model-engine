from app.air_monthly_pd_scanner import _coverage, _bars


def test_coverage_fails_closed_when_constituent_history_is_short():
    bars = [{"trade_date": f"2026-11-{day:02d}"} for day in range(2, 10)]
    result = _coverage("ABC", bars, [f"2026-11-{day:02d}" for day in range(2, 16)])
    assert result["status"] == "DATA_INSUFFICIENT"
    assert result["observed_sessions"] == 8
    assert result["missing_sessions"]


def test_coverage_accepts_sufficient_completed_daily_sessions():
    dates = [f"2026-11-{day:02d}" for day in range(2, 22)]
    bars = [{"trade_date": day} for day in dates]
    result = _coverage("ABC", bars, dates)
    assert result["status"] == "READY"
    assert result["coverage_pct"] == 100


def test_bar_normalization_requires_completed_ohlc_values():
    rows = [
        {"trade_date": "2026-11-02", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
        {"trade_date": "2026-11-03", "open": 11, "high": None, "low": 10, "close": 11, "volume": 100},
    ]
    result = _bars(rows)
    assert len(result) == 1
    assert result[0]["date"] == "2026-11-02"



def test_calendar_session_range_includes_both_sides_of_year_boundary():
    from datetime import date
    from app.air_monthly_pd_scanner import _calendar_sessions_for_range

    class CalendarStore:
        def get_meta(self, key):
            if key in {"trading_calendar_2025", "trading_calendar_2026"}:
                return {"segments": {"CM": []}}
            return None

    sessions = _calendar_sessions_for_range(
        CalendarStore(), date(2025, 12, 15), date(2026, 1, 15)
    )
    assert "2025-12-15" in sessions
    assert "2025-12-31" in sessions
    assert "2026-01-01" in sessions
    assert "2026-01-15" in sessions


def test_stock_scan_waits_until_the_monthly_reference_session_is_completed():
    from app.air_monthly_pd_scanner import _stock_record

    raw_rows = []
    expected_dates = []
    for day in range(1, 13):
        stamp = f"2026-10-{day:02d}"
        expected_dates.append(stamp)
        raw_rows.append({
            "trade_date": stamp, "open": 100, "high": 105,
            "low": 95, "close": 101, "volume": 1000,
        })
    for day in range(2, 10):
        stamp = f"2026-11-{day:02d}"
        expected_dates.append(stamp)
        raw_rows.append({
            "trade_date": stamp, "open": 101, "high": 106,
            "low": 96, "close": 102, "volume": 1200,
        })
    sessions = {"2026-11-23": "TRADING_DAY"}
    result = _stock_record(
        "ABC", ["NIFTY100"], raw_rows, "2026-11-16",
        expected_dates, sessions,
    )
    assert result["qualification"] == "DATA_INSUFFICIENT"
    assert result["reference_date"] == "2026-11-23"
    assert "has not completed" in result["reason"]


def test_options_eod_candidate_requires_all_three_independent_evidence_checks():
    from app.air_monthly_pd_scanner import classify_option_eod_evidence
    result = classify_option_eod_evidence(
        premium_change_pct=8, volume=1800, volume_avg=1000, oi_change_pct=9)
    assert result["qualification"] == "EOD_CANDIDATE"
    assert result["strong_participation"] is False


def test_options_eod_missing_spread_does_not_get_fabricated_or_upgrade_to_strong():
    from app.air_monthly_pd_scanner import classify_option_eod_evidence
    result = classify_option_eod_evidence(
        premium_change_pct=8, volume=1800, volume_avg=1000, oi_change_pct=None)
    assert result["qualification"] == "DATA_INSUFFICIENT"
    assert result["evidence_score"] is None
