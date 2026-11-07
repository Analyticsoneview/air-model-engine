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
    index_row["evidence"] = {"strategy_memberships": ["ORIGINAL366"]}
    recovery_row = row("recovery-stock", "RE-ENTRY", dte=20, entry_price=4)
    recovery_row["evidence"] = {
        "strategy_memberships": ["RECOVERY"],
        "recovery_verified": True,
        "original_entry_premium": 0.8,
    }
    result = build_strategy_views([expiry_stock, original_stock, index_row, recovery_row])

    assert {r["signal_id"] for r in result["EXPIRY78"]["groups"]["NEW"]} == {"expiry-stock"}
    # Out-of-band new stock candidates are rejected; index options are exempt.
    assert {r["signal_id"] for r in result["ORIGINAL366"]["groups"]["NEW"]} == {"original-index"}
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
        "expiry": "2026-11-20",
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



def test_original366_post_stop_close_is_added_to_recovered_watch_without_opening_position():
    from app.model_engine_strategies import build_strategy_views

    contract = {
        "signal_id": "recovered-watch-row",
        "classification": "SLHIT",
        "signal_date": "2026-11-03",
        "entry_date": "2026-11-03",
        "symbol": "TESTCO",
        "instrument_type": "STOCK",
        "option_type": "CE",
        "expiry": "2026-11-20",
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
    assert original["counts"]["SLHIT"] == 1
    assert original["counts"]["RECOVERED"] == 1
    watch = original["groups"]["RECOVERED"][0]
    assert watch["classification"] == "RECOVERED_WATCH"
    assert watch["position_status"] == "WATCH_ONLY_NOT_OPEN"
    assert watch["entry_price"] == 8.0
    assert watch["stop_loss"] == 7.2
    assert watch["target_1"] == 11.6
    assert watch["watch"]["exit_model"]["simulation_basis"] == "ORIGINAL_ENTRY_PRICE_RETROSPECTIVE_EXIT_MODEL"
    assert original["counts"]["OPEN"] == 0
