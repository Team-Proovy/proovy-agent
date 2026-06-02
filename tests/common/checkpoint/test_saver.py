"""checkpointer 팩토리 테스트."""

from langgraph.checkpoint.memory import InMemorySaver
import pytest

from proovy_agent.common.checkpoint.saver import _to_libpq, open_checkpointer


async def test_open_checkpointer_falls_back_to_inmemory_without_url() -> None:
    """database_url이 비어 있고 폴백 허용 시 InMemorySaver로 폴백한다."""
    async with open_checkpointer("", allow_memory_fallback=True) as saver:
        assert isinstance(saver, InMemorySaver)


async def test_open_checkpointer_fail_fast_without_url() -> None:
    """폴백 비허용(prod) + database_url 미설정 시 기동을 중단한다."""
    with pytest.raises(RuntimeError, match="database_url"):
        async with open_checkpointer("", allow_memory_fallback=False):
            pass


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgresql+psycopg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql+psycopg2://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
    ],
)
def test_to_libpq_normalizes_scheme(raw: str, expected: str) -> None:
    assert _to_libpq(raw) == expected
