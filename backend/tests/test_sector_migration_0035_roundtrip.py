"""Disposable-PostgreSQL upgrade/downgrade acceptance for sector migration 0035.

This test is deliberately opt-in. The CI integration workflow runs it only against
its disposable PostgreSQL service; never enable it against staging or production.
"""
from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.skipif(
    os.getenv("AIR_RUN_SECTOR_MIGRATION_ROUNDTRIP") != "1",
    reason="requires the explicitly enabled disposable PostgreSQL migration test",
)
def test_sector_migration_0035_upgrade_downgrade_roundtrip():
    database_url = (
        os.getenv("AIR_CUSTOMER_DATABASE_URL")
        or os.getenv("AIR_DATABASE_URL")
    )
    assert database_url, "A disposable PostgreSQL URL is required"
    config = Config("alembic.ini")
    engine = create_engine(database_url)
    symbol = "AIR_MIGRATION_PREFLIGHT_0035"

    try:
        # Start from the parent revision, then create a row using only legacy columns.
        command.downgrade(config, "0034_market_reference_history")
        with engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO market_equity_sector_history
                        (exchange, symbol, sector, effective_from, source)
                    VALUES
                        ('NSE', :symbol, 'Legacy Sector', DATE '2020-01-01',
                         'disposable migration preflight fixture')
                """),
                {"symbol": symbol},
            )

        # Upgrade verifies the new fields, safe legacy default and CHECK constraint.
        command.upgrade(config, "0035_equity_sector_levels")
        columns = {column["name"] for column in inspect(engine).get_columns(
            "market_equity_sector_history"
        )}
        assert {
            "company_name", "macro_sector", "industry", "basic_industry",
            "classification_status",
        }.issubset(columns)

        with engine.connect() as connection:
            row = connection.execute(
                text("""
                    SELECT sector, classification_status
                    FROM market_equity_sector_history
                    WHERE exchange='NSE' AND symbol=:symbol
                      AND effective_from=DATE '2020-01-01'
                """),
                {"symbol": symbol},
            ).mappings().one()
            assert row["sector"] == "Legacy Sector"
            assert row["classification_status"] == "UNVERIFIED"

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("""
                        UPDATE market_equity_sector_history
                        SET classification_status='INVALID'
                        WHERE exchange='NSE' AND symbol=:symbol
                          AND effective_from=DATE '2020-01-01'
                    """),
                    {"symbol": symbol},
                )

        # Downgrade must preserve all pre-existing 0034 business data.
        command.downgrade(config, "0034_market_reference_history")
        columns_after_downgrade = {
            column["name"] for column in inspect(engine).get_columns(
                "market_equity_sector_history"
            )
        }
        assert not {
            "company_name", "macro_sector", "industry", "basic_industry",
            "classification_status",
        }.intersection(columns_after_downgrade)
        with engine.begin() as connection:
            row = connection.execute(
                text("""
                    SELECT sector, source
                    FROM market_equity_sector_history
                    WHERE exchange='NSE' AND symbol=:symbol
                      AND effective_from=DATE '2020-01-01'
                """),
                {"symbol": symbol},
            ).mappings().one()
            assert row["sector"] == "Legacy Sector"
            assert row["source"] == "disposable migration preflight fixture"
            connection.execute(
                text("""
                    DELETE FROM market_equity_sector_history
                    WHERE exchange='NSE' AND symbol=:symbol
                      AND effective_from=DATE '2020-01-01'
                """),
                {"symbol": symbol},
            )

        # Leave the disposable CI database at the repository's current head.
        command.upgrade(config, "head")
        assert "classification_status" in {
            column["name"] for column in inspect(engine).get_columns(
                "market_equity_sector_history"
            )
        }
    finally:
        engine.dispose()
