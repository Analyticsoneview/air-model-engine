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
    current_time = (now or datetime.now(IST)).astimezone(IST)
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

        if previous is None:
            failures.append("SECOND_OBSERVATION_REQUIRED")

        spot = _num(latest.get("underlying_price"))
        prior_spot = _num(previous.get("underlying_price")) if previous else None
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
        prior_premium = _num(previous.get("last_price")) if previous else None
        premium_change = _pct_change(premium, prior_premium)
        if premium_change is not None and premium_change >= 2.0:
            premium_score = 20 if premium_change >= 10 else 15 if premium_change >= 5 else 10
            breakdown["premium_acceleration"] = premium_score
            score += premium_score
        else:
            failures.append("PREMIUM_NOT_ACCELERATING")

        volume = _int(latest.get("volume"))
        prior_volume = _int(previous.get("volume")) if previous else None
        volume_delta = volume - prior_volume if volume is not None and prior_volume is not None else None
        if volume_delta is not None and volume_delta > 0:
            volume_score = 15 if volume_delta >= 500 else 10 if volume_delta >= 100 else 5
            breakdown["volume_confirmation"] = volume_score
            score += volume_score
        else:
            failures.append("VOLUME_NOT_INCREASING")

        oi = _int(latest.get("open_interest"))
        prior_oi = _int(previous.get("open_interest")) if previous else None
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
