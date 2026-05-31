"""Video job client and repository tests."""

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
