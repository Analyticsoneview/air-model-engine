"""Registry of existing AIR strategies eligible for historical research.

This module intentionally references existing rule definitions. It does not
create or approximate strategy logic. Intraday-only ORB is listed as unavailable
to daily-candle backtests until intraday historical bars are available.
"""
from __future__ import annotations

from typing import Any

from app.model_engine_expiry78 import RULES as EXPIRY78_RULES
from app.model_engine_original366 import ORIGINAL366_RULES
from app.model_engine_strategies import STRATEGY_RULES


def registered_backtest_strategies() -> list[dict[str, Any]]:
    """Return registered strategy metadata and honest daily-data eligibility."""
    entries = [
        {
            "id": "EXPIRY78",
            "name": "EXPIRY78",
            "family": "OPTIONS_DAILY",
            "rules": EXPIRY78_RULES,
            "source": "app.model_engine_expiry78.evaluate_expiry78_contract",
            "data_requirements": ["NSE FO daily option OHLCV", "contract expiry", "strike", "option type", "underlying expiry close"],
            "available_for_daily_backtest": True,
            "pnl_limitations": ["Rupee P&L requires verified historical lot size/position quantity and a configured charges model."],
        },
        {
            "id": "EXPIRYSCAN",
            "name": "EXPIRYSCAN",
            "family": "OPTIONS_SNAPSHOT",
            "rules": "Existing app.model_engine_expiryscan.scan_expiries evidence-screen rules",
            "source": "app.model_engine_expiryscan.scan_expiries",
            "data_requirements": ["time-stamped persisted option-chain observations", "provider/account identity", "bid/ask, volume and OI evidence"],
            "available_for_daily_backtest": False,
            "available_for_historical_report": True,
            "historical_report_mode": "PRESERVED_EXPIRY_COHORT_SUMMARY",
            "available_for_forward_report": True,
            "forward_report_endpoint": "/api/v1/backtest/expiryscan/forward/{account_id}",
            "forward_report_horizon_days": 30,
            "forward_qualification": "Existing positive volume, positive OI, two-sided bid/ask and spread-at-most-10-percent checks; this is a liquidity-screen pass, not a QOC trade signal.",
            "unavailable_reason": "Historical snapshot replay requires archived point-in-time option-chain snapshots; daily Bhavcopy bars must not be substituted.",
        },
        {
            "id": "ORIGINAL366",
            "name": "ORIGINAL366 / RECOVERED",
            "family": "OPTIONS_DAILY",
            "rules": ORIGINAL366_RULES,
            "source": "app.model_engine_original366.evaluate_original366_rows",
            "data_requirements": ["persisted ORIGINAL366 cohort", "verified daily option OHLCV", "expiry settlement evidence"],
            "available_for_daily_backtest": True,
            "pnl_limitations": ["Only the existing ORIGINAL366 cohort is eligible; do not infer cohort membership from all NSE contracts."],
        },
        {
            "id": "RECOVERY",
            "name": "RECOVERY",
            "family": "OPTIONS_DAILY",
            "rules": STRATEGY_RULES["RECOVERY"],
            "source": "app.model_engine_strategies.build_strategy_views / verified recovery evidence",
            "data_requirements": ["verified recovery evidence", "daily option OHLCV", "historical lot size"],
            "available_for_daily_backtest": True,
            "pnl_limitations": ["Requires explicitly verified recovery evidence; a generic RE-ENTRY label is insufficient."],
        },
        {
            "id": "ORB_MORNING",
            "name": "ORB Morning",
            "family": "INTRADAY",
            "rules": "Existing OrbSignalEngine morning rules",
            "source": "app.orb_strategy.OrbSignalEngine",
            "data_requirements": ["timestamped intraday ticks or candles covering 09:18–09:23 and subsequent 3-minute candles"],
            "available_for_daily_backtest": False,
            "unavailable_reason": "NSE daily OHLC candles cannot reproduce the opening range, retest, confirmation or executable tick exits.",
        },
        {
            "id": "ORB_AFTERNOON",
            "name": "ORB Afternoon",
            "family": "INTRADAY",
            "rules": "Existing OrbSignalEngine afternoon rules",
            "source": "app.orb_strategy.OrbSignalEngine",
            "data_requirements": ["timestamped intraday ticks covering 12:57–13:00 and subsequent executable ticks"],
            "available_for_daily_backtest": False,
            "unavailable_reason": "NSE daily OHLC candles cannot reproduce the 12:57–13:00 range or first-tick breakout execution.",
        },
    ]
    return entries
