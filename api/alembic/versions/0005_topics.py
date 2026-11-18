"""topics and cited proposal links

Revision ID: 0005_phase2
Revises: 0004_storage_policy_grants
"""

from alembic import op

revision = "0005_phase2"
down_revision = "0004_storage_policy_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE topics (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      parent_id uuid REFERENCES topics(id) ON DELETE CASCADE,
      title varchar(160) NOT NULL CHECK (length(trim(title)) > 0),
      status varchar(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
      importance integer NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
      position integer NOT NULL DEFAULT 0,
      origin varchar(20) NOT NULL DEFAULT 'proposal' CHECK (origin IN ('proposal', 'manual')),
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
    )
    """)
    op.execute("""
    CREATE TABLE topic_chunk_links (
      topic_id uuid NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
      chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
      confidence real NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
      method varchar(20) NOT NULL DEFAULT 'proposal', manual_override boolean NOT NULL DEFAULT false,
      PRIMARY KEY(topic_id, chunk_id)
    )
    """)
    op.execute("CREATE INDEX topics_workspace_position_idx ON topics(workspace_id, position)")
    op.execute("CREATE INDEX topic_chunk_links_chunk_idx ON topic_chunk_links(chunk_id)")


def downgrade() -> None:
    op.execute("DROP TABLE topic_chunk_links")
    op.execute("DROP TABLE topics")
