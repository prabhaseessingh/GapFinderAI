"""profile time zone (fair-use reset), grounded explanations, generated assets
(cached voice audio, AI illustrations, source-figure pointers) and a private assets bucket.

Revision ID: 0010_phase5_explain
Revises: 0009_phase4_diagnosis
"""

from alembic import op

revision = "0010_phase5_explain"
down_revision = "0009_phase4_diagnosis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE profiles ADD COLUMN timezone text")
    op.execute("""
    CREATE TABLE explanations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      topic_id uuid REFERENCES topics(id) ON DELETE SET NULL,
      question text NOT NULL CHECK (char_length(question) BETWEEN 3 AND 1000),
      locale text NOT NULL,
      origin varchar(12) NOT NULL DEFAULT 'typed' CHECK (origin IN ('typed','voice','topic','report','question')),
      state varchar(14) NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued','running','answered','insufficient','failed')),
      answer text,
      citations jsonb NOT NULL DEFAULT '[]'::jsonb,
      next_action varchar(20),
      failure_code varchar(80),
      prompt_version varchar(40),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "CREATE INDEX explanations_workspace_idx ON explanations(workspace_id, created_at DESC)"
    )
    op.execute("""
    CREATE TABLE generated_assets (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      explanation_id uuid NOT NULL REFERENCES explanations(id) ON DELETE CASCADE,
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      kind varchar(14) NOT NULL CHECK (kind IN ('audio','illustration','source_figure')),
      state varchar(14) NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued','rendering','ready','not_eligible','failed')),
      config_hash char(64) NOT NULL,
      storage_path text,
      mime_type text,
      failure_code varchar(80),
      meta jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (explanation_id, kind, config_hash)
    )""")
    owned = "exists (select 1 from public.workspaces w where w.id = workspace_id and w.student_id = auth.uid())"
    for table in ("explanations", "generated_assets"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f'CREATE POLICY "{table}: owner read" ON public.{table} FOR SELECT TO authenticated '
            f"USING (student_id = auth.uid() AND {owned})"
        )
        op.execute(f"GRANT SELECT ON public.{table} TO authenticated")
    # Private bucket for generated audio/images. No student policies: the API hands out
    # short-lived signed URLs after its own ownership check.
    op.execute("""
    DO $storage$
    BEGIN
      IF to_regclass('storage.buckets') IS NULL THEN RETURN; END IF;
      INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
      VALUES ('workspace-assets', 'workspace-assets', false, 10485760, ARRAY['audio/mpeg','image/jpeg','image/png'])
      ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;
    END
    $storage$""")


def downgrade() -> None:
    raise NotImplementedError("Forward-only; repair with a new migration.")
