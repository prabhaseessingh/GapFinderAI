"""create an application profile for each authenticated student

Revision ID: 0003_profile_trigger
Revises: 0002_phase1
"""

from alembic import op

revision = "0003_profile_trigger"
down_revision = "0002_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION public.create_profile_for_auth_user()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    BEGIN
      INSERT INTO public.profiles (id) VALUES (NEW.id) ON CONFLICT (id) DO NOTHING;
      RETURN NEW;
    END;
    $$;
    DO $$
    BEGIN
      IF to_regclass('auth.users') IS NOT NULL THEN
        DROP TRIGGER IF EXISTS on_auth_user_created_profile ON auth.users;
        CREATE TRIGGER on_auth_user_created_profile AFTER INSERT ON auth.users
        FOR EACH ROW EXECUTE PROCEDURE public.create_profile_for_auth_user();
      END IF;
    END;
    $$;
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF to_regclass('auth.users') IS NOT NULL THEN
        DROP TRIGGER IF EXISTS on_auth_user_created_profile ON auth.users;
      END IF;
    END; $$;
    """)
    op.execute("DROP FUNCTION IF EXISTS public.create_profile_for_auth_user")
