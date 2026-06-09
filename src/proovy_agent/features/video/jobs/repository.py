"""Persistence contracts for asynchronous video jobs."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
from typing import TYPE_CHECKING, Protocol
import uuid

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from proovy_agent.common.checkpoint.saver import _to_libpq
from proovy_agent.features.credits.ledger import CreditLedger
from proovy_agent.features.video.models import (
    StageName,
    UserErrorCode,
    VideoJob,
    VideoJobInput,
    VideoJobStatus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from proovy_agent.features.credits.models import CreditAmount
    from proovy_agent.features.video.jobs.client import VideoCreditCapture

TERMINAL_JOB_STATUSES = {
    VideoJobStatus.SUCCEEDED,
    VideoJobStatus.FAILED,
    VideoJobStatus.CANCELED,
}
RETRYABLE_SOURCE_STATUSES = {VideoJobStatus.FAILED, VideoJobStatus.CANCELED}
RETRY_SOURCE_UNIQUE_CONSTRAINT = "uq_video_jobs_retry_source_job_id"


class VideoJobStoreError(Exception):
    """Base error for video job persistence failures."""


class VideoJobNotFoundError(VideoJobStoreError):
    """Raised when a requested video job does not exist."""


class InvalidRetrySourceError(VideoJobStoreError):
    """Raised when a user retry points at an invalid source job."""


class RetryAlreadyUsedError(VideoJobStoreError):
    """Raised when the source job already has a user retry child."""


def now_utc() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(UTC)


def build_problem_hash(input_snapshot: VideoJobInput) -> str:
    """Build a stable hash for analytics and future deduplication."""
    normalized = " ".join(input_snapshot.problem_text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def default_cloud_tasks_name(job_id: str) -> str:
    """Return the deterministic Cloud Tasks task id for a video job."""
    return f"video-{job_id}"


def _unique_violation_constraint_name(exc: UniqueViolation) -> str | None:
    """Return the violated unique constraint name when psycopg exposes it."""
    return getattr(exc.diag, "constraint_name", None)


def _validated_job_update(job: VideoJob, update: Mapping[str, Any]) -> VideoJob:
    """Apply updates through Pydantic validation rather than model_copy."""
    data = job.model_dump()
    data.update(update)
    return VideoJob.model_validate(data)


def _copy_job(job: VideoJob) -> VideoJob:
    """Return a defensive copy of a stored job."""
    return deepcopy(job)


class VideoJobRepository(Protocol):
    """Storage contract used by API, graph node, and future worker code."""

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
        """Create a queued job, copying source input for user retry requests."""

    async def get(self, job_id: str) -> VideoJob | None:
        """Return a single job by id."""

    async def get_latest_for_thread(self, *, user_id: str, thread_id: str) -> VideoJob | None:
        """Return the newest video job for a user's thread."""

    async def list_lazy_detection_candidates(
        self,
        *,
        user_id: str,
        running_stale_after_seconds: int,
        queued_stale_after_seconds: int,
    ) -> list[VideoJob]:
        """Return user-owned jobs that may need lazy stuck cleanup."""

    async def has_retry_for_source(self, source_job_id: str) -> bool:
        """Whether a user retry child already exists for the source job."""

    async def acquire_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        attempt_id: str,
        lease_stale_after_seconds: int,
    ) -> VideoJob | None:
        """Acquire or steal a stale worker lease; return None when another holder is alive."""

    async def heartbeat_lease(self, job_id: str, *, instance_id: str) -> VideoJob | None:
        """Refresh the current worker lease without changing user-facing progress."""

    async def release_lease(self, job_id: str, *, instance_id: str) -> VideoJob | None:
        """Release a lease held by the current worker instance."""

    async def update_progress(
        self,
        job_id: str,
        *,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ) -> VideoJob:
        """Update the hot progress fields for a single job."""

    async def update_progress_for_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ) -> VideoJob | None:
        """Update worker progress only when the caller still owns the lease."""

    async def finalize(
        self,
        job_id: str,
        *,
        status: VideoJobStatus,
        artifact_object_key: str | None = None,
        error_stage: StageName | None = None,
        user_error_code: UserErrorCode | None = None,
        error_detail: str | None = None,
        cost: Mapping[str, float] | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        """Mark a job as terminal."""

    async def mark_enqueue_failed(
        self,
        job_id: str,
        *,
        error_detail: str | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        """Mark an unleased queued job failed after a confirmed enqueue miss."""

    async def finalize_for_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        status: VideoJobStatus,
        artifact_object_key: str | None = None,
        error_stage: StageName | None = None,
        user_error_code: UserErrorCode | None = None,
        error_detail: str | None = None,
        cost: Mapping[str, float] | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob | None:
        """Mark a leased job as terminal only when the caller still owns it."""

    async def request_cancel(
        self,
        job_id: str,
        *,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        """Request cancellation; queued jobs may become terminal later."""

    async def mark_running_stuck(
        self,
        job_id: str,
        *,
        user_id: str,
        stale_after_seconds: int,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        """Mark one stale running job terminal and refund when the update wins."""

    async def mark_queued_missing(
        self,
        job_id: str,
        *,
        user_id: str,
        stale_after_seconds: int,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        """Mark one stale queued job failed after the queue confirms task absence."""


class InMemoryVideoJobRepository:
    """Process-local repository used by tests and dev without DATABASE_URL."""

    def __init__(self) -> None:
        self._jobs: dict[str, VideoJob] = {}
        self._lock = asyncio.Lock()

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
        _ = credit_capture
        async with self._lock:
            source_job: VideoJob | None = None
            if retry_source_job_id is not None:
                source_job = self._validate_retry_source_locked(
                    retry_source_job_id,
                    user_id=user_id,
                    thread_id=thread_id,
                )
                input_snapshot = source_job.input_snapshot

            if input_snapshot is None:
                raise InvalidRetrySourceError("input_snapshot is required for new video jobs")

            new_job_id = job_id or str(uuid.uuid4())
            if new_job_id in self._jobs:
                raise VideoJobStoreError(f"video job already exists: {new_job_id}")

            created_at = now_utc()
            job = VideoJob(
                id=new_job_id,
                user_id=user_id,
                thread_id=thread_id,
                problem_hash=build_problem_hash(input_snapshot),
                input_snapshot=input_snapshot,
                retry_source_job_id=retry_source_job_id,
                cloud_tasks_name=default_cloud_tasks_name(new_job_id),
                progress_updated_at=created_at,
                created_at=created_at,
            )
            self._jobs[job.id] = _copy_job(job)
            return _copy_job(job)

    async def get(self, job_id: str) -> VideoJob | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return _copy_job(job) if job is not None else None

    async def get_latest_for_thread(self, *, user_id: str, thread_id: str) -> VideoJob | None:
        async with self._lock:
            jobs = [
                job
                for job in self._jobs.values()
                if job.user_id == user_id and job.thread_id == thread_id
            ]
            if not jobs:
                return None
            latest = max(jobs, key=lambda job: (job.created_at, job.id))
            return _copy_job(latest)

    async def list_lazy_detection_candidates(
        self,
        *,
        user_id: str,
        running_stale_after_seconds: int,
        queued_stale_after_seconds: int,
    ) -> list[VideoJob]:
        async with self._lock:
            current_time = now_utc()
            running_stale_before = current_time - timedelta(seconds=running_stale_after_seconds)
            queued_stale_before = current_time - timedelta(seconds=queued_stale_after_seconds)
            candidates = [
                job
                for job in self._jobs.values()
                if job.user_id == user_id
                and (
                    (
                        job.status is VideoJobStatus.RUNNING
                        and job.progress_updated_at is not None
                        and job.progress_updated_at < running_stale_before
                    )
                    or (
                        job.status is VideoJobStatus.QUEUED and job.created_at < queued_stale_before
                    )
                )
            ]
            return [_copy_job(job) for job in candidates]

    async def has_retry_for_source(self, source_job_id: str) -> bool:
        async with self._lock:
            return any(job.retry_source_job_id == source_job_id for job in self._jobs.values())

    async def acquire_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        attempt_id: str,
        lease_stale_after_seconds: int,
    ) -> VideoJob | None:
        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return None

            current_time = now_utc()
            lease_expires_before = current_time - timedelta(seconds=lease_stale_after_seconds)
            lease_is_stale = (
                job.progress_updated_at is None or job.progress_updated_at < lease_expires_before
            )
            same_holder = job.lease_holder_instance_id == instance_id
            if job.lease_holder_instance_id is not None and not same_holder and not lease_is_stale:
                return None

            next_attempt_id = (
                job.active_attempt_id
                if same_holder and job.active_attempt_id is not None
                else attempt_id
            )
            updated = _validated_job_update(
                job,
                {
                    "status": VideoJobStatus.RUNNING,
                    "lease_holder_instance_id": instance_id,
                    "active_attempt_id": next_attempt_id,
                    "progress_updated_at": current_time,
                    "started_at": job.started_at or current_time,
                },
            )
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def heartbeat_lease(self, job_id: str, *, instance_id: str) -> VideoJob | None:
        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return None
            if job.lease_holder_instance_id != instance_id:
                return None

            updated = _validated_job_update(job, {"progress_updated_at": now_utc()})
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def release_lease(self, job_id: str, *, instance_id: str) -> VideoJob | None:
        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.lease_holder_instance_id != instance_id:
                return None

            updated = _validated_job_update(
                job,
                {
                    "lease_holder_instance_id": None,
                    "progress_updated_at": now_utc(),
                },
            )
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def update_progress(
        self,
        job_id: str,
        *,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ) -> VideoJob:
        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return _copy_job(job)

            update: dict[str, object] = {"progress_updated_at": now_utc()}
            if stage is not None:
                update["stage"] = stage
            if progress is not None:
                update["progress"] = dict(progress)
            if status is not None:
                update["status"] = status
                if status is VideoJobStatus.RUNNING and job.started_at is None:
                    update["started_at"] = update["progress_updated_at"]
            updated = _validated_job_update(job, update)
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def update_progress_for_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ) -> VideoJob | None:
        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return None
            if job.lease_holder_instance_id != instance_id:
                return None

            update: dict[str, object] = {"progress_updated_at": now_utc()}
            if stage is not None:
                update["stage"] = stage
            if progress is not None:
                update["progress"] = dict(progress)
            if status is not None:
                update["status"] = status
                if status is VideoJobStatus.RUNNING and job.started_at is None:
                    update["started_at"] = update["progress_updated_at"]
            updated = _validated_job_update(job, update)
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def finalize(
        self,
        job_id: str,
        *,
        status: VideoJobStatus,
        artifact_object_key: str | None = None,
        error_stage: StageName | None = None,
        user_error_code: UserErrorCode | None = None,
        error_detail: str | None = None,
        cost: Mapping[str, float] | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        if status not in TERMINAL_JOB_STATUSES:
            raise VideoJobStoreError("finalize requires a terminal job status")

        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return _copy_job(job)

            update: dict[str, object] = {
                "status": status,
                "artifact_object_key": artifact_object_key,
                "error_stage": error_stage,
                "user_error_code": user_error_code,
                "error_detail": error_detail,
                "cost": dict(cost or job.cost),
                "progress_updated_at": now_utc(),
                "finished_at": now_utc(),
            }
            if refund_amount is not None and status in {
                VideoJobStatus.FAILED,
                VideoJobStatus.CANCELED,
            }:
                update["refund_applied_at"] = job.refund_applied_at or now_utc()
            updated = _validated_job_update(job, update)
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def mark_enqueue_failed(
        self,
        job_id: str,
        *,
        error_detail: str | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return _copy_job(job)
            if job.status is not VideoJobStatus.QUEUED or job.lease_holder_instance_id is not None:
                return _copy_job(job)

            update: dict[str, object] = {
                "status": VideoJobStatus.FAILED,
                "error_stage": StageName.ENQUEUE,
                "user_error_code": UserErrorCode.INFRASTRUCTURE_ENQUEUE_FAILED,
                "error_detail": error_detail,
                "progress_updated_at": now_utc(),
                "finished_at": now_utc(),
            }
            if refund_amount is not None:
                update["refund_applied_at"] = now_utc()
            updated = _validated_job_update(job, update)
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def finalize_for_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        status: VideoJobStatus,
        artifact_object_key: str | None = None,
        error_stage: StageName | None = None,
        user_error_code: UserErrorCode | None = None,
        error_detail: str | None = None,
        cost: Mapping[str, float] | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob | None:
        if status not in TERMINAL_JOB_STATUSES:
            raise VideoJobStoreError("finalize requires a terminal job status")

        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return _copy_job(job)
            if job.lease_holder_instance_id != instance_id:
                return None
            if status is VideoJobStatus.SUCCEEDED and job.cancel_requested:
                return None

            update: dict[str, object] = {
                "status": status,
                "lease_holder_instance_id": None,
                "artifact_object_key": artifact_object_key,
                "error_stage": error_stage,
                "user_error_code": user_error_code,
                "error_detail": error_detail,
                "cost": dict(cost or job.cost),
                "progress_updated_at": now_utc(),
                "finished_at": now_utc(),
            }
            if refund_amount is not None and status in {
                VideoJobStatus.FAILED,
                VideoJobStatus.CANCELED,
            }:
                update["refund_applied_at"] = job.refund_applied_at or now_utc()
            updated = _validated_job_update(job, update)
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def request_cancel(
        self,
        job_id: str,
        *,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        async with self._lock:
            job = self._require_job_locked(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return _copy_job(job)
            if job.status is VideoJobStatus.QUEUED and job.lease_holder_instance_id is None:
                update: dict[str, object] = {
                    "status": VideoJobStatus.CANCELED,
                    "cancel_requested": True,
                    "progress_updated_at": now_utc(),
                    "finished_at": now_utc(),
                }
                if refund_amount is not None:
                    update["refund_applied_at"] = job.refund_applied_at or now_utc()
                updated = _validated_job_update(job, update)
            else:
                updated = _validated_job_update(job, {"cancel_requested": True})
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def mark_running_stuck(
        self,
        job_id: str,
        *,
        user_id: str,
        stale_after_seconds: int,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        async with self._lock:
            job = self._require_job_locked(job_id)
            stale_before = now_utc() - timedelta(seconds=stale_after_seconds)
            if (
                job.user_id != user_id
                or job.status is not VideoJobStatus.RUNNING
                or job.progress_updated_at is None
                or job.progress_updated_at >= stale_before
            ):
                return _copy_job(job)

            status = VideoJobStatus.CANCELED if job.cancel_requested else VideoJobStatus.FAILED
            update: dict[str, object] = {
                "status": status,
                "lease_holder_instance_id": None,
                "error_stage": job.stage,
                "user_error_code": None
                if status is VideoJobStatus.CANCELED
                else UserErrorCode.INFRASTRUCTURE_TIMEOUT,
                "progress_updated_at": now_utc(),
                "finished_at": now_utc(),
            }
            if refund_amount is not None:
                update["refund_applied_at"] = job.refund_applied_at or now_utc()
            updated = _validated_job_update(job, update)
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    async def mark_queued_missing(
        self,
        job_id: str,
        *,
        user_id: str,
        stale_after_seconds: int,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        async with self._lock:
            job = self._require_job_locked(job_id)
            stale_before = now_utc() - timedelta(seconds=stale_after_seconds)
            if (
                job.user_id != user_id
                or job.status is not VideoJobStatus.QUEUED
                or job.created_at >= stale_before
                or job.lease_holder_instance_id is not None
            ):
                return _copy_job(job)

            update: dict[str, object] = {
                "status": VideoJobStatus.FAILED,
                "lease_holder_instance_id": None,
                "error_stage": StageName.ENQUEUE,
                "user_error_code": UserErrorCode.INFRASTRUCTURE_ENQUEUE_FAILED,
                "progress_updated_at": now_utc(),
                "finished_at": now_utc(),
            }
            if refund_amount is not None:
                update["refund_applied_at"] = job.refund_applied_at or now_utc()
            updated = _validated_job_update(job, update)
            self._jobs[job_id] = _copy_job(updated)
            return _copy_job(updated)

    def _require_job_locked(self, job_id: str) -> VideoJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise VideoJobNotFoundError(job_id)
        return job

    def _validate_retry_source_locked(
        self,
        source_job_id: str,
        *,
        user_id: str,
        thread_id: str,
    ) -> VideoJob:
        source_job = self._jobs.get(source_job_id)
        if source_job is None:
            raise InvalidRetrySourceError("retry source job does not exist")
        if source_job.user_id != user_id or source_job.thread_id != thread_id:
            raise InvalidRetrySourceError("retry source job does not belong to this user/thread")
        if source_job.status not in RETRYABLE_SOURCE_STATUSES:
            raise InvalidRetrySourceError("retry source job is not failed or canceled")
        if source_job.retry_source_job_id is not None:
            raise InvalidRetrySourceError("retry source job cannot itself be a retry")
        if any(job.retry_source_job_id == source_job_id for job in self._jobs.values()):
            raise RetryAlreadyUsedError("retry already exists for source job")
        return source_job


class PostgresVideoJobRepository:
    """Postgres-backed repository for production deployments.

    The schema is created by the Phase B video job migration. Connections are
    opened per operation for now; a pooled session dependency can replace this
    without changing the VideoJobRepository contract.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = _to_libpq(database_url)

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
        async with await self._connect() as conn, conn.transaction():
            if retry_source_job_id is not None:
                source_job = await self._select_for_update(conn, retry_source_job_id)
                self._validate_retry_source(
                    source_job,
                    retry_source_job_id,
                    user_id=user_id,
                    thread_id=thread_id,
                )
                if await self._has_retry_for_source(conn, retry_source_job_id):
                    raise RetryAlreadyUsedError("retry already exists for source job")
                input_snapshot = source_job.input_snapshot

            if input_snapshot is None:
                raise InvalidRetrySourceError("input_snapshot is required for new video jobs")

            new_job_id = job_id or str(uuid.uuid4())
            created_at = now_utc()
            values = {
                "id": new_job_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "problem_hash": build_problem_hash(input_snapshot),
                "input_snapshot": Jsonb(input_snapshot.model_dump(mode="json")),
                "retry_source_job_id": retry_source_job_id,
                "status": VideoJobStatus.QUEUED.value,
                "stage": None,
                "progress": Jsonb({}),
                "cloud_tasks_name": default_cloud_tasks_name(new_job_id),
                "progress_updated_at": created_at,
                "created_at": created_at,
            }
            try:
                cur = await conn.execute(
                    """
                    INSERT INTO video_jobs (
                        id, user_id, thread_id, problem_hash, input_snapshot,
                        retry_source_job_id, status, stage, progress, cloud_tasks_name,
                        progress_updated_at, created_at
                    )
                    VALUES (
                        %(id)s, %(user_id)s, %(thread_id)s, %(problem_hash)s,
                        %(input_snapshot)s, %(retry_source_job_id)s, %(status)s,
                        %(stage)s, %(progress)s, %(cloud_tasks_name)s,
                        %(progress_updated_at)s, %(created_at)s
                    )
                    RETURNING *
                    """,
                    values,
                )
            except UniqueViolation as exc:
                if _unique_violation_constraint_name(exc) == RETRY_SOURCE_UNIQUE_CONSTRAINT:
                    raise RetryAlreadyUsedError("retry already exists for source job") from exc
                constraint_name = _unique_violation_constraint_name(exc) or "unknown"
                raise VideoJobStoreError(
                    f"video job unique constraint violation: {constraint_name}"
                ) from exc
            row = await cur.fetchone()
            if row is None:
                raise VideoJobStoreError("video job insert returned no row")
            if credit_capture is not None:
                await CreditLedger(conn).capture(
                    user_id,
                    credit_capture.hold_id,
                    credit_capture.amount,
                )
            return _row_to_job(row)

    async def get(self, job_id: str) -> VideoJob | None:
        async with await self._connect() as conn:
            cur = await conn.execute("SELECT * FROM video_jobs WHERE id = %s", (job_id,))
            row = await cur.fetchone()
            return _row_to_job(row) if row is not None else None

    async def get_latest_for_thread(self, *, user_id: str, thread_id: str) -> VideoJob | None:
        async with await self._connect() as conn:
            cur = await conn.execute(
                """
                SELECT *
                  FROM video_jobs
                 WHERE user_id = %s
                   AND thread_id = %s
                 ORDER BY created_at DESC, id DESC
                 LIMIT 1
                """,
                (user_id, thread_id),
            )
            row = await cur.fetchone()
            return _row_to_job(row) if row is not None else None

    async def list_lazy_detection_candidates(
        self,
        *,
        user_id: str,
        running_stale_after_seconds: int,
        queued_stale_after_seconds: int,
    ) -> list[VideoJob]:
        running_stale_before = now_utc() - timedelta(seconds=running_stale_after_seconds)
        queued_stale_before = now_utc() - timedelta(seconds=queued_stale_after_seconds)
        async with await self._connect() as conn:
            cur = await conn.execute(
                """
                SELECT *
                  FROM video_jobs
                 WHERE user_id = %(user_id)s
                   AND (
                     (
                       status = 'running'
                       AND progress_updated_at IS NOT NULL
                       AND progress_updated_at < %(running_stale_before)s
                     )
                     OR (
                       status = 'queued'
                       AND created_at < %(queued_stale_before)s
                     )
                   )
                 ORDER BY created_at ASC
                """,
                {
                    "user_id": user_id,
                    "running_stale_before": running_stale_before,
                    "queued_stale_before": queued_stale_before,
                },
            )
            rows = await cur.fetchall()
            return [_row_to_job(row) for row in rows]

    async def has_retry_for_source(self, source_job_id: str) -> bool:
        async with await self._connect() as conn:
            return await self._has_retry_for_source(conn, source_job_id)

    async def acquire_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        attempt_id: str,
        lease_stale_after_seconds: int,
    ) -> VideoJob | None:
        current_time = now_utc()
        lease_expires_before = current_time - timedelta(seconds=lease_stale_after_seconds)
        async with await self._connect() as conn:
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET lease_holder_instance_id = %(instance_id)s,
                    active_attempt_id = CASE
                        WHEN lease_holder_instance_id = %(instance_id)s
                             AND active_attempt_id IS NOT NULL
                        THEN active_attempt_id
                        ELSE %(attempt_id)s
                    END,
                    progress_updated_at = %(progress_updated_at)s,
                    started_at = COALESCE(started_at, %(progress_updated_at)s),
                    status = %(status)s
                WHERE id = %(id)s
                  AND status NOT IN ('succeeded', 'failed', 'canceled')
                  AND (
                    lease_holder_instance_id IS NULL
                    OR lease_holder_instance_id = %(instance_id)s
                    OR progress_updated_at IS NULL
                    OR progress_updated_at < %(lease_expires_before)s
                  )
                RETURNING *
                """,
                {
                    "id": job_id,
                    "instance_id": instance_id,
                    "attempt_id": attempt_id,
                    "progress_updated_at": current_time,
                    "lease_expires_before": lease_expires_before,
                    "status": VideoJobStatus.RUNNING.value,
                },
            )
            row = await cur.fetchone()
            if row is not None:
                return _row_to_job(row)

        existing = await self.get(job_id)
        if existing is None:
            raise VideoJobNotFoundError(job_id)
        return None

    async def heartbeat_lease(self, job_id: str, *, instance_id: str) -> VideoJob | None:
        async with await self._connect() as conn:
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET progress_updated_at = %(progress_updated_at)s
                WHERE id = %(id)s
                  AND lease_holder_instance_id = %(instance_id)s
                  AND status NOT IN ('succeeded', 'failed', 'canceled')
                RETURNING *
                """,
                {
                    "id": job_id,
                    "instance_id": instance_id,
                    "progress_updated_at": now_utc(),
                },
            )
            row = await cur.fetchone()
            if row is not None:
                return _row_to_job(row)

        existing = await self.get(job_id)
        if existing is None:
            raise VideoJobNotFoundError(job_id)
        return None

    async def release_lease(self, job_id: str, *, instance_id: str) -> VideoJob | None:
        async with await self._connect() as conn:
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET lease_holder_instance_id = NULL,
                    progress_updated_at = %(progress_updated_at)s
                WHERE id = %(id)s
                  AND lease_holder_instance_id = %(instance_id)s
                RETURNING *
                """,
                {
                    "id": job_id,
                    "instance_id": instance_id,
                    "progress_updated_at": now_utc(),
                },
            )
            row = await cur.fetchone()
            if row is not None:
                return _row_to_job(row)

        existing = await self.get(job_id)
        if existing is None:
            raise VideoJobNotFoundError(job_id)
        return None

    async def update_progress(
        self,
        job_id: str,
        *,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ) -> VideoJob:
        existing = await self.get(job_id)
        if existing is None:
            raise VideoJobNotFoundError(job_id)
        if existing.status in TERMINAL_JOB_STATUSES:
            return existing

        next_stage = stage if stage is not None else existing.stage
        next_progress = dict(progress) if progress is not None else existing.progress
        next_status = status if status is not None else existing.status
        started_at = existing.started_at
        if next_status is VideoJobStatus.RUNNING and started_at is None:
            started_at = now_utc()

        async with await self._connect() as conn:
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET stage = %(stage)s,
                    progress = %(progress)s,
                    status = %(status)s,
                    started_at = %(started_at)s,
                    progress_updated_at = %(progress_updated_at)s
                WHERE id = %(id)s
                  AND status NOT IN ('succeeded', 'failed', 'canceled')
                RETURNING *
                """,
                {
                    "id": job_id,
                    "stage": next_stage.value if next_stage is not None else None,
                    "progress": Jsonb(next_progress),
                    "status": next_status.value,
                    "started_at": started_at,
                    "progress_updated_at": now_utc(),
                },
            )
            row = await cur.fetchone()
            if row is None:
                refreshed = await self.get(job_id)
                if refreshed is not None and refreshed.status in TERMINAL_JOB_STATUSES:
                    return refreshed
                raise VideoJobNotFoundError(job_id)
            return _row_to_job(row)

    async def update_progress_for_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ) -> VideoJob | None:
        existing = await self.get(job_id)
        if existing is None:
            raise VideoJobNotFoundError(job_id)
        if existing.status in TERMINAL_JOB_STATUSES:
            return None

        next_stage = stage if stage is not None else existing.stage
        next_progress = dict(progress) if progress is not None else existing.progress
        next_status = status if status is not None else existing.status
        started_at = existing.started_at
        if next_status is VideoJobStatus.RUNNING and started_at is None:
            started_at = now_utc()

        async with await self._connect() as conn:
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET stage = %(stage)s,
                    progress = %(progress)s,
                    status = %(status)s,
                    started_at = %(started_at)s,
                    progress_updated_at = %(progress_updated_at)s
                WHERE id = %(id)s
                  AND lease_holder_instance_id = %(instance_id)s
                  AND status NOT IN ('succeeded', 'failed', 'canceled')
                RETURNING *
                """,
                {
                    "id": job_id,
                    "instance_id": instance_id,
                    "stage": next_stage.value if next_stage is not None else None,
                    "progress": Jsonb(next_progress),
                    "status": next_status.value,
                    "started_at": started_at,
                    "progress_updated_at": now_utc(),
                },
            )
            row = await cur.fetchone()
            if row is not None:
                return _row_to_job(row)

        refreshed = await self.get(job_id)
        if refreshed is None:
            raise VideoJobNotFoundError(job_id)
        if refreshed.status in TERMINAL_JOB_STATUSES:
            return None
        return None

    async def finalize(
        self,
        job_id: str,
        *,
        status: VideoJobStatus,
        artifact_object_key: str | None = None,
        error_stage: StageName | None = None,
        user_error_code: UserErrorCode | None = None,
        error_detail: str | None = None,
        cost: Mapping[str, float] | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        if status not in TERMINAL_JOB_STATUSES:
            raise VideoJobStoreError("finalize requires a terminal job status")

        existing = await self.get(job_id)
        if existing is None:
            raise VideoJobNotFoundError(job_id)
        if existing.status in TERMINAL_JOB_STATUSES:
            return existing

        async with await self._connect() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET status = %(status)s,
                    artifact_object_key = %(artifact_object_key)s,
                    error_stage = %(error_stage)s,
                    user_error_code = %(user_error_code)s,
                    error_detail = %(error_detail)s,
                    cost = %(cost)s,
                    progress_updated_at = %(progress_updated_at)s,
                    finished_at = %(finished_at)s
                WHERE id = %(id)s
                  AND status NOT IN ('succeeded', 'failed', 'canceled')
                RETURNING *
                """,
                {
                    "id": job_id,
                    "status": status.value,
                    "artifact_object_key": artifact_object_key,
                    "error_stage": error_stage.value if error_stage is not None else None,
                    "user_error_code": user_error_code.value
                    if user_error_code is not None
                    else None,
                    "error_detail": error_detail,
                    "cost": Jsonb(dict(cost or existing.cost)),
                    "progress_updated_at": now_utc(),
                    "finished_at": now_utc(),
                },
            )
            row = await cur.fetchone()
            if row is None:
                refreshed = await self.get(job_id)
                if refreshed is not None and refreshed.status in TERMINAL_JOB_STATUSES:
                    return refreshed
                raise VideoJobNotFoundError(job_id)
            if refund_amount is not None and status in {
                VideoJobStatus.FAILED,
                VideoJobStatus.CANCELED,
            }:
                await CreditLedger(conn).refund_if_not_succeeded(job_id, refund_amount)
                refreshed = await self._select_for_update(conn, job_id)
                if refreshed is None:
                    raise VideoJobNotFoundError(job_id)
                return refreshed
            return _row_to_job(row)

    async def mark_enqueue_failed(
        self,
        job_id: str,
        *,
        error_detail: str | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        async with await self._connect() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET status = %(status)s,
                    lease_holder_instance_id = NULL,
                    error_stage = %(error_stage)s,
                    user_error_code = %(user_error_code)s,
                    error_detail = %(error_detail)s,
                    progress_updated_at = %(progress_updated_at)s,
                    finished_at = %(finished_at)s
                WHERE id = %(id)s
                  AND status = 'queued'
                  AND lease_holder_instance_id IS NULL
                RETURNING *
                """,
                {
                    "id": job_id,
                    "status": VideoJobStatus.FAILED.value,
                    "error_stage": StageName.ENQUEUE.value,
                    "user_error_code": UserErrorCode.INFRASTRUCTURE_ENQUEUE_FAILED.value,
                    "error_detail": error_detail,
                    "progress_updated_at": now_utc(),
                    "finished_at": now_utc(),
                },
            )
            row = await cur.fetchone()
            if row is None:
                refreshed_cur = await conn.execute(
                    "SELECT * FROM video_jobs WHERE id = %s", (job_id,)
                )
                refreshed_row = await refreshed_cur.fetchone()
                if refreshed_row is None:
                    raise VideoJobNotFoundError(job_id)
                return _row_to_job(refreshed_row)
            if refund_amount is not None:
                await CreditLedger(conn).refund_if_not_succeeded(job_id, refund_amount)
                refreshed = await self._select_for_update(conn, job_id)
                if refreshed is None:
                    raise VideoJobNotFoundError(job_id)
                return refreshed
            return _row_to_job(row)

    async def finalize_for_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        status: VideoJobStatus,
        artifact_object_key: str | None = None,
        error_stage: StageName | None = None,
        user_error_code: UserErrorCode | None = None,
        error_detail: str | None = None,
        cost: Mapping[str, float] | None = None,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob | None:
        if status not in TERMINAL_JOB_STATUSES:
            raise VideoJobStoreError("finalize requires a terminal job status")

        existing = await self.get(job_id)
        if existing is None:
            raise VideoJobNotFoundError(job_id)
        if existing.status in TERMINAL_JOB_STATUSES:
            return existing

        async with await self._connect() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET status = %(status)s,
                    lease_holder_instance_id = NULL,
                    artifact_object_key = %(artifact_object_key)s,
                    error_stage = %(error_stage)s,
                    user_error_code = %(user_error_code)s,
                    error_detail = %(error_detail)s,
                    cost = %(cost)s,
                    progress_updated_at = %(progress_updated_at)s,
                    finished_at = %(finished_at)s
                WHERE id = %(id)s
                  AND lease_holder_instance_id = %(instance_id)s
                  AND status NOT IN ('succeeded', 'failed', 'canceled')
                  AND (%(status)s <> 'succeeded' OR cancel_requested = FALSE)
                RETURNING *
                """,
                {
                    "id": job_id,
                    "instance_id": instance_id,
                    "status": status.value,
                    "artifact_object_key": artifact_object_key,
                    "error_stage": error_stage.value if error_stage is not None else None,
                    "user_error_code": user_error_code.value
                    if user_error_code is not None
                    else None,
                    "error_detail": error_detail,
                    "cost": Jsonb(dict(cost or existing.cost)),
                    "progress_updated_at": now_utc(),
                    "finished_at": now_utc(),
                },
            )
            row = await cur.fetchone()
            if row is not None:
                if refund_amount is not None and status in {
                    VideoJobStatus.FAILED,
                    VideoJobStatus.CANCELED,
                }:
                    await CreditLedger(conn).refund_if_not_succeeded(job_id, refund_amount)
                    refreshed = await self._select_for_update(conn, job_id)
                    if refreshed is None:
                        raise VideoJobNotFoundError(job_id)
                    return refreshed
                return _row_to_job(row)

        refreshed = await self.get(job_id)
        if refreshed is None:
            raise VideoJobNotFoundError(job_id)
        if refreshed.status in TERMINAL_JOB_STATUSES:
            return refreshed
        return None

    async def request_cancel(
        self,
        job_id: str,
        *,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        existing = await self.get(job_id)
        if existing is None:
            raise VideoJobNotFoundError(job_id)
        if existing.status in TERMINAL_JOB_STATUSES:
            return existing

        async with await self._connect() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET status = 'canceled',
                    cancel_requested = TRUE,
                    progress_updated_at = %(progress_updated_at)s,
                    finished_at = %(finished_at)s
                WHERE id = %(id)s
                  AND status = 'queued'
                  AND lease_holder_instance_id IS NULL
                RETURNING *
                """,
                {
                    "id": job_id,
                    "progress_updated_at": now_utc(),
                    "finished_at": now_utc(),
                },
            )
            row = await cur.fetchone()
            if row is not None:
                if refund_amount is not None:
                    await CreditLedger(conn).refund_if_not_succeeded(job_id, refund_amount)
                    refreshed = await self._select_for_update(conn, job_id)
                    if refreshed is None:
                        raise VideoJobNotFoundError(job_id)
                    return refreshed
                return _row_to_job(row)

            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET cancel_requested = TRUE
                WHERE id = %(id)s
                  AND status = 'running'
                RETURNING *
                """,
                {"id": job_id},
            )
            row = await cur.fetchone()
            if row is None:
                refreshed = await self.get(job_id)
                if refreshed is not None and refreshed.status in TERMINAL_JOB_STATUSES:
                    return refreshed
                raise VideoJobNotFoundError(job_id)
            return _row_to_job(row)

    async def mark_running_stuck(
        self,
        job_id: str,
        *,
        user_id: str,
        stale_after_seconds: int,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        stale_before = now_utc() - timedelta(seconds=stale_after_seconds)
        async with await self._connect() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET status = CASE WHEN cancel_requested THEN 'canceled' ELSE 'failed' END,
                    lease_holder_instance_id = NULL,
                    user_error_code = CASE
                        WHEN cancel_requested THEN NULL
                        ELSE %(timeout_code)s
                    END,
                    error_stage = stage,
                    progress_updated_at = %(progress_updated_at)s,
                    finished_at = %(finished_at)s
                WHERE id = %(id)s
                  AND user_id = %(user_id)s
                  AND status = 'running'
                  AND progress_updated_at IS NOT NULL
                  AND progress_updated_at < %(stale_before)s
                RETURNING *
                """,
                {
                    "id": job_id,
                    "user_id": user_id,
                    "timeout_code": UserErrorCode.INFRASTRUCTURE_TIMEOUT.value,
                    "progress_updated_at": now_utc(),
                    "finished_at": now_utc(),
                    "stale_before": stale_before,
                },
            )
            row = await cur.fetchone()
            if row is None:
                refreshed_cur = await conn.execute(
                    "SELECT * FROM video_jobs WHERE id = %s", (job_id,)
                )
                refreshed_row = await refreshed_cur.fetchone()
                if refreshed_row is None:
                    raise VideoJobNotFoundError(job_id)
                return _row_to_job(refreshed_row)
            if refund_amount is not None:
                await CreditLedger(conn).refund_if_not_succeeded(job_id, refund_amount)
                refreshed = await self._select_for_update(conn, job_id)
                if refreshed is None:
                    raise VideoJobNotFoundError(job_id)
                return refreshed
            return _row_to_job(row)

    async def mark_queued_missing(
        self,
        job_id: str,
        *,
        user_id: str,
        stale_after_seconds: int,
        refund_amount: CreditAmount | None = None,
    ) -> VideoJob:
        stale_before = now_utc() - timedelta(seconds=stale_after_seconds)
        async with await self._connect() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE video_jobs
                SET status = 'failed',
                    lease_holder_instance_id = NULL,
                    error_stage = %(error_stage)s,
                    user_error_code = %(user_error_code)s,
                    progress_updated_at = %(progress_updated_at)s,
                    finished_at = %(finished_at)s
                WHERE id = %(id)s
                  AND user_id = %(user_id)s
                  AND status = 'queued'
                  AND lease_holder_instance_id IS NULL
                  AND created_at < %(stale_before)s
                RETURNING *
                """,
                {
                    "id": job_id,
                    "user_id": user_id,
                    "error_stage": StageName.ENQUEUE.value,
                    "user_error_code": UserErrorCode.INFRASTRUCTURE_ENQUEUE_FAILED.value,
                    "progress_updated_at": now_utc(),
                    "finished_at": now_utc(),
                    "stale_before": stale_before,
                },
            )
            row = await cur.fetchone()
            if row is None:
                refreshed_cur = await conn.execute(
                    "SELECT * FROM video_jobs WHERE id = %s", (job_id,)
                )
                refreshed_row = await refreshed_cur.fetchone()
                if refreshed_row is None:
                    raise VideoJobNotFoundError(job_id)
                return _row_to_job(refreshed_row)
            if refund_amount is not None:
                await CreditLedger(conn).refund_if_not_succeeded(job_id, refund_amount)
                refreshed = await self._select_for_update(conn, job_id)
                if refreshed is None:
                    raise VideoJobNotFoundError(job_id)
                return refreshed
            return _row_to_job(row)

    async def _connect(self) -> AsyncConnection[dict[str, Any]]:
        return await AsyncConnection.connect(self._database_url, row_factory=dict_row)

    async def _select_for_update(
        self,
        conn: AsyncConnection[dict[str, Any]],
        job_id: str,
    ) -> VideoJob | None:
        cur = await conn.execute("SELECT * FROM video_jobs WHERE id = %s FOR UPDATE", (job_id,))
        row = await cur.fetchone()
        return _row_to_job(row) if row is not None else None

    async def _has_retry_for_source(
        self,
        conn: AsyncConnection[dict[str, Any]],
        source_job_id: str,
    ) -> bool:
        cur = await conn.execute(
            "SELECT 1 FROM video_jobs WHERE retry_source_job_id = %s LIMIT 1",
            (source_job_id,),
        )
        return await cur.fetchone() is not None

    def _validate_retry_source(
        self,
        source_job: VideoJob | None,
        source_job_id: str,
        *,
        user_id: str,
        thread_id: str,
    ) -> None:
        if source_job is None:
            raise InvalidRetrySourceError("retry source job does not exist")
        if source_job.id != source_job_id:
            raise InvalidRetrySourceError("retry source job does not match")
        if source_job.user_id != user_id or source_job.thread_id != thread_id:
            raise InvalidRetrySourceError("retry source job does not belong to this user/thread")
        if source_job.status not in RETRYABLE_SOURCE_STATUSES:
            raise InvalidRetrySourceError("retry source job is not failed or canceled")
        if source_job.retry_source_job_id is not None:
            raise InvalidRetrySourceError("retry source job cannot itself be a retry")


def _row_to_job(row: Mapping[str, Any]) -> VideoJob:
    return VideoJob(
        id=row["id"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        problem_hash=row["problem_hash"],
        input_snapshot=VideoJobInput.model_validate(row["input_snapshot"]),
        retry_source_job_id=row["retry_source_job_id"],
        status=VideoJobStatus(row["status"]),
        stage=StageName(row["stage"]) if row["stage"] is not None else None,
        progress=dict(row["progress"] or {}),
        lease_holder_instance_id=row["lease_holder_instance_id"],
        progress_updated_at=row["progress_updated_at"],
        active_attempt_id=row["active_attempt_id"],
        artifact_object_key=row["artifact_object_key"],
        error_stage=StageName(row["error_stage"]) if row["error_stage"] is not None else None,
        user_error_code=(
            UserErrorCode(row["user_error_code"]) if row["user_error_code"] is not None else None
        ),
        error_detail=row["error_detail"],
        cost=dict(row["cost"] or {}),
        cloud_tasks_name=row["cloud_tasks_name"],
        cancel_requested=row["cancel_requested"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        refund_applied_at=row.get("refund_applied_at"),
    )
