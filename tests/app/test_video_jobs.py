"""Video job API tests."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from proovy_agent.app import main
from proovy_agent.features.video.jobs import CloudRunVideoJobClient, InMemoryVideoJobRepository
from proovy_agent.features.video.models import VideoJob, VideoJobStatus


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[VideoJob] = []

    async def enqueue(self, job: VideoJob) -> None:
        self.enqueued.append(job)

    async def delete(self, cloud_tasks_name: str) -> None:
        return None


class _FakeArtifactUrlResolver:
    def __init__(self) -> None:
        self.urls: dict[str, str] = {}
        self.requested_keys: list[str] = []

    async def final_video_url(self, artifact_object_key: str) -> str | None:
        self.requested_keys.append(artifact_object_key)
        return self.urls.get(artifact_object_key)


@asynccontextmanager
async def _fake_checkpointer(
    _url: str, *, allow_memory_fallback: bool = True
) -> AsyncIterator[InMemorySaver]:
    yield InMemorySaver()


@pytest.fixture()
def video_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[
    tuple[
        TestClient,
        _FakeQueue,
        CloudRunVideoJobClient,
        _FakeArtifactUrlResolver,
    ]
]:
    async def noop() -> None:
        pass

    queue = _FakeQueue()
    artifact_url_resolver = _FakeArtifactUrlResolver()
    video_client = CloudRunVideoJobClient(InMemoryVideoJobRepository(), queue)

    monkeypatch.setattr(main, "init_daytona_client", noop)
    monkeypatch.setattr(main, "close_daytona_client", noop)
    monkeypatch.setattr(main, "open_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(main, "create_video_job_client", lambda _settings: video_client)
    monkeypatch.setattr(
        main,
        "create_video_artifact_url_resolver",
        lambda _settings: artifact_url_resolver,
    )

    with TestClient(main.create_app()) as client:
        yield client, queue, video_client, artifact_url_resolver


def test_create_video_job_and_get_progress_round_trip(
    video_api: tuple[
        TestClient,
        _FakeQueue,
        CloudRunVideoJobClient,
        _FakeArtifactUrlResolver,
    ],
) -> None:
    """API가 잡 ID를 반환하고 같은 ID로 진행률 조회가 가능하다."""
    client, queue, _video_client, _artifact_url_resolver = video_api

    create_response = client.post(
        "/api/v1/video-jobs",
        json={
            "user_id": "user-1",
            "thread_id": "thread-1",
            "input_snapshot": {"problem_text": "2x + 1 = 7을 풀어라."},
        },
    )

    assert create_response.status_code == 202
    created = create_response.json()
    assert created["status"] == "queued"
    assert created["progress_url"] == f"/api/v1/video-jobs/{created['job_id']}"
    assert created["poll_after_seconds"] == 2
    assert [job.id for job in queue.enqueued] == [created["job_id"]]

    progress_response = client.get(
        f"/api/v1/video-jobs/{created['job_id']}",
        params={"user_id": "user-1"},
    )

    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["job_id"] == created["job_id"]
    assert progress["status"] == "queued"
    assert progress["progress"] == {}
    assert progress["poll_after_seconds"] == 2
    assert progress["can_user_retry"] is False
    assert "artifact_object_key" not in progress
    assert progress["user_diagnostic"] is None


def test_succeeded_progress_uses_signed_url_without_exposing_object_key(
    video_api: tuple[
        TestClient,
        _FakeQueue,
        CloudRunVideoJobClient,
        _FakeArtifactUrlResolver,
    ],
) -> None:
    """성공 job은 signed URL만 노출하고 내부 object key는 숨긴다."""
    client, _queue, video_client, artifact_url_resolver = video_api
    create_response = client.post(
        "/api/v1/video-jobs",
        json={
            "user_id": "user-1",
            "thread_id": "thread-1",
            "input_snapshot": {"problem_text": "2x + 1 = 7을 풀어라."},
        },
    )
    job_id = create_response.json()["job_id"]
    object_key = f"video-jobs/{job_id}/attempts/attempt-1/final.mp4"
    artifact_url_resolver.urls[object_key] = "https://signed.example/video.mp4"
    asyncio.run(
        video_client.finalize(
            job_id,
            status=VideoJobStatus.SUCCEEDED,
            artifact_object_key=object_key,
        )
    )

    progress_response = client.get(
        f"/api/v1/video-jobs/{job_id}",
        params={"user_id": "user-1"},
    )

    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert "artifact_object_key" not in progress
    assert object_key not in progress_response.text
    assert progress["user_diagnostic"]["final_video_url"] == "https://signed.example/video.mp4"
    assert artifact_url_resolver.requested_keys == [object_key]


def test_progress_lookup_is_user_scoped(
    video_api: tuple[
        TestClient,
        _FakeQueue,
        CloudRunVideoJobClient,
        _FakeArtifactUrlResolver,
    ],
) -> None:
    """다른 user_id로는 job progress가 노출되지 않는다."""
    client, _queue, _video_client, _artifact_url_resolver = video_api
    create_response = client.post(
        "/api/v1/video-jobs",
        json={
            "user_id": "user-1",
            "thread_id": "thread-1",
            "input": {"problem_text": "1+1은?"},
        },
    )
    job_id = create_response.json()["job_id"]

    response = client.get(f"/api/v1/video-jobs/{job_id}", params={"user_id": "user-2"})

    assert response.status_code == 404
