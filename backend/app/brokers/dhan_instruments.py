"""Dhan public compact security-master loader with segment-safe symbol resolution."""
from __future__ import annotations

import csv
import io
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
SEGMENT_MAP = {
    ("NSE", "E"): "NSE_EQ", ("NSE", "D"): "NSE_FNO",
    ("NSE", "C"): "NSE_CURRENCY", ("NSE", "I"): "IDX_I",
    ("BSE", "E"): "BSE_EQ", ("BSE", "D"): "BSE_FNO",
    ("BSE", "C"): "BSE_CURRENCY", ("MCX", "M"): "MCX_COMM",
}


class DhanInstrumentMaster:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None,
                 ttl_seconds: int = 86400, timeout: float = 30.0):
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)
        self.ttl_seconds = ttl_seconds
        self._loaded_at = 0.0
        self._rows: list[dict[str, Any]] = []

    async def refresh(self, force: bool = False) -> int:
        if self._rows and not force and time.monotonic() - self._loaded_at < self.ttl_seconds:
            return len(self._rows)
        response = await self._http.get(MASTER_URL)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        required = {
            "SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_SMST_SECURITY_ID",
            "SEM_INSTRUMENT_NAME", "SEM_TRADING_SYMBOL", "SEM_CUSTOM_SYMBOL",
            "SM_SYMBOL_NAME", "SEM_LOT_UNITS", "SEM_EXPIRY_DATE",
            "SEM_STRIKE_PRICE", "SEM_OPTION_TYPE", "SEM_TICK_SIZE",
        }
        headers = set(reader.fieldnames or [])
        missing = required - headers
        if missing:
            raise ValueError(f"Dhan security master missing columns: {sorted(missing)}")
        rows = []
        for row in reader:
            segment = SEGMENT_MAP.get((
                (row.get("SEM_EXM_EXCH_ID") or "").strip().upper(),
                (row.get("SEM_SEGMENT") or "").strip().upper(),
            ))
            security_id = (row.get("SEM_SMST_SECURITY_ID") or "").strip()
            if segment and security_id.isdigit():
                row["_AIR_SEGMENT"] = segment
                rows.append(row)
        if not rows:
            raise ValueError("Dhan security master contained no supported instruments")
        self._rows = rows
        self._loaded_at = time.monotonic()
        return len(rows)

    async def search(self, query: str, *, limit: int = 50,
                     exchange_segment: str | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        await self.refresh()
        needle = query.strip().upper()
        if not needle:
            return []
        matches = []
        for row in self._rows:
            if exchange_segment and row["_AIR_SEGMENT"] != exchange_segment.upper():
                continue
            symbol = (row.get("SEM_TRADING_SYMBOL") or "").strip()
            custom = (row.get("SEM_CUSTOM_SYMBOL") or "").strip()
            underlying = (row.get("SM_SYMBOL_NAME") or "").strip()
            # Exact trading symbol and custom symbol precede fuzzy substring hits.
            rank = 0 if symbol.upper() == needle else 1 if custom.upper() == needle else 2
            if rank < 2 or needle in symbol.upper() or needle in custom.upper() or needle in underlying.upper():
                matches.append((rank, row))
        matches.sort(key=lambda item: (item[0], item[1].get("SEM_EXPIRY_DATE", "")))
        result = []
        for _, row in matches[:limit]:
            try:
                strike = Decimal(str(row.get("SEM_STRIKE_PRICE", "0")))
                lot_size = int(float(row.get("SEM_LOT_UNITS", "0") or 0))
            except (InvalidOperation, ValueError):
                strike, lot_size = Decimal("0"), 0
            result.append({
                "exchange": (row.get("SEM_EXM_EXCH_ID") or "").strip(),
                "segment": row["_AIR_SEGMENT"],
                "token": (row.get("SEM_SMST_SECURITY_ID") or "").strip(),
                "symbol": (row.get("SEM_TRADING_SYMBOL") or row.get("SEM_CUSTOM_SYMBOL") or "").strip(),
                "display_name": (row.get("SEM_CUSTOM_SYMBOL") or "").strip(),
                "underlying": (row.get("SM_SYMBOL_NAME") or "").strip(),
                "instrument": (row.get("SEM_INSTRUMENT_NAME") or "").strip(),
                "expiry": (row.get("SEM_EXPIRY_DATE") or "").strip() or None,
                "strike": strike if strike > 0 else None,
                "option_type": (row.get("SEM_OPTION_TYPE") or "").strip() or None,
                "lot_size": lot_size or None,
                "tick_size": row.get("SEM_TICK_SIZE"),
                "instrument_type": (row.get("SEM_INSTRUMENT_NAME") or "").strip(),
            })
        return result

    async def close(self) -> None:
        await self._http.aclose()
