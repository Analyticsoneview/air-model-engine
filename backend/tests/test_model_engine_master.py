from datetime import date, timedelta

from app.model_engine_master import MASTER_COMMANDS, build_master


def row(signal_id, classification, dte=30, pnl=0, entry_price=5, entry_date=None):
    expiry = date.today() + timedelta(days=dte)
    return {
        "signal_id": signal_id, "classification": classification,
        "signal_date": date.today().isoformat(), "symbol": "NIFTY",
        "option_type": "CE", "expiry": expiry.isoformat(),
        "entry_date": entry_date if entry_date is not None else (expiry - timedelta(days=1)).isoformat(),
        "days_to_expiry": dte, "entry_price": entry_price, "pnl": pnl,
        "instrument_type": "INDEX" if signal_id.startswith("i") else "STOCK",
        "sector": "BANKING" if signal_id.startswith("s") else "INDEX",
    }


def test_master_groups_and_cross_cutting_survivor():
    result = build_master([
        row("i-a", "NEW", dte=5, pnl=10),
        row("s-b", "HOLD", dte=20, pnl=-2),
        row("s-c", "RE-ENTRY", dte=7),
        row("s-d", "SL", dte=40),
        row("s-e", "TARGETS", dte=40),
        row("s-f", "EXPIRED", dte=-1),
    ])
    assert result["counts"]["OPEN"] == 2
    assert result["counts"]["NEW"] == 1
    assert result["counts"]["HOLD"] == 1
    assert result["counts"]["REENTRY"] == 1
    assert result["counts"]["SLHIT"] == 1
    assert result["counts"]["SURVIVOR"] == 3
    assert result["counts"]["WAIT"] == 0
    assert result["counts"]["COMBINED"] == 6
    assert result["summary"]["pnl"] == 8
    assert result["breakdowns"]["instrument_type"]["INDEX"] == 1
    assert result["breakdowns"]["instrument_type"]["STOCK"] == 5


def test_master_deduplicates_and_declares_deferred_views():
    source = row("same", "NEW", dte=78)
    result = build_master([source, dict(source)])
    assert result["count"] == 1
    assert result["audit"]["deduplicated"] == 1
    assert "EXPIRY78" in result["vocabulary"]["implemented_views"]
    assert "ORIGINAL366" in result["vocabulary"]["implemented_views"]
    assert "RECOVERY" in result["vocabulary"]["deferred_views"]
    assert "MASTER" in MASTER_COMMANDS



def test_survivor_uses_pre_expiry_entry_not_0_to_7_dte():
    result = build_master([
        row("a", "HOLD", dte=20),
        row("b", "NEW", dte=0, entry_date=date.today().isoformat()),
        row("c", "NEW", dte=0, entry_date=(date.today() - timedelta(days=1)).isoformat()),
        row("d", "NEW", dte=-1, entry_date=(date.today() - timedelta(days=2)).isoformat()),
        row("e", "SL", dte=10),
        row("f", "NEW", dte=15, entry_date=""),
    ])
    assert result["counts"]["SURVIVOR"] == 2
    members = {item["signal_id"] for item in result["groups"]["SURVIVOR"]}
    assert members == {"a", "c"}
    assert all(item["survivor_rule"] == "EXPIRY78_PRE_EXPIRY_ENTRY"
               for item in result["groups"]["SURVIVOR"])


def test_preserves_original_11_contract_27_oct_expiry_case_study():
    from app.expiry_case_study_27oct2026 import (
        COHORT_ID, EXPIRY, historical_expired_contracts,
    )

    cohort = historical_expired_contracts()
    assert len(cohort) == 11
    assert {row["symbol"] for row in cohort} == {
        "ALKEM", "BPCL", "INDHOTEL", "JIOFIN", "LTF", "MIDCPNIFTY",
        "NIFTY", "TCS", "TVSMOTOR", "VMM",
    }
    assert all(row["classification"] == "EXPIRED" for row in cohort)
    assert all(row["expiry"] == EXPIRY == "2026-10-27" for row in cohort)
    assert all(row["cohort_id"] == COHORT_ID for row in cohort)
    assert all(row["days_to_expiry"] < 0 for row in cohort)
    assert all(row["latest_price"] == row["evidence"]["expiry_intrinsic"] for row in cohort)
    assert all(row["evidence"]["daily_history_available"] is True for row in cohort)
    result = build_master(cohort)
    assert result["counts"]["EXPIRED"] == 11
    assert result["summary"]["expired"] == 11


def test_strategy_views_are_isolated_and_stock_entry_filter_is_model_scoped():
    from app.model_engine_strategies import build_strategy_views

    expiry_stock = row("expiry-stock", "NEW", dte=20, entry_price=5)
    expiry_stock["evidence"] = {"strategy_memberships": ["EXPIRY78"]}
    original_stock = row("original-stock", "NEW", dte=20, entry_price=12)
    original_stock["evidence"] = {"strategy_memberships": ["ORIGINAL366"]}
    index_row = row("original-index", "NEW", dte=20, entry_price=150)
    index_row["instrument_type"] = "INDEX"
    index_row["remaining_trading_sessions"] = 10
    index_row["strike"] = 25000
    index_row["evidence"] = {"strategy_memberships": ["ORIGINAL366"]}
    recovery_row = row("recovery-stock", "RE-ENTRY", dte=20, entry_price=4)
    recovery_row["lot_size"] = 1000
    recovery_row["evidence"] = {
        "strategy_memberships": ["RECOVERY"],
        "recovery_verified": True,
        "original_entry_premium": 0.8,
    }
    result = build_strategy_views([expiry_stock, original_stock, index_row, recovery_row])

    assert {r["signal_id"] for r in result["EXPIRY78"]["groups"]["NEW"]} == {"expiry-stock"}
    # Out-of-band new stock candidates are rejected; index options are exempt.
    assert {r["signal_id"] for r in result["ORIGINAL366"]["groups"]["WAIT"]} == {"original-index"}
    assert result["ORIGINAL366"]["audit"]["stock_candidates_rejected_outside_1_to_10"] == 1
    assert result["ORIGINAL366"]["audit"]["stock_candidates_rejected_outside_1_to_10"] == 1
    assert {r["signal_id"] for r in result["RECOVERY"]["groups"]["REENTRY"]} == {"recovery-stock"}
    assert result["ORIGINAL366"]["baseline"]["full_expiry_coverage_cohort"] == 366
    assert result["ORIGINAL366"]["baseline"]["baseline_status"] == "COHORT_FILTER_ONLY"


def test_recovery_lot_size_rule_is_enforced():
    from app.model_engine_strategies import build_strategy_views

    recovery = row("recovery-large-lot", "RE-ENTRY", dte=20, entry_price=5)
    recovery["lot_size"] = 1500
    recovery["evidence"] = {
        "strategy_memberships": ["RECOVERY"],
        "recovery_verified": True,
        "original_entry_premium": 1.0,
    }
    result = build_strategy_views([recovery])
    assert result["RECOVERY"]["counts"]["REENTRY"] == 0
    assert result["RECOVERY"]["audit"]["recovery_candidates_rejected_without_verified_recovery_evidence"] == 1


def test_original366_replay_is_independent_and_does_not_rewrite_historical_baseline():
    from app.model_engine_strategies import ORIGINAL366_BASELINE, build_strategy_views

    contract = {
        "signal_id": "orig-engine-row",
        "classification": "NEW",
        "signal_date": "2026-11-03",
        "entry_date": "2026-11-03",
        "symbol": "TESTCO",
        "instrument_type": "STOCK",
        "option_type": "CE",
        "expiry": (date.today() + timedelta(days=30)).isoformat(),
        "strike": 100,
        "entry_price": 8.0,
        "remaining_trading_sessions": 13,
        "evidence": {
            "strategy_memberships": ["ORIGINAL366"],
            "daily_option_bars": [
                {"date": "2026-11-03", "open": 8, "high": 8.5, "low": 7.8, "close": 8.2, "quantity": 100},
            ],
        },
    }
    views = build_strategy_views([contract])
    original = views["ORIGINAL366"]
    assert original["replay"]["contracts_replayed"] == 1
    assert original["counts"]["HOLD"] == 1
    assert original["baseline"] == ORIGINAL366_BASELINE
    assert original["baseline"]["reference_cohort"] == "ORIGINAL366"
    assert original["baseline"]["display_section"] == "RECOVERED"
    assert original["baseline"]["source_entries"] == 534
    assert original["baseline"]["full_expiry_coverage_cohort"] == 366
    assert original["baseline"]["partial_coverage_excluded"] == 83
    assert original["baseline"]["no_post_entry_data_excluded"] == 85
    assert original["baseline"]["five_percent_sl_hits_in_full_coverage_cohort"] == 366



def test_original366_post_stop_close_is_added_to_recovered_open_lifecycle():
    from app.model_engine_strategies import build_strategy_views

    contract = {
        "signal_id": "recovered-watch-row",
        "classification": "SLHIT",
        "signal_date": "2026-11-03",
        "entry_date": "2026-11-03",
        "symbol": "TESTCO",
        "instrument_type": "STOCK",
        "option_type": "CE",
        "expiry": (date.today() + timedelta(days=30)).isoformat(),
        "strike": 100,
        "entry_price": 8.0,
        "remaining_trading_sessions": 13,
        "evidence": {
            "strategy_memberships": ["ORIGINAL366"],
            "daily_option_bars": [
                {"date": "2026-11-03", "open": 8, "high": 8.5, "low": 7.4, "close": 7.6, "quantity": 100},
                {"date": "2026-11-04", "open": 8.1, "high": 8.8, "low": 7.9, "close": 8.2, "quantity": 100},
            ],
        },
    }
    original = build_strategy_views([contract])["ORIGINAL366"]
    assert original["rules"]["name"] == "RECOVERED"
    assert original["counts"]["ORIGINAL_SLHIT"] == 1
    assert original["counts"]["RECOVERED"] == 1
    assert original["counts"]["OPEN"] == 1
    assert original["counts"]["SLHIT"] == 0
    watch = original["groups"]["RECOVERED"][0]
    assert watch["classification"] == "OPEN"
    assert watch["position_status"] == "OPEN"
    assert watch["entry_price"] == 8.0
    assert watch["stop_loss"] == 7.2
    assert watch["target_1"] == 11.6
    assert watch["watch"]["exit_model"]["simulation_basis"] == "ORIGINAL_ENTRY_PRICE_RETROSPECTIVE_EXIT_MODEL"
    assert original["counts"]["OPEN"] == 1



def _recovered_lifecycle_contract(expiry="2026-11-20", final_bar=None):
    bars = [
        {"date": "2026-11-03", "open": 8.0, "high": 8.5, "low": 7.4, "close": 7.6, "quantity": 100},
        {"date": "2026-11-04", "open": 8.1, "high": 8.8, "low": 7.9, "close": 8.2, "quantity": 100},
    ]
    if final_bar:
        bars.append(final_bar)
    return {
        "signal_id": "recovered-lifecycle",
        "classification": "SLHIT",
        "signal_date": "2026-11-03",
        "entry_date": "2026-11-03",
        "symbol": "TESTCO",
        "instrument_type": "STOCK",
        "option_type": "CE",
        "expiry": expiry,
        "strike": 100,
        "entry_price": 8.0,
        "remaining_trading_sessions": 13,
        "evidence": {"strategy_memberships": ["ORIGINAL366"], "daily_option_bars": bars},
    }


def test_recovered_target_exit_moves_to_targets_not_open():
    from app.model_engine_strategies import build_strategy_views

    contract = _recovered_lifecycle_contract(final_bar={
        "date": "2026-11-05", "open": 8.3, "high": 11.8, "low": 8.1, "close": 11.2, "quantity": 100,
    })
    view = build_strategy_views([contract])["ORIGINAL366"]
    assert view["counts"]["TARGETS"] == 1
    assert view["counts"]["OPEN"] == 0
    assert view["groups"]["TARGETS"][0]["exit_price"] == 11.6


def test_recovered_stop_exit_moves_to_slhit_not_open():
    from app.model_engine_strategies import build_strategy_views

    contract = _recovered_lifecycle_contract(final_bar={
        "date": "2026-11-05", "open": 7.5, "high": 8.9, "low": 7.0, "close": 7.4, "quantity": 100,
    })
    view = build_strategy_views([contract])["ORIGINAL366"]
    assert view["counts"]["SLHIT"] == 1
    assert view["counts"]["OPEN"] == 0
    assert view["groups"]["SLHIT"][0]["exit_price"] == 7.2


def test_recovered_expiry_settlement_moves_to_expired_not_open():
    from app.model_engine_strategies import build_strategy_views

    contract = _recovered_lifecycle_contract(
        expiry="2026-11-06",
        final_bar={
            "date": "2026-11-06", "open": 8.0, "high": 8.5, "low": 7.8,
            "close": 8.1, "quantity": 100, "underlying_close": 115,
        },
    )
    view = build_strategy_views([contract])["ORIGINAL366"]
    assert view["counts"]["EXPIRED"] == 1
    assert view["counts"]["OPEN"] == 0
    assert view["groups"]["EXPIRED"][0]["exit_reason"] == "EXPIRY_INTRINSIC_NO_TARGET_OR_STOP"

def test_strategy_views_sort_signal_date_desc_then_entry_price_ascending():
    from app.model_engine_strategies import build_strategy_views

    cheaper = row("recovery-cheaper", "RE-ENTRY", dte=20, entry_price=2.0)
    expensive = row("recovery-expensive", "RE-ENTRY", dte=20, entry_price=5.0)
    for candidate in (cheaper, expensive):
        candidate["lot_size"] = 100
        candidate["evidence"] = {
            "strategy_memberships": ["RECOVERY"],
            "recovery_verified": True,
            "original_entry_premium": 0.8,
        }

    result = build_strategy_views([expensive, cheaper])
    ordered = result["RECOVERY"]["groups"]["REENTRY"]
    assert [item["signal_id"] for item in ordered] == [
        "recovery-cheaper", "recovery-expensive",
    ]


from app.model_engine_deepcrash15 import evaluate_deepcrash15_contract, evaluate_deepcrash15_rows


def _deepcrash_contract():
    return {
        "signal_id": "deepcrash-test",
        "symbol": "TESTCO",
        "instrument_type": "STOCK",
        "option_type": "CE",
        "strike": 100,
        "expiry": "2027-01-15",
        "remaining_trading_sessions": 16,
        "evidence": {
            "daily_option_bars": [
                {"date": "2026-10-01", "open": 3200, "high": 3400, "low": 3100, "close": 3300, "quantity": 100},
                {"date": "2026-11-20", "open": 42, "high": 48, "low": 40, "close": 47, "quantity": 200},
            ]
        },
    }


def test_deepcrash15_qualifies_exact_contract_and_is_watch_only():
    result = evaluate_deepcrash15_contract(_deepcrash_contract())
    assert result["status"] == "QUALIFIED"
    assert result["classification"] == "WATCH"
    assert result["position_status"] == "WATCH"
    assert result["historical_peak_premium"] == 3400
    assert result["latest_close"] == 47
    assert result["remaining_trading_sessions"] == 16
    assert result["checks"] == {
        "historical_peak_in_range": True,
        "latest_close_below_50": True,
        "at_least_15_trading_sessions": True,
        "latest_candle_bullish": True,
    }


def test_deepcrash15_rejects_non_bullish_latest_candle_and_missing_shelf_evidence():
    contract = _deepcrash_contract()
    contract["evidence"]["daily_option_bars"][-1]["close"] = 41
    result = evaluate_deepcrash15_contract(contract)
    assert result["status"] == "REJECTED"
    assert result["checks"]["latest_candle_bullish"] is False

    contract = _deepcrash_contract()
    contract.pop("remaining_trading_sessions")
    result = evaluate_deepcrash15_contract(contract)
    assert result["status"] == "WAIT"
    assert "remaining_trading_sessions" in result["missing_evidence"][0]


def test_deepcrash15_scans_contracts_independently_without_changing_memberships():
    from app.model_engine_strategies import build_strategy_views

    contract = _deepcrash_contract()
    contract["evidence"]["strategy_memberships"] = ["EXPIRY78"]
    views = build_strategy_views([contract])
    assert views["DEEPCRASH15"]["counts"]["WATCH"] == 1
    assert views["DEEPCRASH15"]["counts"]["OPEN"] == 0
    assert views["DEEPCRASH15"]["groups"]["WATCH"][0]["option_type"] == "CE"
    assert views["EXPIRY78"]["count"] == 1



def _deepcrash_entry_contract():
    contract = _deepcrash_contract()
    contract["expiry"] = "2026-11-30"
    contract["evidence"]["daily_option_bars"] = [
        {"date": "2026-10-01", "open": 3200, "high": 3400, "low": 3100, "close": 3300, "quantity": 100},
        {"date": "2026-11-10", "open": 40, "high": 45, "low": 39, "close": 42, "quantity": 100},
        {"date": "2026-11-11", "open": 42, "high": 46, "low": 40, "close": 44, "quantity": 100},
        {"date": "2026-11-12", "open": 43, "high": 47, "low": 41, "close": 45, "quantity": 100},
        {"date": "2026-11-13", "open": 44, "high": 48, "low": 42, "close": 46, "quantity": 100},
        {"date": "2026-11-16", "open": 43, "high": 46, "low": 40, "close": 44, "quantity": 100},
        {"date": "2026-11-17", "open": 44, "high": 47, "low": 41, "close": 45, "quantity": 100},
        {"date": "2026-11-18", "open": 45, "high": 48, "low": 44, "close": 47, "quantity": 100},
        {"date": "2026-11-19", "open": 47, "high": 50, "low": 46, "close": 49, "quantity": 100},
    ]
    return contract


def test_deepcrash15_requires_six_session_tight_range_bullish_setup_and_next_close_breakout():
    contract = _deepcrash_entry_contract()
    result = evaluate_deepcrash15_contract(contract)
    assert result["status"] == "QUALIFIED"
    assert result["consolidation"]["lookback_sessions"] == 6
    assert result["consolidation"]["range_width"] <= 10
    assert result["consolidation"]["setup_bullish"] is True
    assert result["consolidation"]["next_close_above_setup_close"] is True
    assert result["position_status"] == "OPEN"
    assert result["entry_date"] == "2026-11-19"
    assert result["entry_price"] == 49
    assert result["hold_rule"] == "HOLD_TO_EXPIRY"


def test_deepcrash15_does_not_enter_without_next_day_close_confirmation_or_tight_range():
    contract = _deepcrash_entry_contract()
    contract["evidence"]["daily_option_bars"][-1]["close"] = 46
    result = evaluate_deepcrash15_contract(contract)
    assert result["position_status"] == "WATCH"
    assert result["entry_price"] is None

    contract = _deepcrash_entry_contract()
    for bar in contract["evidence"]["daily_option_bars"][1:7]:
        bar["high"] += 10
    result = evaluate_deepcrash15_contract(contract)
    assert result["consolidation"]["range_width"] > 10
    assert result["position_status"] == "WATCH"


def test_deepcrash15_holds_until_verified_expiry_close():
    contract = _deepcrash_entry_contract()
    contract["evidence"]["daily_option_bars"].append({
        "date": "2026-11-30", "open": 49, "high": 52, "low": 47, "close": 50, "quantity": 100,
    })
    result = evaluate_deepcrash15_contract(contract)
    assert result["position_status"] == "EXPIRED"
    assert result["exit_date"] == "2026-11-30"
    assert result["exit_price"] == 50
    # Expiry settlement must not replace the pre-expiry qualification/entry candle.
    assert result["latest_close"] == 49
    assert result["entry_date"] == "2026-11-19"
    assert result["entry_price"] == 49
