"""Video job API tests."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from proovy_agent.app import main
from proovy_agent.features.video.jobs import CloudRunVideoJobClient, InMemoryVideoJobRepository
from proovy_agent.features.video.models import VideoJob, VideoJobInput, VideoJobStatus


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[VideoJob] = []

    async def enqueue(self, job: VideoJob) -> None:
        self.enqueued.append(job)

    async def delete(self, cloud_tasks_name: str) -> None:
        return None

    async def task_missing(self, cloud_tasks_name: str) -> bool:
        _ = cloud_tasks_name
        return False


class _FakeArtifactUrlResolver:
    def __init__(self) -> None:
        self.urls: dict[str, str] = {}
        self.requested_keys: list[str] = []
        self.should_fail = False

    async def final_video_url(self, artifact_object_key: str) -> str | None:
        self.requested_keys.append(artifact_object_key)
        if self.should_fail:
            raise RuntimeError("signing failed")
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
    """잡 진행률 조회 API가 DB job 상태를 반환한다."""
    client, queue, video_client, _artifact_url_resolver = video_api

    job = asyncio.run(
        video_client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=VideoJobInput(problem_text="2x + 1 = 7을 풀어라."),
        )
    )

    assert [queued.id for queued in queue.enqueued] == [job.id]

    progress_response = client.get(
        f"/api/v1/video-jobs/{job.id}",
        params={"user_id": "user-1"},
    )

    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["job_id"] == job.id
    assert progress["status"] == "queued"
    assert progress["progress"] == {}
    assert progress["poll_after_seconds"] == 2
    assert progress["can_user_retry"] is False
    assert "artifact_object_key" not in progress
    assert progress["user_diagnostic"] is None


def test_create_video_job_endpoint_is_disabled(
    video_api: tuple[TestClient, _FakeQueue, CloudRunVideoJobClient, _FakeArtifactUrlResolver],
) -> None:
    """영상 job 생성은 VideoNode capture 계약을 통해서만 허용한다."""
    client, _queue, _video_client, _artifact_url_resolver = video_api

    response = client.post(
        "/api/v1/video-jobs",
        json={
            "user_id": "user-1",
            "thread_id": "thread-1",
            "input_snapshot": {"problem_text": "2x + 1 = 7을 풀어라."},
        },
    )

    assert response.status_code == 410


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
    job = asyncio.run(
        video_client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=VideoJobInput(problem_text="2x + 1 = 7을 풀어라."),
        )
    )
    job_id = job.id
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


def test_progress_still_returns_when_signed_url_resolver_fails(
    video_api: tuple[
        TestClient,
        _FakeQueue,
        CloudRunVideoJobClient,
        _FakeArtifactUrlResolver,
    ],
) -> None:
    """Signed URL 생성 실패는 hot progress 조회를 500으로 만들지 않는다."""
    client, _queue, video_client, artifact_url_resolver = video_api
    job = asyncio.run(
        video_client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=VideoJobInput(problem_text="2x + 1 = 7을 풀어라."),
        )
    )
    job_id = job.id
    object_key = f"video-jobs/{job_id}/attempts/attempt-1/final.mp4"
    artifact_url_resolver.should_fail = True
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
    assert progress["status"] == "succeeded"
    assert progress["user_diagnostic"] is None
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
    client, _queue, video_client, _artifact_url_resolver = video_api
    job = asyncio.run(
        video_client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=VideoJobInput(problem_text="1+1은?"),
        )
    )

    response = client.get(f"/api/v1/video-jobs/{job.id}", params={"user_id": "user-2"})

    assert response.status_code == 404


def test_cancel_queued_video_job_returns_terminal_status(
    video_api: tuple[
        TestClient,
        _FakeQueue,
        CloudRunVideoJobClient,
        _FakeArtifactUrlResolver,
    ],
) -> None:
    """queued job 취소는 즉시 canceled 상태로 복원된다."""
    client, _queue, video_client, _artifact_url_resolver = video_api
    job = asyncio.run(
        video_client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=VideoJobInput(problem_text="1+1은?"),
        )
    )

    response = client.post(
        f"/api/v1/video-jobs/{job.id}/cancel",
        params={"user_id": "user-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job.id
    assert payload["status"] == "canceled"
    assert payload["can_user_retry"] is True


def test_thread_state_restores_latest_video_job(
    video_api: tuple[
        TestClient,
        _FakeQueue,
        CloudRunVideoJobClient,
        _FakeArtifactUrlResolver,
    ],
) -> None:
    """재접속 시 thread 응답의 video_jobs[-1]로 최신 영상 상태를 복원한다."""
    client, _queue, video_client, _artifact_url_resolver = video_api
    first = asyncio.run(
        video_client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=VideoJobInput(problem_text="1+1은?"),
        )
    )
    latest = asyncio.run(
        video_client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=VideoJobInput(problem_text="2+2는?"),
        )
    )
    asyncio.run(video_client.finalize(first.id, status=VideoJobStatus.FAILED))

    response = client.get("/api/v1/threads/thread-1", params={"user_id": "user-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread_id"] == "thread-1"
    assert [job["job_id"] for job in payload["video_jobs"]] == [latest.id]
    assert payload["video_jobs"][-1]["status"] == "queued"


def test_cancel_running_stale_job_cleans_up_in_same_request(
    video_api: tuple[
        TestClient,
        _FakeQueue,
        CloudRunVideoJobClient,
        _FakeArtifactUrlResolver,
    ],
) -> None:
    """running stale job 취소는 다음 poll을 기다리지 않고 canceled로 정리된다."""
    client, _queue, video_client, _artifact_url_resolver = video_api
    job = asyncio.run(
        video_client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=VideoJobInput(problem_text="1+1은?"),
        )
    )
    repository = video_client._repository
    asyncio.run(
        repository.acquire_lease(
            job.id,
            instance_id="worker-1",
            attempt_id="attempt-1",
            lease_stale_after_seconds=60,
        )
    )
    repository._jobs[job.id] = repository._jobs[job.id].model_copy(
        update={
            "progress_updated_at": datetime.now(UTC) - timedelta(minutes=31),
        }
    )

    response = client.post(
        f"/api/v1/video-jobs/{job.id}/cancel",
        params={"user_id": "user-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "canceled"
    assert payload["can_user_retry"] is True
