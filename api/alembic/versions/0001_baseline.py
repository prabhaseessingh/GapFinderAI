"""baseline

Revision ID: 0001_phase0
Revises:
"""

from alembic import op

revision = "0001_phase0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Supabase owns auth.users. A local-only stub lets the identical schema run in Docker.
    op.execute("""
    DO $local_auth$
    BEGIN
      IF to_regnamespace('auth') IS NULL THEN
        CREATE SCHEMA auth;
        CREATE TABLE auth.users (id uuid PRIMARY KEY);
      END IF;
    END;
    $local_auth$;
    """)
    op.execute(
        "CREATE TABLE IF NOT EXISTS profiles (id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, display_name text, selected_locale text NOT NULL DEFAULT 'en', privacy_accepted_at timestamptz, privacy_policy_version text, created_at timestamptz NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS workspaces (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, title varchar(120) NOT NULL CHECK (length(trim(title)) > 0), selected_locale text NOT NULL DEFAULT 'en', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())"
    )
    op.execute("CREATE INDEX IF NOT EXISTS workspaces_student_id_idx ON workspaces(student_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workspaces")
    op.execute("DROP TABLE IF EXISTS profiles")
