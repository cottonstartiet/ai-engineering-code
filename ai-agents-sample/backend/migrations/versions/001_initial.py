"""Initial schema; vector dimensions are established and checked by the indexer."""

from alembic import op
from sqlalchemy import text

from support_demo.db import Base

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind)
    bind.execute(
        text(
            "CREATE INDEX policies_text_search ON policies USING gin(to_tsvector('english', text))"
        )
    )


def downgrade():
    Base.metadata.drop_all(op.get_bind())
