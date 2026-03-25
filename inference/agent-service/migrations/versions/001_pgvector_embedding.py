"""Pgvector: migrate playbook_bullets.embedding from JSONB to vector(384) with HNSW index.

Revision ID: 001
Revises: 
Create Date: 2025-01-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Drop old JSONB embedding column
    op.drop_column("playbook_bullets", "embedding")

    # 3. Add new vector(384) column
    op.add_column(
        "playbook_bullets",
        sa.Column(
            "embedding",
            sa.Text,  # placeholder — replaced by pgvector type below
            nullable=True,
        ),
    )
    # Cast column type using raw DDL (SQLAlchemy doesn't natively know vector)
    op.execute(
        "ALTER TABLE playbook_bullets ALTER COLUMN embedding TYPE vector(384) "
        "USING NULL"
    )

    # 4. Create HNSW index for cosine-distance ANN queries
    # m=16, ef_construction=64 — good defaults for 384-dim all-MiniLM-L6-v2
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "playbook_bullets_embedding_hnsw_idx "
        "ON playbook_bullets "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS playbook_bullets_embedding_hnsw_idx")
    op.drop_column("playbook_bullets", "embedding")
    op.add_column(
        "playbook_bullets",
        sa.Column(
            "embedding",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=True,
        ),
    )
