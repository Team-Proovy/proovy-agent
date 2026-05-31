"""ProovyState schema and checkpoint compatibility tests."""

from typing import Annotated

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from proovy_agent.common.checkpoint.saver import _ALLOWED_MSGPACK_MODULES
from proovy_agent.graph.state import ProovyState, VideoJobRef


def test_state_roundtrips_with_video_and_credit_fields() -> None:
    state = ProovyState(
        user_id="user-1",
        thread_id="thread-1",
        explanation_mode="brief",
        hold_id="hold-1",
        video_jobs=[
            VideoJobRef(
                job_id="job-1",
                status="running",
                progress={"segments_done": 2, "segments_total": 5},
                artifact_url="https://example.test/signed-video-url",
            )
        ],
    )

    payload = state.model_dump(mode="json")
    loaded = ProovyState.model_validate(payload)

    assert loaded.model_dump(mode="json") == payload


def test_state_schema_excludes_dead_and_multiturn_unsafe_fields() -> None:
    assert "reservation_id" not in ProovyState.model_fields
    assert "credit_reserved" not in ProovyState.model_fields
    assert "verified_solution" not in ProovyState.model_fields


def test_checkpoint_serializer_roundtrips_video_job_ref() -> None:
    serializer = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
    jobs = [VideoJobRef(job_id="job-1", status="queued")]

    loaded = serializer.loads_typed(serializer.dumps_typed(jobs))

    assert loaded == jobs


class _OldCheckpointState(BaseModel):
    user_id: str = ""
    thread_id: str = ""
    reservation_id: str = ""
    credit_reserved: float = 0.0
    messages: Annotated[list, add_messages] = Field(default_factory=list)


def _old_checkpoint_graph(checkpointer: InMemorySaver):
    def noop(_state: _OldCheckpointState) -> dict:
        return {}

    builder = StateGraph(_OldCheckpointState)
    builder.add_node("noop", noop)
    builder.add_edge(START, "noop")
    builder.add_edge("noop", END)
    return builder.compile(checkpointer=checkpointer)


def _new_checkpoint_graph(checkpointer: InMemorySaver):
    def append_video_job(state: ProovyState) -> dict:
        assert not hasattr(state, "reservation_id")
        assert not hasattr(state, "credit_reserved")
        return {"video_jobs": [VideoJobRef(job_id="job-1", status="queued")]}

    builder = StateGraph(ProovyState)
    builder.add_node("append_video_job", append_video_job)
    builder.add_edge(START, "append_video_job")
    builder.add_edge("append_video_job", END)
    return builder.compile(checkpointer=checkpointer)


async def test_existing_thread_checkpoint_with_retired_credit_fields_loads() -> None:
    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": "thread-1"}}

    old_graph = _old_checkpoint_graph(checkpointer)
    await old_graph.ainvoke(
        _OldCheckpointState(
            user_id="user-1",
            thread_id="thread-1",
            reservation_id="reservation-old",
            credit_reserved=10.0,
            messages=[HumanMessage(content="old turn")],
        ),
        config=config,
    )

    new_graph = _new_checkpoint_graph(checkpointer)
    final = await new_graph.ainvoke(
        ProovyState(user_id="user-1", thread_id="thread-1"),
        config=config,
    )

    assert "reservation_id" not in final
    assert "credit_reserved" not in final
    assert final.get("hold_id") is None
    assert [message.content for message in final["messages"]] == ["old turn"]
    assert final["video_jobs"] == [VideoJobRef(job_id="job-1", status="queued")]
