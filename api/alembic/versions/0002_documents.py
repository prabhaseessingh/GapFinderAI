"""documents and chunks

Revision ID: 0002_phase1
Revises: 0001_phase0
"""

from alembic import op

revision = "0002_phase1"
down_revision = "0001_phase0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS documents (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      student_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      material_role text NOT NULL CHECK (material_role IN ('syllabus','textbook','notes','past_paper')),
      filename varchar(255) NOT NULL, storage_key text NOT NULL UNIQUE, mime_type text NOT NULL,
      byte_size bigint NOT NULL CHECK (byte_size > 0 AND byte_size <= 52428800), checksum_sha256 char(64) NOT NULL,
      version integer NOT NULL DEFAULT 1, state text NOT NULL DEFAULT 'uploaded', failure_code text,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (workspace_id, checksum_sha256, version)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, text_content text NOT NULL,
      source_language text NOT NULL, heading_path text[] NOT NULL DEFAULT '{}', page_start integer, page_end integer,
      char_start integer NOT NULL, char_end integer NOT NULL, content_hash char(64) NOT NULL,
      embedding vector(384), embedding_model text, created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(document_id, content_hash)
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS documents_workspace_state_idx ON documents(workspace_id, state)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS chunks_workspace_idx ON chunks(workspace_id)")


def downgrade() -> None:
    op.execute("DROP TABLE chunks")
    op.execute("DROP TABLE documents")
