"""response evaluation, append-only gap reports/mastery snapshots, study preferences,
immutable revision plans and sessions, session completions, quiz kind (diagnostic | retest)

Revision ID: 0009_phase4_diagnosis
Revises: 0008_phase3_quiz
"""

from alembic import op

revision = "0009_phase4_diagnosis"
down_revision = "0008_phase3_quiz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE quizzes ADD COLUMN kind varchar(12) NOT NULL DEFAULT 'diagnostic' CHECK (kind IN ('diagnostic','retest'))"
    )
    op.execute("ALTER TABLE attempts ADD COLUMN failure_code varchar(80)")
    for column in (
        "score real",
        "max_score real",
        "verdict varchar(30) CHECK (verdict IS NULL OR verdict IN ('correct','partial','incorrect','unanswered','insufficient_evidence'))",
        "evaluator varchar(20) CHECK (evaluator IS NULL OR evaluator IN ('deterministic','groq'))",
        "evaluation jsonb",
        "confidence real CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))",
        "evaluated_at timestamptz",
    ):
        op.execute(f"ALTER TABLE responses ADD COLUMN {column}")
    op.execute("""
    CREATE TABLE gap_reports (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      attempt_id uuid REFERENCES attempts(id) ON DELETE SET NULL,
      version integer NOT NULL,
      policy_version varchar(40) NOT NULL,
      summary jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (workspace_id, version)
    )""")
    op.execute("""
    CREATE TABLE topic_mastery_snapshots (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      report_id uuid NOT NULL REFERENCES gap_reports(id) ON DELETE CASCADE,
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      topic_id uuid REFERENCES topics(id) ON DELETE SET NULL,
      topic_title varchar(160) NOT NULL,
      position integer NOT NULL,
      label varchar(20) NOT NULL CHECK (label IN ('weak','medium','strong','limited_evidence')),
      mastery real, confidence real NOT NULL, priority real NOT NULL, importance integer NOT NULL,
      evaluated_questions integer NOT NULL,
      facts jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "CREATE INDEX topic_mastery_snapshots_report_idx ON topic_mastery_snapshots(report_id)"
    )
    op.execute("""
    CREATE TABLE study_preferences (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      exam_date date NOT NULL,
      minutes_per_day integer NOT NULL CHECK (minutes_per_day BETWEEN 1 AND 1440),
      available_weekdays text[] NOT NULL CHECK (cardinality(available_weekdays) > 0),
      timezone text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""
    CREATE TABLE revision_plans (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      report_id uuid NOT NULL REFERENCES gap_reports(id) ON DELETE CASCADE,
      preferences_id uuid NOT NULL REFERENCES study_preferences(id) ON DELETE CASCADE,
      version integer NOT NULL,
      status varchar(12) NOT NULL CHECK (status IN ('feasible','shortfall')),
      demand_minutes integer NOT NULL, scheduled_minutes integer NOT NULL, available_minutes integer NOT NULL,
      shortfall jsonb NOT NULL DEFAULT '[]'::jsonb,
      policy_version varchar(40) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (workspace_id, version)
    )""")
    op.execute("""
    CREATE TABLE revision_sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      plan_id uuid NOT NULL REFERENCES revision_plans(id) ON DELETE CASCADE,
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      day date NOT NULL, sequence integer NOT NULL,
      topic_id uuid REFERENCES topics(id) ON DELETE SET NULL,
      topic_title varchar(160), focus text[] NOT NULL DEFAULT '{}',
      activity varchar(10) NOT NULL CHECK (activity IN ('study','review','retest')),
      minutes integer NOT NULL CHECK (minutes > 0),
      UNIQUE (plan_id, day, sequence)
    )""")
    op.execute("""
    CREATE TABLE session_completions (
      session_id uuid PRIMARY KEY REFERENCES revision_sessions(id) ON DELETE CASCADE,
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      completed_at timestamptz NOT NULL DEFAULT now()
    )""")
    owned = "exists (select 1 from public.workspaces w where w.id = workspace_id and w.student_id = auth.uid())"
    for table in (
        "gap_reports",
        "topic_mastery_snapshots",
        "study_preferences",
        "revision_plans",
        "revision_sessions",
        "session_completions",
    ):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f'CREATE POLICY "{table}: owner read" ON public.{table} FOR SELECT TO authenticated USING ({owned})'
        )
        op.execute(f"GRANT SELECT ON public.{table} TO authenticated")


def downgrade() -> None:
    raise NotImplementedError("Forward-only; repair with a new migration.")
