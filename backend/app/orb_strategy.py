"""Live, customer-scoped ORB signal engine for AIR.

The engine emits signals only. It never places broker orders.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _dt(value: Any, fallback: Any = None) -> datetime | None:
    for candidate in (value, fallback):
        if not candidate:
            continue
        try:
            parsed = candidate if isinstance(candidate, datetime) else datetime.fromisoformat(
                str(candidate).replace("Z", "+00:00")
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=IST)
            return parsed.astimezone(IST)
        except (TypeError, ValueError):
            continue
    return None


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None and str(value) != "" else None
    except (InvalidOperation, ValueError):
        return None


class OrbSignalEngine:
    """Builds the 09:18–09:23 range and 12:57–13:00 range from live ticks."""

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = {str(x).upper(): self._new_symbol_state() for x in (symbols or [])}
        self.signals: list[dict[str, Any]] = []
        self.last_tick_at: str | None = None
        self.feed_count = 0

    @staticmethod
    def _new_symbol_state() -> dict[str, Any]:
        return {
            "session_date": None,
            "morning": {"high": None, "low": None, "breakout": False,
                        "retested": False, "entry": None, "last_candle": None,
                        "building": None, "pending_exit": False},
            "afternoon": {"high": None, "low": None, "entry": None},
        }

    def add_symbols(self, symbols: list[str]) -> None:
        for symbol in symbols:
            self.symbols.setdefault(str(symbol).upper(), self._new_symbol_state())

    def on_tick(self, tick: dict[str, Any]) -> None:
        symbol = str(tick.get("symbol") or "").upper()
        if symbol not in self.symbols:
            return
        price = _decimal(tick.get("ltp"))
        stamp = _dt(tick.get("exchange_time"), tick.get("received_at"))
        if price is None or stamp is None:
            return
        if stamp.weekday() >= 5:
            return
        state = self.symbols[symbol]
        day = stamp.date().isoformat()
        if state["session_date"] != day:
            state.clear()
            state.update(self._new_symbol_state())
            state["session_date"] = day
        self.last_tick_at = stamp.isoformat()
        self.feed_count += 1
        clock = stamp.time().replace(tzinfo=None)
        morning = state["morning"]
        afternoon = state["afternoon"]

        # The opening range is the actual five-minute window 09:18:00–09:22:59.
        if time(9, 18) <= clock < time(9, 23):
            morning["high"] = price if morning["high"] is None else max(morning["high"], price)
            morning["low"] = price if morning["low"] is None else min(morning["low"], price)
        elif time(9, 23) <= clock < time(15, 15):
            self._morning_tick(symbol, morning, price, stamp)

        # Afternoon range is the 12:57:00–12:59:59 candle. Breakout is tick-triggered.
        if time(12, 57) <= clock < time(13, 0):
            afternoon["high"] = price if afternoon["high"] is None else max(afternoon["high"], price)
            afternoon["low"] = price if afternoon["low"] is None else min(afternoon["low"], price)
        elif time(13, 0) <= clock < time(15, 15):
            high, low = afternoon["high"], afternoon["low"]
            if high is not None and low is not None and afternoon["entry"] is None and price > high:
                signal = self._signal(symbol, "AFTERNOON", stamp, price, low, high)
                afternoon["entry"] = signal
                self.signals.append(signal)
            entry = afternoon["entry"]
            if entry and entry["status"] == "OPEN" and price <= Decimal(str(entry["stop_loss"])):
                entry.update({"status": "SL_HIT", "exit_price": str(price),
                              "exit_at": stamp.isoformat(), "exit_reason": "RANGE_LOW_STOP"})

    def _morning_tick(self, symbol: str, state: dict[str, Any],
                      price: Decimal, stamp: datetime) -> None:
        high = state["high"]
        if high is None:
            return
        entry = state["entry"]
        # A protective stop is tick-monitored; a stop is never moved down.
        if entry and entry["status"] == "OPEN" and price <= Decimal(str(entry["stop_loss"])):
            entry.update({"status": "SL_HIT", "exit_price": str(price),
                          "exit_at": stamp.isoformat(), "exit_reason": "TRAILING_STOP"})
            return

        # 3-minute bars are aligned to NSE's 09:15 session open.
        minutes = stamp.hour * 60 + stamp.minute
        offset = minutes - (9 * 60 + 15)
        bucket_start = (offset // 3) * 3 + (9 * 60 + 15)
        start = datetime.combine(stamp.date(), time(bucket_start // 60, bucket_start % 60), IST)
        building = state["building"]
        if building is None or building["start"] != start.isoformat():
            if building is not None:
                self._complete_morning_candle(symbol, state, building, stamp)
            state["building"] = {"start": start.isoformat(), "open": price,
                                 "high": price, "low": price, "close": price}
            return
        building["high"] = max(building["high"], price)
        building["low"] = min(building["low"], price)
        building["close"] = price

    def _complete_morning_candle(self, symbol: str, state: dict[str, Any],
                                 candle: dict[str, Any], next_stamp: datetime) -> None:
        high = state["high"]
        close = Decimal(str(candle["close"]))
        low = Decimal(str(candle["low"]))
        previous = state["last_candle"]
        if state["entry"] is None:
            if not state["breakout"] and close > high:
                state["breakout"] = True
            elif state["breakout"] and not state["retested"] and low <= high:
                state["retested"] = True
            elif state["breakout"] and state["retested"] and close > high:
                signal = self._signal(symbol, "MORNING", next_stamp, close, low, high)
                state["entry"] = signal
                self.signals.append(signal)
        else:
            entry = state["entry"]
            if entry["status"] == "OPEN":
                if previous and close < Decimal(str(previous["open"])):
                    entry["pending_exit"] = True
                elif low > Decimal(str(entry["stop_loss"])):
                    entry["stop_loss"] = str(low)
        if state["entry"] and state["entry"]["status"] == "OPEN" and state["entry"].get("pending_exit"):
            state["entry"].update({"status": "EXIT_SIGNAL",
                                   "exit_at": next_stamp.isoformat(),
                                   "exit_reason": "CLOSE_BELOW_PREVIOUS_CANDLE_OPEN"})
        state["last_candle"] = candle

    @staticmethod
    def _signal(symbol: str, session: str, stamp: datetime,
                entry: Decimal, stop: Decimal, range_high: Decimal) -> dict[str, Any]:
        return {
            "signal_id": f"ORB:{session}:{stamp.date().isoformat()}:{symbol}",
            "strategy": f"ORB_{session}",
            "symbol": symbol,
            "session_date": stamp.date().isoformat(),
            "entry_at": stamp.isoformat(),
            "entry_price": str(entry),
            "stop_loss": str(stop),
            "range_high": str(range_high),
            "status": "OPEN",
            "pending_exit": False,
            "execution": "SIGNAL_ONLY_NO_ORDER_PLACED",
        }

    def snapshot(self) -> dict[str, Any]:
        rows = []
        for symbol, state in sorted(self.symbols.items()):
            rows.append({
                "symbol": symbol,
                "session_date": state.get("session_date"),
                "morning": {
                    "range_high": str(state["morning"]["high"]) if state["morning"]["high"] is not None else None,
                    "range_low": str(state["morning"]["low"]) if state["morning"]["low"] is not None else None,
                    "breakout": state["morning"]["breakout"],
                    "retested": state["morning"]["retested"],
                    "entry": state["morning"]["entry"],
                },
                "afternoon": {
                    "range_high": str(state["afternoon"]["high"]) if state["afternoon"]["high"] is not None else None,
                    "range_low": str(state["afternoon"]["low"]) if state["afternoon"]["low"] is not None else None,
                    "entry": state["afternoon"]["entry"],
                },
            })
        return {"symbols": rows, "signals": self.signals[-100:],
                "last_tick_at": self.last_tick_at, "tick_count": self.feed_count}
