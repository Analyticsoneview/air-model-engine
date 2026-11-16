"""Introduce shared-schema SaaS tenant registry and PostgreSQL row-level isolation.

Revision ID: 0020_saas_tenant_isolation
Revises: 0019_air_monthly_pd
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_saas_tenant_isolation"
down_revision = "0019_air_monthly_pd"
branch_labels = None
depends_on = None

# Existing customer_id remains the stable user identity. tenant_id is a separate
# immutable partition key so several customer identities can later belong to one
# organisation without rewriting customer-owned data.
_CUSTOMER_TABLES = [
    "air_access_requests",
    "air_device_sessions",
    "air_customer_subscriptions",
    "air_customer_marketing_preferences",
    "air_access_decision_history",
    "air_customer_lifecycle",
    "air_customer_subscription_history",
    "air_marketing_audit",
    "customer_trading_accounts",
    "customer_market_data_access",
    "customer_market_data_selection",
    "broker_credentials",
    "order_ledger",
    "order_ledger_events",
    "air_portfolio_snapshots",
    "model_signals",
    "report_recipients",
    "account_report_runs",
    "air_support_tickets",
    "air_support_ticket_events",
]

_WORKFLOW_TABLES = [
    "air_workflow_definitions",
    "air_workflow_events",
    "air_workflow_outbox",
    "air_workflow_runs",
    "air_workflow_run_steps",
    "air_workflow_definition_versions",
    "air_workflow_audit",
]


def upgrade() -> None:
    op.create_table(
        "air_tenants",
        sa.Column("tenant_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("owner_customer_id", sa.String(128), nullable=False, unique=True),
        sa.Column("plan_code", sa.String(24), nullable=False, server_default="STANDARD"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('PROVISIONING','ACTIVE','SUSPENDED','CLOSED')",
                           name="ck_air_tenants_status"),
        sa.CheckConstraint("plan_code IN ('STANDARD','PAID','ENTERPRISE')",
                           name="ck_air_tenants_plan"),
    )
    op.create_table(
        "air_tenant_members",
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=False, unique=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="OWNER"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tenant_id", "customer_id", name="pk_air_tenant_members"),
        sa.CheckConstraint("role IN ('OWNER','ADMIN','MEMBER','READ_ONLY')", name="ck_air_tenant_member_role"),
        sa.CheckConstraint("status IN ('INVITED','ACTIVE','SUSPENDED','REMOVED')", name="ck_air_tenant_member_status"),
    )
    op.create_index("ix_air_tenant_members_customer", "air_tenant_members", ["customer_id"])
    op.create_index("ix_air_tenant_members_tenant_status", "air_tenant_members", ["tenant_id", "status"])

    # Seed one personal tenant for each existing customer identity. This preserves
    # the current mobile-number identity model and is idempotent for cutover retries.
    op.execute("""
        WITH customer_ids AS (
            SELECT mobile_e164 AS customer_id FROM air_access_requests
            UNION SELECT customer_id FROM air_customer_subscriptions
            UNION SELECT customer_id FROM air_customer_marketing_preferences
            UNION SELECT customer_id FROM air_customer_lifecycle
            UNION SELECT customer_id FROM air_customer_subscription_history
            UNION SELECT customer_id FROM customer_trading_accounts
            UNION SELECT customer_id FROM customer_market_data_access
            UNION SELECT customer_id FROM customer_market_data_selection
            UNION SELECT customer_id FROM broker_credentials
            UNION SELECT customer_id FROM air_portfolio_snapshots
            UNION SELECT customer_id FROM model_signals
            UNION SELECT customer_id FROM report_recipients
            UNION SELECT customer_id FROM account_report_runs
            UNION SELECT customer_id FROM air_support_tickets
            UNION SELECT actor_customer_id FROM air_marketing_audit
            UNION SELECT NULLIF(trigger_config_json::jsonb->>'customer_id','') FROM air_workflow_definitions
            UNION SELECT NULLIF(payload_json::jsonb->>'customer_id','') FROM air_workflow_events
        )
        INSERT INTO air_tenants(tenant_id,name,owner_customer_id,plan_code,status)
        SELECT gen_random_uuid()::text, 'AIR ' || customer_id, customer_id, 'STANDARD', 'ACTIVE'
        FROM customer_ids
        WHERE customer_id IS NOT NULL AND btrim(customer_id) <> ''
        ON CONFLICT(owner_customer_id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO air_tenant_members(tenant_id,customer_id,role,status)
        SELECT tenant_id,owner_customer_id,'OWNER','ACTIVE' FROM air_tenants
        ON CONFLICT(customer_id) DO NOTHING
    """)

    # Add tenant and user identity to operational tables which previously had
    # only broker/account or workflow foreign keys.
    for table in _CUSTOMER_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
    op.add_column("air_device_sessions", sa.Column("customer_id", sa.String(128), nullable=True))
    op.add_column("order_ledger", sa.Column("customer_id", sa.String(128), nullable=True))
    op.add_column("order_ledger_events", sa.Column("customer_id", sa.String(128), nullable=True))
    op.add_column("air_support_ticket_events", sa.Column("customer_id", sa.String(128), nullable=True))
    for table in _WORKFLOW_TABLES:
        op.add_column(table, sa.Column("customer_id", sa.String(128), nullable=True))
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))

    # Backfill tenant partition keys from the existing owner/customer relationship.
    op.execute("""
        UPDATE air_access_requests r SET tenant_id=m.tenant_id
        FROM air_tenant_members m WHERE m.customer_id=r.mobile_e164
    """)
    op.execute("""
        UPDATE air_device_sessions s SET customer_id=r.mobile_e164,tenant_id=r.tenant_id
        FROM air_access_requests r WHERE r.request_id=s.request_id
    """)
    for table in [
        "air_customer_subscriptions", "air_customer_marketing_preferences",
        "air_customer_lifecycle", "air_customer_subscription_history",
        "customer_trading_accounts", "customer_market_data_access",
        "customer_market_data_selection", "broker_credentials",
        "air_portfolio_snapshots", "model_signals", "report_recipients",
        "account_report_runs", "air_support_tickets",
    ]:
        op.execute(f"""
            UPDATE {table} t SET tenant_id=m.tenant_id
            FROM air_tenant_members m WHERE m.customer_id=t.customer_id
        """)
    op.execute("""
        UPDATE air_access_decision_history t SET tenant_id=m.tenant_id
        FROM air_tenant_members m WHERE m.customer_id=t.mobile_e164
    """)
    op.execute("""
        UPDATE air_marketing_audit t SET tenant_id=m.tenant_id
        FROM air_tenant_members m WHERE m.customer_id=t.actor_customer_id
    """)
    op.execute("""
        UPDATE air_support_ticket_events e
        SET customer_id=t.customer_id,tenant_id=t.tenant_id
        FROM air_support_tickets t WHERE t.ticket_id=e.ticket_id
    """)
    op.execute("""
        UPDATE order_ledger l SET customer_id=a.customer_id,tenant_id=m.tenant_id
        FROM customer_trading_accounts a
        JOIN air_tenant_members m ON m.customer_id=a.customer_id
        WHERE lower(a.broker)=lower(l.broker) AND a.account_id=l.account_id
    """)
    op.execute("""
        UPDATE order_ledger_events e
        SET customer_id=l.customer_id,tenant_id=l.tenant_id
        FROM order_ledger l
        WHERE e.broker=l.broker AND e.account_id=l.account_id
          AND e.idempotency_key=l.idempotency_key
    """)

    # Workflow rows inherit tenant scope from their owner field/payload or parent.
    op.execute("""
        UPDATE air_workflow_definitions
        SET customer_id=NULLIF(trigger_config_json::jsonb->>'customer_id','')
    """)
    op.execute("""
        UPDATE air_workflow_definitions w SET tenant_id=m.tenant_id
        FROM air_tenant_members m WHERE m.customer_id=w.customer_id
    """)
    op.execute("""
        UPDATE air_workflow_events
        SET customer_id=NULLIF(payload_json::jsonb->>'customer_id','')
    """)
    op.execute("ALTER TABLE air_workflow_events DROP CONSTRAINT IF EXISTS air_workflow_events_idempotency_key_key")
    op.execute("""
        CREATE UNIQUE INDEX uq_air_workflow_events_tenant_idempotency
        ON air_workflow_events(tenant_id,idempotency_key) WHERE tenant_id IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_air_workflow_events_global_idempotency
        ON air_workflow_events(idempotency_key) WHERE tenant_id IS NULL
    """)
    op.execute("""
        UPDATE air_workflow_events e SET tenant_id=m.tenant_id
        FROM air_tenant_members m WHERE m.customer_id=e.customer_id
    """)
    op.execute("""
        UPDATE air_workflow_outbox o SET customer_id=e.customer_id,tenant_id=e.tenant_id
        FROM air_workflow_events e WHERE e.event_id=o.event_id
    """)
    op.execute("""
        UPDATE air_workflow_runs r SET customer_id=w.customer_id,tenant_id=w.tenant_id
        FROM air_workflow_definitions w WHERE w.workflow_id=r.workflow_id
    """)
    op.execute("""
        UPDATE air_workflow_run_steps s SET customer_id=r.customer_id,tenant_id=r.tenant_id
        FROM air_workflow_runs r WHERE r.run_id=s.run_id
    """)
    op.execute("""
        UPDATE air_workflow_definition_versions v SET customer_id=w.customer_id,tenant_id=w.tenant_id
        FROM air_workflow_definitions w WHERE w.workflow_id=v.workflow_id
    """)
    op.execute("""
        UPDATE air_workflow_audit a SET customer_id=w.customer_id,tenant_id=w.tenant_id
        FROM air_workflow_definitions w WHERE w.workflow_id=a.workflow_id
    """)

    # Index every tenant partition key before enabling row-level security.
    for table in _CUSTOMER_TABLES + _WORKFLOW_TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index("ix_air_tenants_status_created", "air_tenants", ["status", "created_at"])

    op.execute("""
        CREATE OR REPLACE FUNCTION air_is_admin_context()
        RETURNS boolean LANGUAGE sql STABLE AS $$
            SELECT COALESCE(NULLIF(current_setting('air.is_admin', true), '')::boolean, false)
        $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION air_assign_tenant_id()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            active_tenant text;
            row_customer text;
            resolved_tenant text;
        BEGIN
            active_tenant := NULLIF(current_setting('air.tenant_id', true), '');
            row_customer := COALESCE(
                NULLIF(to_jsonb(NEW)->>'customer_id',''),
                NULLIF(to_jsonb(NEW)->>'mobile_e164',''),
                NULLIF(to_jsonb(NEW)->>'actor_customer_id','')
            );
            IF TG_TABLE_NAME='air_device_sessions' AND row_customer IS NULL THEN
                SELECT mobile_e164 INTO row_customer FROM air_access_requests
                WHERE request_id=NEW.request_id LIMIT 1;
                NEW.customer_id := row_customer;
            ELSIF TG_TABLE_NAME='air_support_ticket_events' AND row_customer IS NULL THEN
                SELECT customer_id INTO row_customer FROM air_support_tickets
                WHERE ticket_id=NEW.ticket_id LIMIT 1;
                NEW.customer_id := row_customer;
            ELSIF TG_TABLE_NAME='order_ledger' AND row_customer IS NULL THEN
                SELECT customer_id INTO row_customer FROM customer_trading_accounts
                WHERE lower(broker)=lower(NEW.broker) AND account_id=NEW.account_id LIMIT 1;
                NEW.customer_id := row_customer;
            ELSIF TG_TABLE_NAME='order_ledger_events' AND row_customer IS NULL THEN
                SELECT customer_id INTO row_customer FROM order_ledger
                WHERE lower(broker)=lower(NEW.broker) AND account_id=NEW.account_id
                  AND idempotency_key=NEW.idempotency_key LIMIT 1;
                NEW.customer_id := row_customer;
            ELSIF TG_TABLE_NAME='air_workflow_outbox' AND row_customer IS NULL THEN
                SELECT customer_id INTO row_customer FROM air_workflow_events
                WHERE event_id=NEW.event_id LIMIT 1;
                NEW.customer_id := row_customer;
            ELSIF TG_TABLE_NAME='air_workflow_runs' AND row_customer IS NULL THEN
                SELECT customer_id INTO row_customer FROM air_workflow_definitions
                WHERE workflow_id=NEW.workflow_id LIMIT 1;
                IF row_customer IS NULL THEN
                    SELECT customer_id INTO row_customer FROM air_workflow_events
                    WHERE event_id=NEW.event_id LIMIT 1;
                END IF;
                NEW.customer_id := row_customer;
            ELSIF TG_TABLE_NAME='air_workflow_run_steps' AND row_customer IS NULL THEN
                SELECT customer_id INTO row_customer FROM air_workflow_runs
                WHERE run_id=NEW.run_id LIMIT 1;
                NEW.customer_id := row_customer;
            ELSIF TG_TABLE_NAME IN ('air_workflow_definition_versions','air_workflow_audit')
                  AND row_customer IS NULL THEN
                SELECT customer_id INTO row_customer FROM air_workflow_definitions
                WHERE workflow_id=NEW.workflow_id LIMIT 1;
                NEW.customer_id := row_customer;
            END IF;
            IF NEW.tenant_id IS NULL AND active_tenant IS NOT NULL THEN
                NEW.tenant_id := active_tenant;
            END IF;
            IF NEW.tenant_id IS NULL AND row_customer IS NOT NULL THEN
                SELECT tenant_id INTO NEW.tenant_id
                FROM air_tenant_members
                WHERE customer_id=row_customer AND status='ACTIVE'
                LIMIT 1;
            END IF;
            IF NOT air_is_admin_context() AND active_tenant IS NOT NULL
               AND NEW.tenant_id IS DISTINCT FROM active_tenant THEN
                RAISE EXCEPTION 'AIR tenant context mismatch';
            END IF;
            IF NOT air_is_admin_context() AND active_tenant IS NOT NULL AND row_customer IS NOT NULL THEN
                SELECT tenant_id INTO resolved_tenant FROM air_tenant_members
                WHERE customer_id=row_customer AND status='ACTIVE' LIMIT 1;
                IF resolved_tenant IS DISTINCT FROM active_tenant THEN
                    RAISE EXCEPTION 'AIR customer is not a member of the active tenant';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
    """)

    # Tenant registry visibility: a member can see only their own tenant and
    # membership rows. Admin context is established only after admin JWT validation.
    op.execute("ALTER TABLE air_tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE air_tenants FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY air_tenants_select ON air_tenants FOR SELECT
        USING (air_is_admin_context()
            OR tenant_id=NULLIF(current_setting('air.tenant_id',true),'')
            OR owner_customer_id=NULLIF(current_setting('air.customer_id',true),'')
            OR EXISTS (SELECT 1 FROM air_tenant_members m
                       WHERE m.tenant_id=air_tenants.tenant_id
                         AND m.customer_id=NULLIF(current_setting('air.customer_id',true),'')))
    """)
    op.execute("""
        CREATE POLICY air_tenants_insert ON air_tenants FOR INSERT
        WITH CHECK (air_is_admin_context()
            OR owner_customer_id=NULLIF(current_setting('air.customer_id',true),''))
    """)
    op.execute("""
        CREATE POLICY air_tenants_admin_update ON air_tenants FOR UPDATE
        USING (air_is_admin_context()) WITH CHECK (air_is_admin_context())
    """)
    op.execute("""
        CREATE POLICY air_tenants_admin_delete ON air_tenants FOR DELETE
        USING (air_is_admin_context())
    """)
    op.execute("ALTER TABLE air_tenant_members ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE air_tenant_members FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY air_tenant_members_select ON air_tenant_members FOR SELECT
        USING (air_is_admin_context()
            OR tenant_id=NULLIF(current_setting('air.tenant_id',true),'')
            OR customer_id=NULLIF(current_setting('air.customer_id',true),''))
    """)
    op.execute("""
        CREATE POLICY air_tenant_members_insert ON air_tenant_members FOR INSERT
        WITH CHECK (air_is_admin_context()
            OR (customer_id=NULLIF(current_setting('air.customer_id',true),'')
                AND tenant_id=(SELECT tenant_id FROM air_tenants
                               WHERE owner_customer_id=NULLIF(current_setting('air.customer_id',true),''))))
    """)
    op.execute("""
        CREATE POLICY air_tenant_members_admin_update ON air_tenant_members FOR UPDATE
        USING (air_is_admin_context()) WITH CHECK (air_is_admin_context())
    """)
    op.execute("""
        CREATE POLICY air_tenant_members_admin_delete ON air_tenant_members FOR DELETE
        USING (air_is_admin_context())
    """)

    # Customer-owned tables require a matching tenant id for both reads and writes.
    for table in _CUSTOMER_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY air_tenant_scope ON {table}
            USING (air_is_admin_context()
                OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context()
                OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
        """)
        op.execute(f"""
            CREATE TRIGGER trg_{table}_assign_tenant
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION air_assign_tenant_id()
        """)

    # Global/system workflows may have NULL tenant_id; customer workflows and
    # their events, runs, versions, audit and steps remain tenant-isolated.
    for table in _WORKFLOW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY air_tenant_scope ON {table}
            USING (air_is_admin_context()
                OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context()
                OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
        """)
        op.execute(f"""
            CREATE TRIGGER trg_{table}_assign_tenant
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION air_assign_tenant_id()
        """)

    op.execute("ALTER TABLE air_workflow_worker_heartbeats ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE air_workflow_worker_heartbeats FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY air_workflow_heartbeat_admin_only ON air_workflow_worker_heartbeats
        USING (air_is_admin_context()) WITH CHECK (air_is_admin_context())
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS air_workflow_heartbeat_admin_only ON air_workflow_worker_heartbeats")
    op.execute("ALTER TABLE air_workflow_worker_heartbeats DISABLE ROW LEVEL SECURITY")
    for table in _WORKFLOW_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_assign_tenant ON {table}")
        op.execute(f"DROP POLICY IF EXISTS air_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
        op.drop_column(table, "customer_id")
    for table in _CUSTOMER_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_assign_tenant ON {table}")
        op.execute(f"DROP POLICY IF EXISTS air_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
    op.execute("DROP POLICY IF EXISTS air_tenant_members_select ON air_tenant_members")
    op.execute("DROP POLICY IF EXISTS air_tenant_members_insert ON air_tenant_members")
    op.execute("DROP POLICY IF EXISTS air_tenant_members_admin_update ON air_tenant_members")
    op.execute("DROP POLICY IF EXISTS air_tenant_members_admin_delete ON air_tenant_members")
    op.execute("DROP INDEX IF EXISTS uq_air_workflow_events_tenant_idempotency")
    op.execute("DROP INDEX IF EXISTS uq_air_workflow_events_global_idempotency")
    op.execute("ALTER TABLE air_workflow_events ADD CONSTRAINT air_workflow_events_idempotency_key_key UNIQUE (idempotency_key)")
    op.execute("ALTER TABLE air_tenant_members NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE air_tenant_members DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_air_tenant_members_tenant_status", table_name="air_tenant_members")
    op.drop_index("ix_air_tenant_members_customer", table_name="air_tenant_members")
    op.drop_table("air_tenant_members")
    op.execute("DROP POLICY IF EXISTS air_tenants_select ON air_tenants")
    op.execute("DROP POLICY IF EXISTS air_tenants_insert ON air_tenants")
    op.execute("DROP POLICY IF EXISTS air_tenants_admin_update ON air_tenants")
    op.execute("DROP POLICY IF EXISTS air_tenants_admin_delete ON air_tenants")
    op.execute("ALTER TABLE air_tenants DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_air_tenants_status_created", table_name="air_tenants")
    op.drop_table("air_tenants")
    op.execute("DROP FUNCTION IF EXISTS air_assign_tenant_id()")
    op.execute("DROP FUNCTION IF EXISTS air_is_admin_context()")
    op.drop_column("air_device_sessions", "customer_id")
    op.drop_column("order_ledger_events", "customer_id")
    op.drop_column("order_ledger", "customer_id")
    op.drop_column("air_support_ticket_events", "customer_id")
