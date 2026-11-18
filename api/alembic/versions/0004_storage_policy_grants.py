"""allow storage policies to check the authenticated workspace owner

Revision ID: 0004_storage_policy_grants
Revises: 0003_profile_trigger
"""

from alembic import op

revision = "0004_storage_policy_grants"
down_revision = "0003_profile_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Supabase provides these roles; a plain local Postgres does not.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') "
        "THEN CREATE ROLE authenticated NOLOGIN; END IF; END $$"
    )
    op.execute("GRANT SELECT ON public.workspaces TO authenticated")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public.workspaces FROM authenticated")
