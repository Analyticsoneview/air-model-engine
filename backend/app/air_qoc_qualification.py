"""Evidence-based AIR QOC qualification over repeated normalized option snapshots.

A single snapshot is never a signal. A contract needs two time-separated observations,
freshness, directional underlying confirmation, premium/volume/OI confirmation, and
a usable two-sided quote before it can be qualified.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

IST = ZoneInfo("Asia/Kolkata")
MODE_MAX_AGE_SECONDS = {"LIVE": 300, "POSITIONAL": 1800, "POST_MARKET": 86400}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=IST) if result.tzinfo is None else result.astimezone(IST)
    except (TypeError, ValueError):
        return None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return (current - previous) / previous * 100.0


def _classify(score: int, failures: list[str]) -> str:
    if failures or score < 70:
        return "REJECT"
    if score >= 90:
        return "HIGH_CONVICTION"
    if score >= 80:
        return "QUALIFIED"
    return "WATCH"


def qualify_option_observations(
    observations: list[dict[str, Any]],
    *,
    mode: str = "LIVE",
    now: datetime | None = None,
    max_candidates: int = 100,
) -> dict[str, Any]:
    """Score latest-vs-prior observations; output evidence, gates and risk references."""
    mode = mode.upper()
    if mode not in MODE_MAX_AGE_SECONDS:
        raise ValueError("mode must be LIVE, POSITIONAL or POST_MARKET")
    reference_time = now or datetime.now(IST)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=IST)
    current_time = reference_time.astimezone(IST)
    max_age = MODE_MAX_AGE_SECONDS[mode]

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in observations:
        key = (
            str(row.get("underlying_scrip") or ""),
            str(row.get("expiry") or ""),
            str(row.get("strike") or ""),
            str(row.get("option_type") or "").upper(),
        )
        grouped.setdefault(key, []).append(row)

    results: list[dict[str, Any]] = []
    for (underlying, expiry, strike_text, option_type), samples in grouped.items():
        samples.sort(key=lambda item: _time(item.get("observed_at")) or datetime.min.replace(tzinfo=IST), reverse=True)
        latest = samples[0]
        previous = next(
            (item for item in samples[1:]
             if str(item.get("observed_at")) != str(latest.get("observed_at"))),
            None,
        )
        failures: list[str] = []
        score = 0
        breakdown: dict[str, int] = {}

        observed = _time(latest.get("observed_at"))
        prior_observed = _time(previous.get("observed_at")) if previous else None
        same_session_pair = (
            observed is not None and prior_observed is not None
            and observed.date() == current_time.date()
            and prior_observed.date() == current_time.date()
            and prior_observed < observed
        )
        snapshot_gap_seconds = (observed - prior_observed).total_seconds() if same_session_pair else None
        pair_is_fresh = (
            same_session_pair and snapshot_gap_seconds is not None
            and snapshot_gap_seconds <= max_age
        )
        previous_sample = previous if pair_is_fresh else None
        age_seconds = (current_time - observed).total_seconds() if observed else None
        fresh = (
            age_seconds is not None and 0 <= age_seconds <= max_age
            and observed.date() == current_time.date()
        )
        if fresh:
            breakdown["freshness"] = 5
            score += 5
        else:
            failures.append("STALE_OR_WRONG_SESSION_DATA")

        if not same_session_pair:
            failures.append("SECOND_SAME_SESSION_OBSERVATION_REQUIRED")
        elif not pair_is_fresh:
            failures.append("SNAPSHOT_PAIR_GAP_TOO_WIDE")

        spot = _num(latest.get("underlying_price"))
        prior_spot = _num(previous_sample.get("underlying_price")) if previous_sample else None
        spot_change = _pct_change(spot, prior_spot)
        expected_move = spot_change is not None and (
            (option_type == "CE" and spot_change >= 0.05)
            or (option_type == "PE" and spot_change <= -0.05)
        )
        if expected_move:
            direction_score = 20 if abs(spot_change) >= 0.5 else 15 if abs(spot_change) >= 0.2 else 10
            breakdown["underlying_direction"] = direction_score
            score += direction_score
        else:
            failures.append("UNDERLYING_DIRECTION_NOT_CONFIRMED")

        premium = _num(latest.get("last_price"))
        prior_premium = _num(previous_sample.get("last_price")) if previous_sample else None
        premium_change = _pct_change(premium, prior_premium)
        if premium_change is not None and premium_change >= 2.0:
            premium_score = 20 if premium_change >= 10 else 15 if premium_change >= 5 else 10
            breakdown["premium_acceleration"] = premium_score
            score += premium_score
        else:
            failures.append("PREMIUM_NOT_ACCELERATING")

        volume = _int(latest.get("volume"))
        prior_volume = _int(previous_sample.get("volume")) if previous_sample else None
        volume_delta = volume - prior_volume if volume is not None and prior_volume is not None else None
        if volume_delta is not None and volume_delta > 0:
            volume_score = 15 if volume_delta >= 500 else 10 if volume_delta >= 100 else 5
            breakdown["volume_confirmation"] = volume_score
            score += volume_score
        else:
            failures.append("VOLUME_NOT_INCREASING")

        oi = _int(latest.get("open_interest"))
        prior_oi = _int(previous_sample.get("open_interest")) if previous_sample else None
        oi_delta = oi - prior_oi if oi is not None and prior_oi is not None else None
        if oi_delta is not None and oi_delta > 0:
            oi_score = 15 if oi_delta >= 500 else 10 if oi_delta >= 100 else 5
            breakdown["oi_confirmation"] = oi_score
            score += oi_score
        else:
            failures.append("OI_NOT_INCREASING")

        bid = _num(latest.get("bid_price"))
        ask = _num(latest.get("ask_price"))
        bid_qty = _int(latest.get("bid_quantity")) or 0
        ask_qty = _int(latest.get("ask_quantity")) or 0
        spread_pct = (
            ((ask - bid) / ((ask + bid) / 2.0) * 100.0)
            if bid is not None and ask is not None and ask >= bid and (ask + bid) > 0
            else None
        )
        liquid = (
            spread_pct is not None and spread_pct <= 5.0
            and bid_qty > 0 and ask_qty > 0
        )
        if liquid:
            liquidity_score = 15 if spread_pct <= 1.5 else 10 if spread_pct <= 3.0 else 5
            breakdown["liquidity"] = liquidity_score
            score += liquidity_score
        else:
            failures.append("TWO_SIDED_LIQUIDITY_FAILED")

        strike = _num(strike_text)
        otm_pct = None
        is_otm = False
        if spot is not None and spot > 0 and strike is not None:
            if option_type == "CE" and strike > spot:
                otm_pct = (strike - spot) / spot * 100.0
                is_otm = 0.05 <= otm_pct <= 5.0
            elif option_type == "PE" and strike < spot:
                otm_pct = (spot - strike) / spot * 100.0
                is_otm = 0.05 <= otm_pct <= 5.0
        if is_otm:
            otm_score = 10 if 0.1 <= otm_pct <= 3.0 else 5
            breakdown["otm_distance"] = otm_score
            score += otm_score
        else:
            failures.append("OTM_DISTANCE_OUTSIDE_0_5_PERCENT")

        score = min(100, score)
        classification = _classify(score, failures)
        dte = None
        try:
            dte = (datetime.fromisoformat(expiry).date() - current_time.date()).days
        except ValueError:
            failures.append("INVALID_EXPIRY")
            classification = "REJECT"
        if dte is not None and dte < 0:
            failures.append("CONTRACT_EXPIRED")
            classification = "REJECT"

        entry = premium
        results.append({
            "underlying": underlying,
            "expiry": expiry,
            "dte": dte,
            "strike": strike_text,
            "option_type": option_type,
            "security_id": latest.get("security_id"),
            "classification": classification,
            "score": score,
            "entry_premium": entry,
            "stop_loss_reference": round(entry * 0.70, 2) if entry is not None else None,
            "targets_reference": {
                "plus_50_percent": round(entry * 1.5, 2),
                "plus_100_percent": round(entry * 2.0, 2),
                "plus_200_percent": round(entry * 3.0, 2),
                "plus_300_percent": round(entry * 4.0, 2),
            } if entry is not None else {},
            "underlying_price": spot,
            "underlying_change_pct": round(spot_change, 3) if spot_change is not None else None,
            "premium_change_pct": round(premium_change, 3) if premium_change is not None else None,
            "volume": volume,
            "volume_delta": volume_delta,
            "open_interest": oi,
            "oi_delta": oi_delta,
            "otm_pct": round(otm_pct, 3) if otm_pct is not None else None,
            "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
            "bid_quantity": bid_qty,
            "ask_quantity": ask_qty,
            "observed_at": latest.get("observed_at"),
            "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "snapshot_gap_seconds": round(snapshot_gap_seconds, 1) if snapshot_gap_seconds is not None else None,
            "score_breakdown": breakdown,
            "gate_failures": sorted(set(failures)),
            "risk_note": "Illustrative premium references only; manual decision required. No orders are placed.",
        })

    results.sort(key=lambda item: (
        item["classification"] not in {"HIGH_CONVICTION", "QUALIFIED"},
        -item["score"], item["underlying"], item["expiry"], item["strike"], item["option_type"],
    ))
    evaluated_count = len(results)
    counts = {
        name: sum(1 for item in results if item["classification"] == name)
        for name in ("HIGH_CONVICTION", "QUALIFIED", "WATCH", "REJECT")
    }
    results = results[:max(1, min(max_candidates, 500))]
    for rank, signal in enumerate(results, start=1):
        signal["rank"] = rank
    return {
        "methodology": "AIR QOC · underlying leads → premium/volume/OI confirm → liquidity and OTM gates",
        "mode": mode,
        "source": "normalized broker option-chain snapshots",
        "as_of": current_time.isoformat(),
        "freshness_max_seconds": max_age,
        "observations_received": len(observations),
        "contracts_evaluated": evaluated_count,
        "signals_returned": len(results),
        "counts": counts,
        "signals": results,
        "disclosure": (
            "Qualification requires two distinct same-session snapshots. Stale data, missing "
            "evidence, failed directional confirmation, non-increasing premium/volume/OI, "
            "poor two-sided liquidity, or OTM distance outside 0.05–5% is rejected. "
            "Scores are research filters, not probability or guaranteed returns."
        ),
    }


def backtest_option_observations(
    observations: list[dict[str, Any]],
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    stop_loss_pct: float = 30.0,
    session_cutoff: str = "15:20",
) -> dict[str, Any]:
    """Replay first qualified contract/session entries using later same-session snapshots.

    This is a sparse-snapshot research replay, not a tick-accurate fill simulation.
    """
    from datetime import time as clock_time

    start_day = datetime.fromisoformat(from_date).date() if from_date else None
    end_day = datetime.fromisoformat(to_date).date() if to_date else None
    cutoff = clock_time.fromisoformat(session_cutoff)
    grouped: dict[tuple[str, str, str, str, Any], list[dict[str, Any]]] = {}
    for row in observations:
        observed = _time(row.get("observed_at"))
        if observed is None:
            continue
        if start_day and observed.date() < start_day:
            continue
        if end_day and observed.date() > end_day:
            continue
        key = (
            str(row.get("underlying_scrip") or ""),
            str(row.get("expiry") or ""),
            str(row.get("strike") or ""),
            str(row.get("option_type") or "").upper(),
            observed.date(),
        )
        grouped.setdefault(key, []).append(row)

    trades: list[dict[str, Any]] = []
    for (underlying, expiry, strike, option_type, session_date), samples in grouped.items():
        samples.sort(key=lambda item: _time(item.get("observed_at")) or datetime.min.replace(tzinfo=IST))
        for index in range(1, len(samples) - 1):
            entry_row = samples[index]
            entry_time = _time(entry_row.get("observed_at"))
            entry_premium = _num(entry_row.get("last_price"))
            if entry_time is None or entry_time.timetz().replace(tzinfo=None) > cutoff or entry_premium is None or entry_premium <= 0:
                continue
            scored = qualify_option_observations(
                [samples[index - 1], entry_row], mode="POST_MARKET", now=entry_time,
                max_candidates=1,
            )
            if not scored["signals"]:
                continue
            signal = scored["signals"][0]
            if signal["classification"] not in {"HIGH_CONVICTION", "QUALIFIED"}:
                continue

            forward = []
            for row in samples[index + 1:]:
                stamp = _time(row.get("observed_at"))
                price = _num(row.get("last_price"))
                if stamp is None or stamp.date() != session_date or stamp.timetz().replace(tzinfo=None) > cutoff:
                    continue
                if price is not None and price > 0:
                    forward.append((stamp, row, price))
            if not forward:
                continue

            stop_price = entry_premium * (1.0 - stop_loss_pct / 100.0)
            stop_hit = next((position for position, item in enumerate(forward) if item[2] <= stop_price), None)
            path = forward[:stop_hit + 1] if stop_hit is not None else forward
            exit_time, exit_row, exit_premium = path[-1]
            path_prices = [item[2] for item in path]
            return_pct = (exit_premium - entry_premium) / entry_premium * 100.0
            trades.append({
                "signal_date": session_date.isoformat(),
                "underlying": underlying,
                "option_type": option_type,
                "strike": strike,
                "expiry": expiry,
                "classification": signal["classification"],
                "score": signal["score"],
                "entry_time": entry_time.isoformat(),
                "entry_premium": round(entry_premium, 2),
                "exit_time": exit_time.isoformat(),
                "exit_premium": round(exit_premium, 2),
                "return_pct": round(return_pct, 2),
                "exit_reason": "STOP_LOSS_OBSERVED" if stop_hit is not None else "SESSION_CUTOFF",
                "max_favorable_excursion_pct": round((max(path_prices) / entry_premium - 1) * 100, 2),
                "max_adverse_excursion_pct": round((min(path_prices) / entry_premium - 1) * 100, 2),
                "milestones_reached": {
                    "plus_50_percent": any(price >= entry_premium * 1.5 for price in path_prices),
                    "plus_100_percent": any(price >= entry_premium * 2.0 for price in path_prices),
                    "plus_200_percent": any(price >= entry_premium * 3.0 for price in path_prices),
                    "plus_300_percent": any(price >= entry_premium * 4.0 for price in path_prices),
                },
                "holding_minutes": round((exit_time - entry_time).total_seconds() / 60.0, 1),
            })
            break  # first qualified entry per contract and IST session; no re-entry/overnight carry

    trades.sort(key=lambda item: (item["signal_date"], item["entry_time"]), reverse=True)
    returns = [item["return_pct"] for item in trades]
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    wins = sum(1 for value in returns if value > 0)
    summary = {
        "trades": len(trades),
        "wins": wins,
        "losses": sum(1 for value in returns if value < 0),
        "win_rate_pct": round(wins / len(trades) * 100.0, 2) if trades else None,
        "average_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        "total_simple_return_pct": round(sum(returns), 2) if returns else None,
        "profit_factor": round(gains / losses, 3) if losses > 0 else (None if gains == 0 else "no_losses"),
        "best_trade_pct": round(max(returns), 2) if returns else None,
        "worst_trade_pct": round(min(returns), 2) if returns else None,
    }
    return {
        "status": "completed" if trades else "insufficient_qualified_history",
        "method": "first HIGH_CONVICTION/QUALIFIED entry per contract/session; snapshot-based exit replay",
        "session_cutoff": session_cutoff,
        "stop_loss_pct": stop_loss_pct,
        "from_date": from_date,
        "to_date": to_date,
        "summary": summary,
        "trades": trades[:500],
        "disclosure": (
            "Historical replay uses only stored snapshots and first qualifying entries per contract/session. "
            "Stop exits occur at the first observed snapshot at or below the stop reference; otherwise "
            "positions are marked at the last observed snapshot by the session cutoff. Intrabar path, "
            "actual fills, slippage, brokerage, taxes and market impact are unavailable and excluded. "
            "Results are not a calibrated strategy expectancy and must not be treated as live performance."
        ),
    }
