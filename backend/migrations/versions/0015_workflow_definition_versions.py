"""Immutable workflow definition snapshots for versioned runs.

Revision ID: 0015_workflow_definition_versions
Revises: 0014_workflow_run_steps
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_workflow_def_versions"
down_revision = "0014_workflow_run_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_workflow_definition_versions",
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("trigger_type", sa.String(16), nullable=False),
        sa.Column("trigger_config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("workflow_spec_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("execution_mode", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("workflow_id", "version",
                                name="pk_air_workflow_definition_versions"),
        sa.CheckConstraint("version >= 1", name="ck_air_workflow_definition_version"),
    )
    op.create_index(
        "ix_air_workflow_definition_versions_created",
        "air_workflow_definition_versions", ["workflow_id", "created_at"],
    )
    op.execute("""
        INSERT INTO air_workflow_definition_versions
            (workflow_id,version,name,description,trigger_type,trigger_config_json,
             workflow_spec_json,execution_mode,created_by,created_at)
        SELECT workflow_id,version,name,description,trigger_type,trigger_config_json,
               workflow_spec_json,execution_mode,created_by,created_at
        FROM air_workflow_definitions
    """)


def downgrade() -> None:
    op.drop_index("ix_air_workflow_definition_versions_created",
                  table_name="air_workflow_definition_versions")
    op.drop_table("air_workflow_definition_versions")
