from datetime import date, timedelta

from app.model_engine_master import MASTER_COMMANDS, build_master


def row(signal_id, classification, dte=30, pnl=0, entry_price=5):
    expiry = date.today() + timedelta(days=dte)
    return {
        "signal_id": signal_id, "classification": classification,
        "signal_date": date.today().isoformat(), "symbol": "NIFTY",
        "option_type": "CE", "expiry": expiry.isoformat(),
        "days_to_expiry": dte, "entry_price": entry_price, "pnl": pnl,
    }


def test_master_groups_and_cross_cutting_survivor():
    result = build_master([
        row("a", "NEW", dte=5, pnl=10),
        row("b", "HOLD", dte=20, pnl=-2),
        row("c", "RE-ENTRY", dte=7),
        row("d", "SL", dte=40),
        row("e", "TARGETS", dte=40),
        row("f", "EXPIRED", dte=-1),
    ])
    assert result["counts"]["OPEN"] == 2
    assert result["counts"]["NEW"] == 1
    assert result["counts"]["HOLD"] == 1
    assert result["counts"]["REENTRY"] == 1
    assert result["counts"]["SLHIT"] == 1
    assert result["counts"]["SURVIVOR"] == 2
    assert result["counts"]["WAIT"] == 0
    assert result["counts"]["COMBINED"] == 6
    assert result["summary"]["pnl"] == 8


def test_master_deduplicates_and_declares_deferred_views():
    source = row("same", "NEW", dte=78)
    result = build_master([source, dict(source)])
    assert result["count"] == 1
    assert result["audit"]["deduplicated"] == 1
    assert "EXPIRY78" in result["vocabulary"]["deferred_views"]
    assert "ORIGINAL366" in result["vocabulary"]["deferred_views"]
    assert "RECOVERY" in result["vocabulary"]["deferred_views"]
    assert "MASTER" in MASTER_COMMANDS
