"""checkpointer 팩토리 테스트."""

from langgraph.checkpoint.memory import InMemorySaver

from proovy_agent.common.checkpoint.saver import open_checkpointer


async def test_open_checkpointer_falls_back_to_inmemory_without_url() -> None:
    """database_url이 비어 있으면 InMemorySaver로 폴백한다."""
    async with open_checkpointer("") as saver:
        assert isinstance(saver, InMemorySaver)
