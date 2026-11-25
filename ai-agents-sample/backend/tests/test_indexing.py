import pytest

from support_demo.config import settings
from support_demo.seed import index_policies

pytestmark = pytest.mark.integration


async def test_unchanged_chunks_are_not_embedded_again(database, monkeypatch):
    async def unexpected_embed(texts):
        raise AssertionError("Unchanged chunks must not make an embedding request")

    monkeypatch.setattr("support_demo.seed.embed", unexpected_embed)
    await index_policies()


async def test_changed_embedding_dimensions_require_explicit_reindex(database, monkeypatch):
    monkeypatch.setattr(settings(), "embedding_dimensions", 16)
    with pytest.raises(ValueError, match="reindex"):
        await index_policies()
