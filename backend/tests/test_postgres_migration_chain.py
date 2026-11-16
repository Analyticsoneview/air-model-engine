"""Guard the ordered PostgreSQL migration history used by AIR deployments."""

from alembic.config import Config
from alembic.script import ScriptDirectory


EXPECTED_CHAIN = [
    "0001_admin_auth_schema",
    "0002_customer_access_schema",
    "0003_broker_stores",
    "0004_qoc_observations",
    "0005_market_instrument_directory",
    "0006_market_data_source_registry",
    "0007_execution_order_stores",
    "0008_customer_access_decisions",
    "0009_customer_lifecycle",
    "0010_portfolio_risk_foundation",
    "0011_admin_support_center",
    "0012_workflow_engine_foundation",
    "0013_workflow_run_ledger",
    "0014_workflow_run_steps",
    "0015_workflow_def_versions",
    "0016_workflow_audit_calendar",
    "0017_workflow_runtime_heartbeat",
    "0018_workflow_run_leases",
    "0019_air_monthly_pd",
    "0020_saas_tenant_isolation",
    "0021_tenant_object_storage",
    "0022_commercial_contract_ledger",
]


def test_postgresql_migrations_have_one_expected_head_and_linear_history():
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [EXPECTED_CHAIN[-1]]

    revision = script.get_revision(EXPECTED_CHAIN[-1])
    actual_reverse = []
    while revision is not None:
        actual_reverse.append(revision.revision)
        if revision.down_revision is None:
            break
        assert isinstance(revision.down_revision, str), (
            "AIR PostgreSQL migrations must remain a single linear chain"
        )
        revision = script.get_revision(revision.down_revision)

    assert list(reversed(actual_reverse)) == EXPECTED_CHAIN
