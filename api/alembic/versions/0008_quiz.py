"""diagnostic quizzes, questions (hidden key/rubric), attempts and responses

Revision ID: 0008_phase3_quiz
Revises: 0007_security_platform
"""

from alembic import op

revision = "0008_phase3_quiz"
down_revision = "0007_security_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE quizzes (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      state varchar(20) NOT NULL DEFAULT 'blueprint_draft'
        CHECK (state IN ('blueprint_draft','generating','ready','generation_failed')),
      question_count integer NOT NULL CHECK (question_count IN (5, 10, 15)),
      locale text NOT NULL,
      timer_mode varchar(10) NOT NULL DEFAULT 'untimed' CHECK (timer_mode IN ('untimed','timed')),
      time_limit_seconds integer CHECK (time_limit_seconds IS NULL OR time_limit_seconds BETWEEN 60 AND 14400),
      blueprint jsonb NOT NULL DEFAULT '{}'::jsonb,
      policy_version varchar(40) NOT NULL,
      failure_code varchar(80),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((timer_mode = 'timed') = (time_limit_seconds IS NOT NULL))
    )""")
    op.execute("CREATE INDEX quizzes_workspace_idx ON quizzes(workspace_id, created_at DESC)")
    op.execute("""
    CREATE TABLE quiz_questions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      quiz_id uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      topic_id uuid REFERENCES topics(id) ON DELETE SET NULL,
      topic_title varchar(160) NOT NULL,
      position integer NOT NULL,
      question_type varchar(20) NOT NULL CHECK (question_type IN ('mcq','true_false','short_answer')),
      cognitive_level varchar(20) NOT NULL CHECK (cognitive_level IN ('recall','understand','apply')),
      prompt text NOT NULL,
      options jsonb,
      correct_answer jsonb NOT NULL,
      rubric jsonb NOT NULL DEFAULT '[]'::jsonb,
      explanation text,
      max_score real NOT NULL CHECK (max_score > 0),
      citations jsonb NOT NULL,
      content_hash char(64) NOT NULL,
      validation_status varchar(20) NOT NULL DEFAULT 'passed' CHECK (validation_status IN ('passed')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (quiz_id, position),
      UNIQUE (quiz_id, content_hash)
    )""")
    op.execute("""
    CREATE TABLE attempts (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      quiz_id uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      state varchar(20) NOT NULL DEFAULT 'in_progress'
        CHECK (state IN ('in_progress','submitted','evaluating','evaluated','evaluation_failed')),
      started_at timestamptz NOT NULL DEFAULT now(),
      deadline_at timestamptz,
      submitted_at timestamptz,
      submit_reason varchar(20) CHECK (submit_reason IS NULL OR submit_reason IN ('student','time_limit')),
      elapsed_seconds integer,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX attempts_quiz_idx ON attempts(quiz_id, created_at DESC)")
    # At most one open attempt per quiz and student.
    op.execute(
        "CREATE UNIQUE INDEX attempts_one_open_idx ON attempts(quiz_id, student_id) WHERE state = 'in_progress'"
    )
    op.execute("""
    CREATE TABLE responses (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      attempt_id uuid NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
      question_id uuid NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      answer jsonb,
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (attempt_id, question_id)
    )""")

    for table in ("quizzes", "quiz_questions", "attempts", "responses"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    owned = "exists (select 1 from public.workspaces w where w.id = workspace_id and w.student_id = auth.uid())"
    op.execute(
        f'CREATE POLICY "quizzes: owner read" ON public.quizzes FOR SELECT TO authenticated USING (student_id = auth.uid() AND {owned})'
    )
    op.execute(
        f'CREATE POLICY "attempts: owner read" ON public.attempts FOR SELECT TO authenticated USING (student_id = auth.uid() AND {owned})'
    )
    op.execute(
        f'CREATE POLICY "responses: owner read" ON public.responses FOR SELECT TO authenticated USING ({owned})'
    )
    # quiz_questions holds the hidden answer key and rubric: RLS on, no client policy, no grant.
    op.execute("GRANT SELECT ON public.quizzes, public.attempts, public.responses TO authenticated")
    op.execute("REVOKE ALL ON public.quiz_questions FROM authenticated, anon")


def downgrade() -> None:
    raise NotImplementedError("Forward-only; repair with a new migration.")
