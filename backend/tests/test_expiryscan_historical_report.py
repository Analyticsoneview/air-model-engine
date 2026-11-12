from datetime import date

import pytest

from app.backtest_api import expiryscan_historical_report
from app.backtest_registry import registered_backtest_strategies


@pytest.mark.asyncio
async def test_expiryscan_october_2026_report_returns_preserved_11_contract_cohort():
    report = await expiryscan_historical_report(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        customer_id="test-customer",
    )
    assert report["strategy"] == "EXPIRYSCAN"
    assert report["contract_count"] == 11
    assert report["daily_observation_count"] == 191
    assert report["data_status"] == "CONTRACT_SUMMARY_VERIFIED_DAILY_DETAIL_PENDING"
    assert all(row["classification"] == "EXPIRED" for row in report["contracts"])
    assert all(row["expected_closing_date"] == "2026-10-26" for row in report["contracts"])
    assert all(row["daily_detail_status"] == "SOURCE_WORKBOOK_NOT_PRESENT_IN_REPOSITORY" for row in report["contracts"])


@pytest.mark.asyncio
async def test_expiryscan_outside_preserved_cohort_period_returns_no_cohort():
    report = await expiryscan_historical_report(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        customer_id="test-customer",
    )
    assert report["contract_count"] == 0
    assert report["data_status"] == "NO_PRESERVED_COHORT_IN_PERIOD"


@pytest.mark.asyncio
async def test_expiryscan_rejects_reversed_date_range():
    with pytest.raises(Exception):
        await expiryscan_historical_report(
            start_date=date(2026, 11, 1),
            end_date=date(2026, 10, 1),
            customer_id="test-customer",
        )


def test_expiryscan_is_available_for_historical_reporting_not_daily_replay():
    item = next(x for x in registered_backtest_strategies() if x["id"] == "EXPIRYSCAN")
    assert item["available_for_historical_report"] is True
    assert item["available_for_daily_backtest"] is False
    assert item["historical_report_mode"] == "PRESERVED_EXPIRY_COHORT_SUMMARY"
