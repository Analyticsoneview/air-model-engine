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
