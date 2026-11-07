"""EXPIRY78 stock-option physical-settlement review for the 27-Oct-2026 cohort.

The source ledger records 13 EXPIRY_INTRINSIC outcomes. Underlying expiry closes
are not embedded in that ledger, so delivery direction/notional is provisional
until the official expiry close and account-level netting are verified.
No broker actions are performed.
"""
from __future__ import annotations

from typing import Any

EXPIRY = "2026-10-27"
SOURCE = "EXPIRY78_45_trailing_backtest.csv"
_CASES = [
    ("OPTSTKHINDPETRO27-OCT-2026CE320", "HINDPETRO", "CE", 320, 2025, 11.40, 34.00, 45765.00),
    ("OPTSTKANGELONE27-OCT-2026CE270", "ANGELONE", "CE", 270, 2500, 6.40, 19.21, 32025.00),
    ("OPTSTKBAJAJHLDNG27-OCT-2026PE11300", "BAJAJHLDNG", "PE", 11300, 75, 132.54, 399.14, 19995.00),
    ("OPTSTKPERSISTENT27-OCT-2026CE5500", "PERSISTENT", "CE", 5500, 125, 136.50, 332.50, 24500.00),
    ("OPTSTKPFC27-OCT-2026PE325", "PFC", "PE", 325, 1300, 5.06, 9.41, 5655.00),
    ("OPTSTKATHERENERG27-OCT-2026CE1620", "ATHERENERG", "CE", 1620, 375, 19.24, 53.92, 13005.00),
    ("OPTSTKBDL27-OCT-2026PE1060", "BDL", "PE", 1060, 425, 18.95, 54.02, 14904.75),
    ("OPTSTKCOALINDIA27-OCT-2026CE395", "COALINDIA", "CE", 395, 1350, 4.22, 3.00, -1647.00),
    ("OPTSTKGMRAIRPORT27-OCT-2026PE91", "GMRAIRPORT", "PE", 91, 6975, 1.80, 1.52, -1953.00),
    ("OPTSTKLTM27-OCT-2026CE3950", "LTM", "CE", 3950, 150, 80.80, 109.70, 4335.00),
    ("OPTSTKMANKIND27-OCT-2026CE2360", "MANKIND", "CE", 2360, 250, 11.05, 142.48, 32857.50),
    ("OPTSTKMANKIND27-OCT-2026CE2500", "MANKIND", "CE", 2500, 250, 1.55, 2.48, 232.50),
    ("OPTSTKMAXHEALTH27-OCT-2026PE870", "MAXHEALTH", "PE", 870, 525, 13.48, 25.00, 6048.00),
]



def classify_stock_option_delivery(option_type: str, position_side: str, strike: float, underlying_expiry_close: float, quantity: int) -> dict[str, Any]:
    """Classify a verified stock-option expiry position and its physical obligation."""
    side = str(option_type).upper()
    position = str(position_side).upper()
    if side not in {"CE", "PE"} or position not in {"LONG_OPTION", "SHORT_OPTION"}:
        raise ValueError("option_type must be CE/PE and position_side LONG_OPTION/SHORT_OPTION")
    if strike <= 0 or underlying_expiry_close <= 0 or quantity <= 0:
        raise ValueError("strike, underlying close and quantity must be positive")
    itm = underlying_expiry_close > strike if side == "CE" else underlying_expiry_close < strike
    if not itm:
        return {"itm_status": "OTM", "delivery_direction": "NO_DELIVERY", "share_delivery_quantity": 0, "funds_payable": 0.0, "funds_receivable": 0.0}
    takes_shares = (side == "CE" and position == "LONG_OPTION") or (side == "PE" and position == "SHORT_OPTION")
    notional = round(strike * quantity, 2)
    return {"itm_status": "ITM", "delivery_direction": "TAKE_SHARES" if takes_shares else "GIVE_SHARES", "share_delivery_quantity": quantity, "funds_payable": notional if takes_shares else 0.0, "funds_receivable": notional if not takes_shares else 0.0}

def build_physical_settlement_review() -> dict[str, Any]:
    """Return provisional delivery obligations, never treating missing closes as verified ITM."""
    rows = []
    for contract, symbol, side, strike, quantity, entry, source_exit, pnl in _CASES:
        is_call = side == "CE"
        rows.append({
            "contract": contract,
            "symbol": symbol,
            "instrument_type": "STOCK_OPTION",
            "option_type": side,
            "position_side": "LONG_OPTION",
            "expiry": EXPIRY,
            "strike": strike,
            "quantity_shares": quantity,
            "entry_premium": entry,
            "source_recorded_expiry_value": source_exit,
            "source_gross_pnl": pnl,
            "underlying_expiry_close": None,
            "intrinsic_value_verified": False,
            "itm_status": "PENDING_UNDERLYING_CLOSE",
            "delivery_direction_if_itm": "TAKE_SHARES" if is_call else "GIVE_SHARES",
            "share_delivery_quantity_if_itm": quantity,
            "funds_obligation_at_strike_if_itm": round(strike * quantity, 2),
            "funds_payable_if_itm": round(strike * quantity, 2) if is_call else 0.0,
            "funds_receivable_if_itm": round(strike * quantity, 2) if not is_call else 0.0,
            "settlement_status": "PROVISIONAL_NOT_CONFIRMED",
        })

    calls = [row for row in rows if row["option_type"] == "CE"]
    puts = [row for row in rows if row["option_type"] == "PE"]
    total_notional = sum(row["funds_obligation_at_strike_if_itm"] for row in rows)
    return {
        "cohort": "EXPIRY78_45_CONTRACT_BACKTEST",
        "expiry": EXPIRY,
        "source": SOURCE,
        "source_contract_count": 45,
        "expiry_intrinsic_rows": len(rows),
        "stock_options_only": True,
        "index_options_included": False,
        "underlying_expiry_close_available": False,
        "verification_status": "PENDING_OFFICIAL_UNDERLYING_EXPIRY_CLOSE",
        "summary": {
            "provisional_take_delivery_contracts": len(calls),
            "provisional_give_delivery_contracts": len(puts),
            "take_delivery_share_quantity_if_all_calls_itm": sum(r["quantity_shares"] for r in calls),
            "give_delivery_share_quantity_if_all_puts_itm": sum(r["quantity_shares"] for r in puts),
            "provisional_call_funds_payable_if_itm": round(sum(r["funds_payable_if_itm"] for r in calls), 2),
            "provisional_put_funds_receivable_if_itm": round(sum(r["funds_receivable_if_itm"] for r in puts), 2),
            "gross_strike_value_exposure_if_all_itm": round(total_notional, 2),
        },
        "logic": {
            "long_stock_ce_itm": "TAKE_DELIVERY: buy quantity shares; funds payable = strike × quantity",
            "long_stock_pe_itm": "GIVE_DELIVERY: deliver quantity shares; funds receivable = strike × quantity",
            "otm": "No physical delivery obligation",
            "itm_test": "CE is ITM only when verified underlying expiry close > strike; PE is ITM only when verified underlying expiry close < strike",
            "short_stock_ce_itm": "GIVE_DELIVERY: deliver quantity shares; funds receivable = strike × quantity",
            "short_stock_pe_itm": "TAKE_DELIVERY: buy quantity shares; funds payable = strike × quantity",
            "index_options": "Cash settled; excluded from physical stock delivery",
            "netting": "Only net obligations after matching the same client/UCC, security and settlement context using broker/exchange-confirmed positions",
            "safety": "Never infer ITM from option premium, source exit label or intrinsic proxy. Never place or close an order.",
        },
        "rows": rows,
        "note": "Source ledger has recorded expiry values but no authoritative underlying expiry closes. All rows remain provisional until underlying close, ITM status, contract quantity and account-level netting are verified.",
    }
