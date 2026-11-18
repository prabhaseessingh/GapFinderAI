"""mark demo workspaces (copied from the demo snapshot) so the UI labels them clearly.

Revision ID: 0011_phase6_demo
Revises: 0010_phase5_explain
"""

from alembic import op

revision = "0011_phase6_demo"
down_revision = "0010_phase5_explain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE workspaces ADD COLUMN demo_source varchar(40)")
    # At most one demo copy per student.
    op.execute(
        "CREATE UNIQUE INDEX workspaces_one_demo_idx ON workspaces(student_id) WHERE demo_source IS NOT NULL"
    )


def downgrade() -> None:
    raise NotImplementedError("Forward-only; repair with a new migration.")
