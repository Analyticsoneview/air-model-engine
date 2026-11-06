"""Pinned historical case-study cohort for the 27-Oct-2026 expiry.

These 11 contracts were selected in the original AIR QOC/Master study and
validated against the 26-Oct-2026 option bhavcopy (op261026.csv). This is a
historical case-study cohort, not a predictive rule and not the separate
37-pre-expiry/8-expiry-day or 11-longest-hold subsets.
"""
from __future__ import annotations

COHORT_ID = "EXPIRY_2026-10-27_CASE_STUDY_11"
SOURCE_WORKBOOK = "AIR_EXPIRYSCAN_EXPIRED_27Oct2026_11Contracts_DailyDetail.xlsx"
EXPIRY = "2026-10-27"

# Values below are the preserved contract-level summary from CONTRACT_SUMMARY.
# Daily observations are preserved in the source workbook's DAILY_DETAIL sheet.
_CASES = (
    ("ALKEM", "PE", 5300, "2026-10-07", 75.58, 71.801, 73.60, 395.55, 240.00, 221.98, 12),
    ("BPCL", "PE", 320, "2026-09-22", 8.74, 8.303, 8.70, 40.00, 27.95, 24.40, 22),
    ("INDHOTEL", "CE", 720, "2026-10-12", 10.78, 10.241, 10.50, 90.00, 89.70, 92.85, 10),
    ("JIOFIN", "PE", 220, "2026-09-22", 2.004, 1.9038, 2.00, 17.51, 12.16, 12.76, 22),
    ("LTF", "PE", 300, "2026-09-23", 6.40, 6.08, 6.30, 67.75, 59.85, 59.20, 21),
    ("MIDCPNIFTY", "PE", 14350, "2026-09-23", 130.44, 123.918, 125.15, 1240.00, 1106.05, 1129.95, 21),
    ("NIFTY", "PE", 23150, "2026-09-23", 129.90, 123.405, 126.85, 899.60, 353.95, 400.25, 21),
    ("NIFTY", "PE", 23200, "2026-09-23", 140.06, 133.057, 138.30, 951.45, 419.50, 450.25, 21),
    ("TCS", "CE", 2140, "2026-10-12", 34.00, 32.30, 44.50, 406.90, 365.35, 356.90, 10),
    ("TVSMOTOR", "CE", 3600, "2026-10-09", 210.00, 199.50, 210.00, 507.95, 480.95, 486.98, 10),
    ("VMM", "PE", 100, "2026-09-23", 1.12, 1.064, 1.10, 15.55, 12.00, 12.01, 21),
)


def historical_expired_contracts() -> list[dict]:
    """Return the exact 11 preserved historical contracts for MASTER/EXPIRED."""
    rows = []
    for (symbol, option_type, strike, entry_date, entry_price, stop_loss,
         lowest_daily_low, highest_daily_high, last_traded_close,
         expiry_intrinsic, daily_rows) in _CASES:
        rows.append({
            "signal_id": f"{COHORT_ID}:{symbol}:{option_type}:{strike}",
            "classification": "EXPIRED",
            "position_status": "EXPIRED",
            "signal_date": entry_date,
            "entry_date": entry_date,
            "symbol": symbol,
            "instrument_type": "INDEX" if symbol in ("NIFTY", "MIDCPNIFTY") else "STOCK",
            "option_type": option_type,
            "expiry": EXPIRY,
            "strike": strike,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "latest_price": last_traded_close,
            "days_to_expiry": -1,
            "cohort_id": COHORT_ID,
            "evidence": {
                "source": "AIR_QOC_MASTER_AND_2026-10-26_OPTION_BHAVCOPY",
                "source_bhavcopy": "op261026.csv",
                "source_workbook": SOURCE_WORKBOOK,
                "daily_detail_sheet": "DAILY_DETAIL",
                "contract_summary_sheet": "CONTRACT_SUMMARY",
                "daily_rows": daily_rows,
                "lowest_daily_low": lowest_daily_low,
                "highest_daily_high": highest_daily_high,
                "last_traded_close": last_traded_close,
                "expiry_intrinsic": expiry_intrinsic,
                "daily_history_available": True,
                "note": "Historical selected case-study contract; not a live signal or predictive filter.",
            },
        })
    return rows
