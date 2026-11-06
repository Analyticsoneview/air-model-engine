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
    assert "EXPIRY78" in result["vocabulary"]["deferred_views"]
    assert "ORIGINAL366" in result["vocabulary"]["deferred_views"]
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
