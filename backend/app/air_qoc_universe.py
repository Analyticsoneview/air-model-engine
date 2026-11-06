"""Dhan instrument-master parser for the AIR QOC F&O universe.

Only normalized NSE option-underlying records are returned. The upstream CSV is
used as a reference source and is never persisted by this module.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime
from typing import Any

COMPACT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
DETAILED_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"

ALIASES = {
    "security_id": ("SEM_SMST_SECURITY_ID", "SECURITY_ID", "SMST_SECURITY_ID"),
    "exchange": ("SEM_EXM_EXCH_ID", "EXCH_ID"),
    "segment": ("SEM_SEGMENT", "SEGMENT"),
    "instrument": ("SEM_INSTRUMENT_NAME", "INSTRUMENT"),
    "symbol": ("SEM_TRADING_SYMBOL", "SM_SYMBOL_NAME", "SYMBOL_NAME"),
    "display": ("SEM_CUSTOM_SYMBOL", "DISPLAY_NAME"),
    "underlying_id": ("UNDERLYING_SECURITY_ID", "SEM_UNDERLYING_SECURITY_ID"),
    "underlying_symbol": ("UNDERLYING_SYMBOL", "SEM_UNDERLYING_SYMBOL"),
    "expiry": ("SEM_EXPIRY_DATE", "SM_EXPIRY_DATE", "EXPIRY_DATE"),
    "strike": ("SEM_STRIKE_PRICE", "STRIKE_PRICE"),
    "option_type": ("SEM_OPTION_TYPE", "OPTION_TYPE"),
    "lot_size": ("SEM_LOT_UNITS", "LOT_SIZE"),
    "expiry_flag": ("SEM_EXPIRY_FLAG", "EXPIRY_FLAG"),
}


def _value(row: dict[str, str], key: str) -> str:
    for name in ALIASES[key]:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _int(value: str) -> int | None:
    try:
        number = int(float(value))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _expiry(value: str) -> str | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value[:10], fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def parse_dhan_instrument_master(csv_text: str) -> dict[str, Any]:
    """Parse Dhan compact or detailed CSV into unique NSE F&O underlyings."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("Dhan instrument master CSV has no header")
    headers = set(reader.fieldnames)
    if not any(alias in headers for alias in ALIASES["security_id"]):
        raise ValueError("Dhan instrument master is missing a recognized security-ID column")

    underlyings: dict[tuple[str, str], dict[str, Any]] = {}
    expiries: dict[tuple[str, str], set[str]] = defaultdict(set)
    option_rows = 0
    skipped = 0

    for row in reader:
        exchange = _value(row, "exchange").upper()
        segment = _value(row, "segment").upper()
        instrument = _value(row, "instrument").upper()
        if exchange != "NSE" or segment != "D" or instrument not in {"OPTIDX", "OPTSTK"}:
            continue
        option_rows += 1
        underlying_symbol = _value(row, "underlying_symbol")
        underlying_id = _int(_value(row, "underlying_id"))
        if not underlying_symbol:
            symbol = _value(row, "symbol")
            # Conservative fallback: remove derivative suffix only when the
            # explicit underlying symbol is absent; ambiguous rows are skipped.
            underlying_symbol = symbol.split()[0] if symbol else ""
        if not underlying_symbol or not underlying_id:
            skipped += 1
            continue

        is_index = instrument == "OPTIDX"
        underlying_segment = "IDX_I" if is_index else "NSE_EQ"
        key = (underlying_symbol.upper(), underlying_segment)
        entry = underlyings.setdefault(key, {
            "symbol": underlying_symbol.upper(),
            "security_id": underlying_id,
            "exchange_segment": underlying_segment,
            "instrument": instrument,
            "option_contract_rows": 0,
            "expiries": [],
            "lot_sizes": [],
        })
        # Conflicting IDs for one symbol are a data-quality error; surface it
        # rather than silently choosing an arbitrary row.
        if entry["security_id"] != underlying_id:
            entry["id_conflict"] = True
        entry["option_contract_rows"] += 1
        expiry = _expiry(_value(row, "expiry"))
        if expiry:
            expiries[key].add(expiry)
        lot = _int(_value(row, "lot_size"))
        if lot and lot not in entry["lot_sizes"]:
            entry["lot_sizes"].append(lot)

    for key, entry in underlyings.items():
        entry["expiries"] = sorted(expiries[key])
        entry["expiry_count"] = len(entry["expiries"])
        entry["lot_sizes"] = sorted(entry["lot_sizes"])
        entry["validated"] = not entry.get("id_conflict", False) and bool(entry["expiries"])

    records = sorted(underlyings.values(), key=lambda x: (x["instrument"], x["symbol"]))
    stocks = [x for x in records if x["instrument"] == "OPTSTK"]
    indices = [x for x in records if x["instrument"] == "OPTIDX"]
    return {
        "source": "Dhan official instrument master",
        "exchange": "NSE",
        "option_contract_rows": option_rows,
        "skipped_rows": skipped,
        "stock_underlying_count": len(stocks),
        "index_underlying_count": len(indices),
        "total_underlying_count": len(records),
        "validated_underlying_count": sum(1 for x in records if x["validated"]),
        "underlyings": records,
    }
