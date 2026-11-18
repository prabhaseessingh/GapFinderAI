"""hybrid retrieval indexes

Revision ID: 0006_phase2_retrieval_indexes
Revises: 0005_phase2
"""

from alembic import op

revision = "0006_phase2_retrieval_indexes"
down_revision = "0005_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The lexical expression exactly matches retrieve_hybrid_evidence().
    op.execute(
        "CREATE INDEX IF NOT EXISTS chunks_text_search_idx "
        "ON chunks USING GIN (to_tsvector('simple', text_content))"
    )
    # Partial indexing avoids empty vectors and remains cheap while a workspace grows.
    op.execute(
        "CREATE INDEX IF NOT EXISTS chunks_embedding_cosine_idx "
        "ON chunks USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_embedding_cosine_idx")
    op.execute("DROP INDEX IF EXISTS chunks_text_search_idx")
