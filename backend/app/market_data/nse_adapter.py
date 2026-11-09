"""Adapter exposing AIR's reconciled NSE CM/FO EOD store as historical bars."""
from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal

from app.market_data.contracts import HistoricalBar, MarketInstrument
from app.nse_bhavcopy import nse_data_rows, nse_data_status


class NSEBhavcopyMarketDataAdapter:
    provider_code = "nse_bhavcopy"

    async def authenticate(self, account_id: str) -> None:
        if account_id != "official":
            raise ValueError("NSE Bhavcopy uses the official source account")
        # The local database connection is available before the asynchronous
        # initial archive bootstrap completes. Data readiness is reported separately.
        nse_data_status()

    def health(self) -> dict:
        status = nse_data_status()
        bootstrap = status.get("bootstrap", {})
        return {
            "provider": self.provider_code,
            "account_id": "official",
            "feed_state": "connected",
            "data_readiness": bootstrap.get("status", "NOT_STARTED"),
            "first_available_date": status.get("markets", {}).get("CM", {}).get("first_date"),
            "last_available_date": status.get("markets", {}).get("CM", {}).get("last_date"),
            "data_scope": "EOD daily candles only",
        }

    async def search_instruments(self, query: str, limit: int = 100,
                                 exchange_segment: str | None = None) -> list[MarketInstrument]:
        needle = query.strip().upper()
        if not needle:
            return []
        market = "FO" if exchange_segment and "FO" in exchange_segment.upper() else "CM"
        rows = nse_data_rows(market, symbol=needle, limit=min(max(limit, 1), 50000))
        result = []
        for row in rows:
            token = str(row.get("instrument_id") or row.get("instrument_key") or "")
            if not token:
                continue
            result.append(MarketInstrument(
                exchange="NSE", symbol=str(row.get("symbol") or ""),
                token=token, segment="NSE_FO" if market == "FO" else "NSE_EQ",
                expiry=row.get("expiry"),
                strike=Decimal(str(row["strike"])) if row.get("strike") is not None else None,
                option_type=row.get("option_type"),
                lot_size=int(row["lot_size"]) if row.get("lot_size") else None,
                instrument_type=str(row.get("instrument_type") or ""),
                underlying_symbol=str(row.get("symbol") or "").upper(),
            ))
        return result

    async def get_historical(self, instrument: MarketInstrument, start: datetime,
                             end: datetime, interval: str) -> list[HistoricalBar]:
        if interval.lower() not in {"day", "1d", "d"}:
            raise ValueError("NSE Bhavcopy provides EOD daily bars only")
        market = "FO" if "FO" in instrument.segment.upper() else "CM"
        rows = nse_data_rows(
            market, symbol=instrument.symbol,
            start_date=start.date().isoformat(), end_date=end.date().isoformat(),
            instrument_id=instrument.token, limit=500,
        )
        selected = rows
        result = []
        for row in selected:
            stamp = datetime.combine(
                datetime.fromisoformat(row["trade_date"]).date(),
                time(10, 0), tzinfo=timezone.utc,
            )
            close = row.get("close")
            if close is None:
                continue
            result.append(HistoricalBar(
                provider=self.provider_code, exchange="NSE",
                symbol=instrument.symbol, interval="day", start_time=stamp,
                open=Decimal(str(row.get("open") if row.get("open") is not None else close)),
                high=Decimal(str(row.get("high") if row.get("high") is not None else close)),
                low=Decimal(str(row.get("low") if row.get("low") is not None else close)),
                close=Decimal(str(close)),
                volume=int(row["volume"]) if row.get("volume") is not None else None,
                open_interest=int(row["open_interest"]) if row.get("open_interest") is not None else None,
            ))
        return sorted(result, key=lambda bar: bar.start_time)

    async def subscribe(self, instruments: list[MarketInstrument]) -> None:
        raise RuntimeError("NSE Bhavcopy is an EOD historical source, not a live feed")

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        return None

    async def close(self) -> None:
        return None
