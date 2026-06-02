"""Video job client and repository tests."""

from pydantic import ValidationError
import pytest

from proovy_agent.features.video.jobs import (
    CloudRunVideoJobClient,
    InMemoryVideoJobRepository,
    InvalidRetrySourceError,
    RetryAlreadyUsedError,
)
from proovy_agent.features.video.models import (
    StageName,
    UserErrorCode,
    VideoJob,
    VideoJobInput,
    VideoJobStatus,
)


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[VideoJob] = []
        self.deleted: list[str] = []

    async def enqueue(self, job: VideoJob) -> None:
        self.enqueued.append(job)

    async def delete(self, cloud_tasks_name: str) -> None:
        self.deleted.append(cloud_tasks_name)


class _FailingDeleteQueue(_FakeQueue):
    async def delete(self, cloud_tasks_name: str) -> None:
        self.deleted.append(cloud_tasks_name)
        raise RuntimeError("delete failed")


def _sample_input() -> VideoJobInput:
    return VideoJobInput(problem_text="2x + 1 = 7을 풀어라.")


def _build_client() -> tuple[CloudRunVideoJobClient, _FakeQueue]:
    queue = _FakeQueue()
    return CloudRunVideoJobClient(InMemoryVideoJobRepository(), queue), queue


async def test_video_job_create_and_progress_round_trip() -> None:
    """잡 생성 후 단일 job 조회와 progress write가 round-trip 된다."""
    client, queue = _build_client()

    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    loaded = await client.get_progress(job.id, user_id="user-1")
    updated = await client.update_progress(
        job.id,
        status=VideoJobStatus.RUNNING,
        stage=StageName.RENDER,
        progress={"segments_done": 1, "segments_total": 3},
    )

    assert loaded == job
    assert updated.status is VideoJobStatus.RUNNING
    assert updated.stage is StageName.RENDER
    assert updated.progress == {"segments_done": 1, "segments_total": 3}
    assert updated.started_at is not None
    assert [queued.id for queued in queue.enqueued] == [job.id]


async def test_retry_source_allows_only_one_user_retry() -> None:
    """원본 failed/canceled job당 사용자 재시도는 1회만 허용된다."""
    client, queue = _build_client()
    source = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    failed_source = await client.finalize(
        source.id,
        status=VideoJobStatus.FAILED,
        error_stage=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
    )

    assert await client.can_user_retry(failed_source) is True

    retry = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        retry_source_job_id=source.id,
    )

    assert retry.retry_source_job_id == source.id
    assert retry.input_snapshot == source.input_snapshot
    assert await client.can_user_retry(retry) is False
    assert [queued.id for queued in queue.enqueued] == [source.id, retry.id]

    refreshed_source = await client.get_progress(source.id, user_id="user-1")
    assert refreshed_source is not None
    assert await client.can_user_retry(refreshed_source) is False

    with pytest.raises(RetryAlreadyUsedError):
        await client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            retry_source_job_id=source.id,
        )


async def test_retry_rejects_non_terminal_source() -> None:
    """아직 실패/취소되지 않은 job은 사용자 재시도 원본이 될 수 없다."""
    client, _queue = _build_client()
    source = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    with pytest.raises(InvalidRetrySourceError):
        await client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            retry_source_job_id=source.id,
        )


async def test_terminal_job_ignores_late_progress_write() -> None:
    """Terminal job은 stale worker progress write로 running 상태로 되돌아가지 않는다."""
    client, _queue = _build_client()
    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    failed = await client.finalize(
        job.id,
        status=VideoJobStatus.FAILED,
        error_stage=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
    )

    late_update = await client.update_progress(
        job.id,
        status=VideoJobStatus.RUNNING,
        stage=StageName.RENDER,
        progress={"segments_done": 1, "segments_total": 3},
    )

    assert late_update == failed
    assert late_update.status is VideoJobStatus.FAILED
    assert late_update.progress == {}


async def test_terminal_job_ignores_late_finalize_write() -> None:
    """이미 terminal 상태인 job은 뒤늦은 finalize로 결과가 덮이지 않는다."""
    client, _queue = _build_client()
    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    failed = await client.finalize(
        job.id,
        status=VideoJobStatus.FAILED,
        error_stage=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
    )

    late_finalize = await client.finalize(
        job.id,
        status=VideoJobStatus.SUCCEEDED,
        artifact_object_key="video-jobs/final.mp4",
    )

    assert late_finalize == failed
    assert late_finalize.status is VideoJobStatus.FAILED
    assert late_finalize.artifact_object_key is None


async def test_cancel_returns_persisted_job_when_queue_delete_fails() -> None:
    """Cloud Tasks delete 실패는 이미 저장된 cancel_requested 응답을 막지 않는다."""
    queue = _FailingDeleteQueue()
    client = CloudRunVideoJobClient(InMemoryVideoJobRepository(), queue)
    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    canceled = await client.cancel(job.id)

    assert canceled.cancel_requested is True
    assert canceled.status is VideoJobStatus.QUEUED
    assert queue.deleted == [job.cloud_tasks_name]


async def test_in_memory_repository_returns_defensive_copies() -> None:
    """InMemory repository는 저장 객체 참조를 그대로 외부에 노출하지 않는다."""
    repository = InMemoryVideoJobRepository()
    created = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    created.progress["segments_done"] = 99

    loaded = await repository.get(created.id)
    assert loaded is not None
    assert loaded.progress == {}

    loaded.progress["segments_done"] = 1
    reloaded = await repository.get(created.id)

    assert reloaded is not None
    assert reloaded.progress == {}


async def test_in_memory_repository_validates_progress_updates() -> None:
    """Repository updates는 model_copy가 아닌 Pydantic validation을 거친다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    with pytest.raises(ValidationError, match="progress values must be non-negative"):
        await repository.update_progress(job.id, progress={"segments_done": -1})
