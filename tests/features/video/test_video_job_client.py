"""Video job client and repository tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from uuid import uuid4

from google.api_core.exceptions import AlreadyExists, NotFound
from pydantic import ValidationError
import pytest

from proovy_agent.features.video.jobs import (
    CloudRunVideoJobClient,
    CloudTasksVideoTaskQueue,
    InMemoryVideoJobRepository,
    InvalidRetrySourceError,
    PostgresVideoJobRepository,
    RetryAlreadyUsedError,
    VideoCreditCapture,
    VideoJobEnqueueError,
)
from proovy_agent.features.video.models import (
    StageName,
    UserErrorCode,
    VideoJob,
    VideoJobInput,
    VideoJobStatus,
)


class _FakeQueue:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events
        self.enqueued: list[VideoJob] = []
        self.deleted: list[str] = []
        self.missing_tasks: set[str] = set()

    async def enqueue(self, job: VideoJob) -> None:
        if self.events is not None:
            self.events.append("enqueue")
        self.enqueued.append(job)

    async def delete(self, cloud_tasks_name: str) -> None:
        self.deleted.append(cloud_tasks_name)

    async def task_missing(self, cloud_tasks_name: str) -> bool:
        return cloud_tasks_name in self.missing_tasks


class _FailingDeleteQueue(_FakeQueue):
    async def delete(self, cloud_tasks_name: str) -> None:
        self.deleted.append(cloud_tasks_name)
        raise RuntimeError("delete failed")


class _FailingEnqueueQueue(_FakeQueue):
    async def enqueue(self, job: VideoJob) -> None:
        self.enqueued.append(job)
        raise RuntimeError("enqueue failed")


class _FakeCloudTasksClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, object]] = []
        self.deleted: list[str] = []
        self.loaded: list[str] = []
        self.create_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.get_error: Exception | None = None

    def create_task(self, *, parent: str, task: object) -> None:
        if self.create_error is not None:
            raise self.create_error
        self.created.append((parent, task))

    def get_task(self, *, name: str) -> object:
        self.loaded.append(name)
        if self.get_error is not None:
            raise self.get_error
        return object()

    def delete_task(self, *, name: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(name)


class _RecordingRepository(InMemoryVideoJobRepository):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def create(
        self,
        *,
        user_id: str,
        thread_id: str,
        input_snapshot: VideoJobInput | None = None,
        retry_source_job_id: str | None = None,
        job_id: str | None = None,
        credit_capture: VideoCreditCapture | None = None,
    ) -> VideoJob:
        job = await super().create(
            user_id=user_id,
            thread_id=thread_id,
            input_snapshot=input_snapshot,
            retry_source_job_id=retry_source_job_id,
            job_id=job_id,
            credit_capture=credit_capture,
        )
        if credit_capture is not None:
            self.events.append("capture")
        return job


class _FakeCursor:
    async def fetchone(self) -> None:
        return None


class _FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _RecordingConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.params: list[dict[str, object]] = []

    async def __aenter__(self) -> "_RecordingConnection":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def execute(self, query: str, params: dict[str, object]) -> _FakeCursor:
        self.queries.append(query)
        self.params.append(params)
        return _FakeCursor()


class _RecordingPostgresRepository(PostgresVideoJobRepository):
    def __init__(self, job: VideoJob) -> None:
        super().__init__("postgresql://unused")
        self.job = job
        self.conn = _RecordingConnection()

    async def get(self, job_id: str) -> VideoJob | None:
        return self.job if job_id == self.job.id else None

    async def _connect(self) -> _RecordingConnection:
        return self.conn


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


async def test_credit_capture_contract_happens_before_queue_enqueue() -> None:
    """Video 10cr capture is part of repository create before task dispatch."""
    events: list[str] = []
    client = CloudRunVideoJobClient(_RecordingRepository(events), _FakeQueue(events))
    hold_id = uuid4()

    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
        credit_capture=VideoCreditCapture(hold_id=hold_id, amount=Decimal("10")),
    )

    assert job.cloud_tasks_name == f"video-{job.id}"
    assert events == ["capture", "enqueue"]


async def test_enqueue_failure_marks_unleased_job_failed_and_refunded() -> None:
    """A confirmed enqueue miss compensates a pre-dispatch video capture."""
    repository = InMemoryVideoJobRepository()
    client = CloudRunVideoJobClient(repository, _FailingEnqueueQueue())

    with pytest.raises(VideoJobEnqueueError) as exc_info:
        await client.create_and_enqueue(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=_sample_input(),
            credit_capture=VideoCreditCapture(hold_id=uuid4(), amount=Decimal("10")),
        )

    job = await repository.get(exc_info.value.job_id)
    assert job is not None
    assert job.status is VideoJobStatus.FAILED
    assert job.error_stage is StageName.ENQUEUE
    assert job.user_error_code is UserErrorCode.INFRASTRUCTURE_ENQUEUE_FAILED
    assert job.refund_applied_at is not None


async def test_cloud_tasks_queue_creates_named_http_task() -> None:
    """Cloud Tasks adapter sends deterministic task id and worker auth header."""
    cloud_tasks_client = _FakeCloudTasksClient()
    queue = CloudTasksVideoTaskQueue(
        queue_path="projects/p/locations/us-central1/queues/video",
        worker_url="https://worker.example/jobs/run",
        worker_auth_token="secret",
        client=cloud_tasks_client,  # type: ignore[arg-type]
    )
    job = await InMemoryVideoJobRepository().create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
        job_id="job-1",
    )

    await queue.enqueue(job)

    parent, task = cloud_tasks_client.created[0]
    assert parent == "projects/p/locations/us-central1/queues/video"
    assert task.name == "projects/p/locations/us-central1/queues/video/tasks/video-job-1"
    assert task.http_request.url == "https://worker.example/jobs/run"
    assert task.http_request.headers["X-Proovy-Worker-Token"] == "secret"
    assert json.loads(task.http_request.body.decode("utf-8")) == {"job_id": "job-1"}


async def test_cloud_tasks_queue_treats_already_exists_and_not_found_as_idempotent() -> None:
    """Task create/delete retries are idempotent for deterministic task names."""
    cloud_tasks_client = _FakeCloudTasksClient()
    queue = CloudTasksVideoTaskQueue(
        queue_path="projects/p/locations/us-central1/queues/video",
        worker_url="https://worker.example/jobs/run",
        client=cloud_tasks_client,  # type: ignore[arg-type]
    )
    job = await InMemoryVideoJobRepository().create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
        job_id="job-1",
    )

    cloud_tasks_client.create_error = AlreadyExists("exists")
    cloud_tasks_client.delete_error = NotFound("missing")

    await queue.enqueue(job)
    await queue.delete(job.cloud_tasks_name)


async def test_cloud_tasks_queue_reports_task_missing_only_on_not_found() -> None:
    """lazy detection은 get_task NOT_FOUND만 큐 유실로 취급한다."""
    cloud_tasks_client = _FakeCloudTasksClient()
    queue = CloudTasksVideoTaskQueue(
        queue_path="projects/p/locations/us-central1/queues/video",
        worker_url="https://worker.example/jobs/run",
        client=cloud_tasks_client,  # type: ignore[arg-type]
    )

    assert await queue.task_missing("video-job-1") is False

    cloud_tasks_client.get_error = NotFound("missing")

    assert await queue.task_missing("video-job-1") is True


async def test_cloud_tasks_queue_reconciles_ambiguous_create_errors() -> None:
    """create_task 실패가 모호하면 get_task로 확인해 불필요한 환불을 막는다."""
    cloud_tasks_client = _FakeCloudTasksClient()
    queue = CloudTasksVideoTaskQueue(
        queue_path="projects/p/locations/us-central1/queues/video",
        worker_url="https://worker.example/jobs/run",
        client=cloud_tasks_client,  # type: ignore[arg-type]
    )
    job = await InMemoryVideoJobRepository().create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
        job_id="job-1",
    )

    cloud_tasks_client.create_error = RuntimeError("deadline exceeded")

    await queue.enqueue(job)

    assert cloud_tasks_client.loaded == [
        "projects/p/locations/us-central1/queues/video/tasks/video-job-1"
    ]


async def test_cloud_tasks_queue_raises_only_when_task_absence_confirmed() -> None:
    """get_task NOT_FOUND일 때만 enqueue 실패를 확정한다."""
    cloud_tasks_client = _FakeCloudTasksClient()
    queue = CloudTasksVideoTaskQueue(
        queue_path="projects/p/locations/us-central1/queues/video",
        worker_url="https://worker.example/jobs/run",
        client=cloud_tasks_client,  # type: ignore[arg-type]
    )
    job = await InMemoryVideoJobRepository().create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
        job_id="job-1",
    )

    cloud_tasks_client.create_error = RuntimeError("deadline exceeded")
    cloud_tasks_client.get_error = NotFound("missing")

    with pytest.raises(RuntimeError, match="deadline exceeded"):
        await queue.enqueue(job)


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


async def test_cancel_queued_job_marks_terminal_refunded_and_deletes_queue_task() -> None:
    """queued 취소는 API가 terminal+refund를 잡고 task delete는 best-effort로 수행한다."""
    queue = _FailingDeleteQueue()
    client = CloudRunVideoJobClient(InMemoryVideoJobRepository(), queue)
    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    canceled = await client.cancel(job.id)

    assert canceled.cancel_requested is True
    assert canceled.status is VideoJobStatus.CANCELED
    assert canceled.refund_applied_at is not None
    assert queue.deleted == [job.cloud_tasks_name]


async def test_cancel_running_job_only_sets_flag_without_refund_or_queue_delete() -> None:
    """running 취소 요청은 워커가 terminal을 잡을 때까지 환불하지 않는다."""
    repository = InMemoryVideoJobRepository()
    client = CloudRunVideoJobClient(repository, _FakeQueue())
    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    await repository.acquire_lease(
        job.id,
        instance_id="worker-1",
        attempt_id="attempt-1",
        lease_stale_after_seconds=60,
    )

    canceled = await client.cancel(job.id)

    assert canceled.status is VideoJobStatus.RUNNING
    assert canceled.cancel_requested is True
    assert canceled.refund_applied_at is None


async def test_single_lazy_detection_marks_running_stuck_failed_and_refunded() -> None:
    """hot progress lazy detection은 조회 중인 stale running job 1건만 정리한다."""
    repository = InMemoryVideoJobRepository()
    client = CloudRunVideoJobClient(repository, _FakeQueue())
    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    await repository.acquire_lease(
        job.id,
        instance_id="worker-1",
        attempt_id="attempt-1",
        lease_stale_after_seconds=60,
    )
    repository._jobs[job.id] = repository._jobs[job.id].model_copy(
        update={
            "progress_updated_at": datetime.now(UTC) - timedelta(minutes=31),
            "stage": StageName.RENDER,
        }
    )

    cleaned = await client.check_stuck_job(
        job.id,
        user_id="user-1",
        running_stale_after_seconds=1800,
        queued_stale_after_seconds=900,
    )

    assert cleaned is not None
    assert cleaned.status is VideoJobStatus.FAILED
    assert cleaned.error_stage is StageName.RENDER
    assert cleaned.user_error_code is UserErrorCode.INFRASTRUCTURE_TIMEOUT
    assert cleaned.refund_applied_at is not None


async def test_lazy_detection_marks_old_queued_job_failed_only_when_task_missing() -> None:
    """queued stuck은 Cloud Tasks task absence가 확인된 경우에만 failed+refund 된다."""
    repository = InMemoryVideoJobRepository()
    queue = _FakeQueue()
    client = CloudRunVideoJobClient(repository, queue)
    job = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    repository._jobs[job.id] = repository._jobs[job.id].model_copy(
        update={"created_at": datetime.now(UTC) - timedelta(minutes=16)}
    )

    still_queued = await client.check_stuck_job(
        job.id,
        user_id="user-1",
        running_stale_after_seconds=1800,
        queued_stale_after_seconds=900,
    )
    queue.missing_tasks.add(job.cloud_tasks_name)
    failed = await client.check_stuck_job(
        job.id,
        user_id="user-1",
        running_stale_after_seconds=1800,
        queued_stale_after_seconds=900,
    )

    assert still_queued is not None
    assert still_queued.status is VideoJobStatus.QUEUED
    assert failed is not None
    assert failed.status is VideoJobStatus.FAILED
    assert failed.error_stage is StageName.ENQUEUE
    assert failed.refund_applied_at is not None


async def test_latest_thread_job_returns_reconnect_restore_target() -> None:
    """재접속 복구는 해당 thread의 최신 video_jobs[-1] 상태를 조회한다."""
    client, _queue = _build_client()
    first = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    latest = await client.create_and_enqueue(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=VideoJobInput(problem_text="다른 문제"),
    )
    await client.finalize(first.id, status=VideoJobStatus.FAILED)

    restored = await client.get_latest_for_thread(user_id="user-1", thread_id="thread-1")

    assert restored == latest


async def test_postgres_success_finalize_sql_rejects_cancel_requested_jobs() -> None:
    """Postgres worker success terminal write is guarded against late cancel."""
    job = _job_for_postgres_sql_test()
    repository = _RecordingPostgresRepository(job)

    result = await repository.finalize_for_lease(
        job.id,
        instance_id="worker-1",
        status=VideoJobStatus.SUCCEEDED,
        artifact_object_key="video-jobs/job-1/final.mp4",
    )

    assert result is None
    assert "cancel_requested = FALSE" in repository.conn.queries[0]
    assert repository.conn.params[0]["status"] == VideoJobStatus.SUCCEEDED.value


async def test_postgres_heartbeat_sql_has_no_terminal_status_parameter() -> None:
    """Heartbeat must not carry success-finalize SQL guards or undefined params."""
    job = _job_for_postgres_sql_test()
    repository = _RecordingPostgresRepository(job)

    result = await repository.heartbeat_lease(job.id, instance_id="worker-1")

    assert result is None
    assert "cancel_requested = FALSE" not in repository.conn.queries[0]
    assert "status" not in repository.conn.params[0]


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


def _job_for_postgres_sql_test() -> VideoJob:
    now = datetime.now(UTC)
    return VideoJob(
        id="job-1",
        user_id="user-1",
        thread_id="thread-1",
        problem_hash="hash",
        input_snapshot=_sample_input(),
        cloud_tasks_name="video-job-1",
        status=VideoJobStatus.RUNNING,
        lease_holder_instance_id="worker-1",
        progress_updated_at=now,
        created_at=now,
    )
