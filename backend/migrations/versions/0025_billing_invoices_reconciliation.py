"""Invoices, tax breakdowns, credit notes, settlements and reconciliation.

Revision ID: 0025_billing_recon
Revises: 0024_payment_webhook_sandbox
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_billing_recon"
down_revision = "0024_payment_webhook_sandbox"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "air_billing_invoices",
        sa.Column("invoice_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("invoice_number", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "invoice_number", name="uq_air_billing_invoice_number"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_billing_invoice_idempotency"),
        sa.UniqueConstraint("tenant_id", "invoice_id", name="uq_air_billing_tenant_invoice"),
        sa.CheckConstraint("subtotal_minor >= 0 AND tax_total_minor >= 0 AND total_minor >= 0", name="ck_air_billing_invoice_amounts"),
        sa.CheckConstraint("total_minor = subtotal_minor + tax_total_minor", name="ck_air_billing_invoice_total"),
        sa.CheckConstraint("status IN ('DRAFT','ISSUED','VOID')", name="ck_air_billing_invoice_status"),
    )
    op.create_table(
        "air_billing_invoice_lines",
        sa.Column("line_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("invoice_id", sa.String(36), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_breakdown", sa.JSON(), nullable=False),
        sa.Column("line_subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("line_tax_minor", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "invoice_id"], ["air_billing_invoices.tenant_id", "air_billing_invoices.invoice_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("quantity > 0 AND unit_amount_minor >= 0 AND line_subtotal_minor >= 0 AND line_tax_minor >= 0", name="ck_air_billing_line_amounts"),
    )
    op.create_table(
        "air_billing_refunds",
        sa.Column("refund_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("invoice_id", sa.String(36), nullable=False),
        sa.Column("credit_note_number", sa.String(64), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id", "invoice_id"], ["air_billing_invoices.tenant_id", "air_billing_invoices.invoice_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_billing_refund_idempotency"),
        sa.UniqueConstraint("tenant_id", "credit_note_number", name="uq_air_billing_credit_note_number"),
        sa.CheckConstraint("amount_minor > 0", name="ck_air_billing_refund_positive"),
    )
    op.create_table(
        "air_billing_settlements",
        sa.Column("settlement_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_reference", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "provider", "provider_reference", name="uq_air_billing_settlement_provider_ref"),
        sa.UniqueConstraint("tenant_id", "settlement_id", name="uq_air_billing_tenant_settlement"),
        sa.CheckConstraint("amount_minor >= 0", name="ck_air_billing_settlement_nonnegative"),
    )
    op.create_table(
        "air_billing_reconciliations",
        sa.Column("reconciliation_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("settlement_id", sa.String(36), nullable=False),
        sa.Column("expected_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("settled_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("difference_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("notes", sa.String(500), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id", "settlement_id"], ["air_billing_settlements.tenant_id", "air_billing_settlements.settlement_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_billing_reconciliation_idempotency"),
        sa.CheckConstraint("expected_amount_minor >= 0 AND settled_amount_minor >= 0", name="ck_air_billing_reconciliation_amounts"),
        sa.CheckConstraint("difference_minor = settled_amount_minor - expected_amount_minor", name="ck_air_billing_reconciliation_difference"),
        sa.CheckConstraint("status IN ('MATCH','MISMATCH')", name="ck_air_billing_reconciliation_status"),
    )
    op.create_table(
        "air_billing_audit_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_billing_audit_idempotency"),
    )
    op.create_index("ix_air_billing_invoice_tenant_created", "air_billing_invoices", ["tenant_id", "created_at"])
    op.create_index("ix_air_billing_audit_entity", "air_billing_audit_events", ["tenant_id", "entity_type", "entity_id", "occurred_at"])
    for table in ("air_billing_invoices", "air_billing_invoice_lines", "air_billing_refunds", "air_billing_settlements", "air_billing_reconciliations", "air_billing_audit_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_tenant_scope ON {table}
            USING (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))""")
    for table in ("air_billing_refunds", "air_billing_settlements", "air_billing_reconciliations", "air_billing_audit_events"):
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON air_billing_invoice_lines FROM PUBLIC")


def downgrade():
    tables = ("air_billing_audit_events", "air_billing_reconciliations", "air_billing_settlements", "air_billing_refunds", "air_billing_invoice_lines", "air_billing_invoices")
    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_air_billing_audit_entity", table_name="air_billing_audit_events")
    op.drop_index("ix_air_billing_invoice_tenant_created", table_name="air_billing_invoices")
    for table in tables:
        op.drop_table(table)
