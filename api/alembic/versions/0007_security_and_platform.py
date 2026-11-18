"""consolidate RLS/grants/storage policies into Alembic; platform + remediation tables

Revision ID: 0007_security_platform
Revises: 0006_phase2_retrieval_indexes

* Supabase-only objects (storage bucket/policies) are guarded so the same migration runs on the
  local Docker Postgres, where 0001 created a stub ``auth`` schema. Locally we also create the
  ``auth.uid()`` function and the ``anon``/``authenticated`` roles Supabase normally provides, so
  RLS policies are identical and testable.
* Every application table has RLS enabled. Writes happen only through FastAPI (table owner);
  ``authenticated`` receives SELECT so RLS is the effective read guard (defense in depth).
"""

from alembic import op

revision = "0007_security_platform"
down_revision = "0006_phase2_retrieval_indexes"
branch_labels = None
depends_on = None

OWNED_BY_WORKSPACE = (
    "exists (select 1 from public.workspaces w where w.id = {col} and w.student_id = auth.uid())"
)


def _policy(table: str, name: str, using: str) -> str:
    return (
        f'DROP POLICY IF EXISTS "{name}" ON public.{table};\n'
        f'CREATE POLICY "{name}" ON public.{table} FOR SELECT TO authenticated USING ({using});\n'
    )


def upgrade() -> None:
    # ---- Local parity with Supabase: auth.uid() + roles (no-ops on Supabase) -----------------
    op.execute("""
    DO $local$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
      IF to_regprocedure('auth.uid()') IS NULL THEN
        EXECUTE $fn$
          CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
          'SELECT nullif(current_setting(''request.jwt.claim.sub'', true), '''')::uuid'
        $fn$;
        GRANT USAGE ON SCHEMA auth TO authenticated, anon;
      END IF;
    END;
    $local$;
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO authenticated")

    # ---- Remediation: chunk identity is its position, not its text ------------------
    op.execute("ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_document_id_content_hash_key")
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_index integer")
    op.execute("""
    UPDATE chunks c SET chunk_index = ranked.idx FROM (
      SELECT id, row_number() OVER (PARTITION BY document_id ORDER BY page_start NULLS FIRST, char_start, id) - 1 AS idx
      FROM chunks) ranked
    WHERE ranked.id = c.id AND c.chunk_index IS NULL
    """)
    op.execute("ALTER TABLE chunks ALTER COLUMN chunk_index SET NOT NULL")
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chunks_document_index_key') "
        "THEN ALTER TABLE chunks ADD CONSTRAINT chunks_document_index_key UNIQUE (document_id, chunk_index); END IF; END $$"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_attempts integer NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count integer")
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT documents_state_check CHECK (state IN "
        "('uploaded','scanning','extracting','chunking','embedding','mapping','ready','failed'))"
    )

    # ---- Remediation: deterministic importance + segmentation + translation cache ----
    op.execute(
        "ALTER TABLE topics ADD COLUMN IF NOT EXISTS importance_source varchar(20) NOT NULL DEFAULT 'default'"
    )
    op.execute(
        "ALTER TABLE topics ADD COLUMN IF NOT EXISTS importance_basis jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE topics ADD CONSTRAINT topics_importance_source_check "
        "CHECK (importance_source IN ('default','past_papers','student'))"
    )
    # Citations display the exact validated quote, not the whole chunk.
    op.execute("ALTER TABLE topic_chunk_links ADD COLUMN IF NOT EXISTS quote text")
    # Past-paper evidence now lives in past_paper_questions/past_paper_question_topics.
    op.execute("DELETE FROM topic_chunk_links WHERE method = 'past_paper'")
    # LLM-chosen importance is not authoritative: reset non-student values.
    op.execute(
        "UPDATE topics SET importance = 3, importance_source = 'default' WHERE importance_source <> 'student'"
    )
    op.execute("""
    CREATE TABLE IF NOT EXISTS past_paper_questions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
      document_version integer NOT NULL,
      chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
      position integer NOT NULL,
      question_label varchar(40),
      question_text text NOT NULL,
      page integer,
      marks real CHECK (marks IS NULL OR marks > 0),
      year integer CHECK (year IS NULL OR year BETWEEN 1900 AND 2200),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (document_id, document_version, position)
    )""")
    op.execute("""
    CREATE TABLE IF NOT EXISTS past_paper_question_topics (
      question_id uuid NOT NULL REFERENCES past_paper_questions(id) ON DELETE CASCADE,
      topic_id uuid NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
      method varchar(20) NOT NULL DEFAULT 'model' CHECK (method IN ('model','student')),
      PRIMARY KEY (question_id, topic_id)
    )""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS past_paper_questions_workspace_idx ON past_paper_questions(workspace_id)"
    )
    op.execute("""
    CREATE TABLE IF NOT EXISTS citation_translations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
      quote_hash char(64) NOT NULL,
      target_locale text NOT NULL,
      translated_text text NOT NULL,
      model text NOT NULL,
      prompt_version text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (chunk_id, quote_hash, target_locale)
    )""")

    # ---- Platform: AI runs, job runs, audit events ---------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS ai_runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      student_id uuid REFERENCES profiles(id) ON DELETE CASCADE,
      workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
      operation varchar(60) NOT NULL, provider varchar(30) NOT NULL, model text,
      prompt_version varchar(40) NOT NULL, evidence_ids uuid[] NOT NULL DEFAULT '{}',
      outcome varchar(30) NOT NULL, error_code varchar(80), latency_ms integer,
      usage jsonb NOT NULL DEFAULT '{}'::jsonb, correlation_id varchar(80) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""
    CREATE TABLE IF NOT EXISTS job_runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      student_id uuid REFERENCES profiles(id) ON DELETE CASCADE,
      workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
      task_name varchar(80) NOT NULL, idempotency_key text NOT NULL,
      state varchar(20) NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','succeeded','failed')),
      attempts integer NOT NULL DEFAULT 0, error_code varchar(80), result jsonb NOT NULL DEFAULT '{}'::jsonb,
      correlation_id varchar(80) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (task_name, idempotency_key)
    )""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS job_runs_workspace_idx ON job_runs(workspace_id, task_name, updated_at DESC)"
    )
    op.execute("""
    CREATE TABLE IF NOT EXISTS audit_events (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      student_id uuid, workspace_id uuid,
      action varchar(60) NOT NULL, resource_type varchar(40) NOT NULL, resource_id uuid,
      correlation_id varchar(80) NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    )""")

    # ---- RLS on every table ------------------------------------------------------------------
    tables = [
        "alembic_version",
        "profiles",
        "workspaces",
        "documents",
        "chunks",
        "topics",
        "topic_chunk_links",
        "past_paper_questions",
        "past_paper_question_topics",
        "citation_translations",
        "ai_runs",
        "job_runs",
        "audit_events",
    ]
    for table in tables:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    # Drop the legacy FOR ALL policies created by the hand-applied SQL files: writes are API-only.
    for table, name in [
        ("profiles", "profile owner access"),
        ("workspaces", "workspace owner access"),
        ("documents", "document owner access"),
        ("chunks", "chunk owner read"),
        ("topics", "topic owner access"),
        ("topic_chunk_links", "topic link owner read"),
    ]:
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON public.{table}')
    sql = ""
    sql += _policy("profiles", "profiles: owner read", "id = auth.uid()")
    sql += _policy("workspaces", "workspaces: owner read", "student_id = auth.uid()")
    sql += _policy(
        "documents",
        "documents: owner read",
        "student_id = auth.uid() AND " + OWNED_BY_WORKSPACE.format(col="workspace_id"),
    )
    sql += _policy("chunks", "chunks: owner read", OWNED_BY_WORKSPACE.format(col="workspace_id"))
    sql += _policy("topics", "topics: owner read", OWNED_BY_WORKSPACE.format(col="workspace_id"))
    sql += _policy(
        "topic_chunk_links",
        "topic links: owner read",
        "exists (select 1 from public.topics t join public.workspaces w on w.id = t.workspace_id "
        "where t.id = topic_id and w.student_id = auth.uid())",
    )
    sql += _policy(
        "past_paper_questions",
        "past paper questions: owner read",
        OWNED_BY_WORKSPACE.format(col="workspace_id"),
    )
    sql += _policy(
        "past_paper_question_topics",
        "past paper question topics: owner read",
        "exists (select 1 from public.past_paper_questions q join public.workspaces w on w.id = q.workspace_id "
        "where q.id = question_id and w.student_id = auth.uid())",
    )
    sql += _policy(
        "citation_translations",
        "citation translations: owner read",
        OWNED_BY_WORKSPACE.format(col="workspace_id"),
    )
    sql += _policy("job_runs", "job runs: owner read", "student_id = auth.uid()")
    # ai_runs / audit_events / alembic_version: RLS on, no policy -> invisible to clients.
    op.execute(sql)
    op.execute(
        "GRANT SELECT ON public.profiles, public.workspaces, public.documents, public.chunks, "
        "public.topics, public.topic_chunk_links, public.past_paper_questions, "
        "public.past_paper_question_topics, public.citation_translations, public.job_runs TO authenticated"
    )
    op.execute(
        "REVOKE ALL ON public.alembic_version, public.ai_runs, public.audit_events FROM authenticated, anon"
    )

    # ---- Supabase Storage: private bucket + owner policies (skipped when storage is absent) ---
    op.execute("""
    DO $storage$
    BEGIN
      IF to_regclass('storage.buckets') IS NULL THEN RETURN; END IF;
      INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
      VALUES ('workspace-materials', 'workspace-materials', false, 52428800,
              ARRAY['application/pdf','text/plain','application/vnd.openxmlformats-officedocument.wordprocessingml.document'])
      ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;
      DROP POLICY IF EXISTS "students read own workspace material" ON storage.objects;
      CREATE POLICY "students read own workspace material" ON storage.objects FOR SELECT TO authenticated
        USING (bucket_id = 'workspace-materials' AND EXISTS (SELECT 1 FROM public.workspaces w
               WHERE w.id::text = (storage.foldername(name))[2] AND w.student_id = auth.uid()));
      DROP POLICY IF EXISTS "students upload own workspace material" ON storage.objects;
      CREATE POLICY "students upload own workspace material" ON storage.objects FOR INSERT TO authenticated
        WITH CHECK (bucket_id = 'workspace-materials' AND EXISTS (SELECT 1 FROM public.workspaces w
               WHERE w.id::text = (storage.foldername(name))[2] AND w.student_id = auth.uid()));
      -- Deletion is server-side only (service role), so students cannot erase evidence behind a report.
      DROP POLICY IF EXISTS "students delete own workspace material" ON storage.objects;
    END;
    $storage$;
    """)


def downgrade() -> None:
    raise NotImplementedError("Security migrations are forward-only; repair with a new migration.")
