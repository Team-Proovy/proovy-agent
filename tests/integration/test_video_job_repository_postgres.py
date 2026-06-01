"""Postgres-backed video job repository integration tests.

DATABASE_URL 미설정 시 skip — docker-compose.test.yml의 postgres 서비스로 실행한다:

    docker compose -f docker-compose.test.yml run --rm test-pg
"""

import os
import uuid

from psycopg import AsyncConnection
import pytest

from proovy_agent.common.checkpoint.saver import _to_libpq
from proovy_agent.features.video.jobs import (
    PostgresVideoJobRepository,
    RetryAlreadyUsedError,
    VideoJobStoreError,
)
from proovy_agent.features.video.models import (
    StageName,
    UserErrorCode,
    VideoJobInput,
    VideoJobStatus,
)

pytestmark = pytest.mark.postgres

_VIDEO_JOBS_DDL = [
    "DROP TABLE IF EXISTS video_jobs CASCADE",
    """
    CREATE TABLE video_jobs (
        id text PRIMARY KEY,
        user_id text NOT NULL,
        thread_id text NOT NULL,
        problem_hash text NOT NULL,
        input_snapshot jsonb NOT NULL,
        retry_source_job_id text NULL REFERENCES video_jobs(id),
        status text NOT NULL,
        stage text NULL,
        progress jsonb NOT NULL DEFAULT '{}'::jsonb,
        lease_holder_instance_id text NULL,
        progress_updated_at timestamptz NULL,
        active_attempt_id text NULL,
        artifact_object_key text NULL,
        error_stage text NULL,
        user_error_code text NULL,
        error_detail text NULL,
        cost jsonb NOT NULL DEFAULT '{}'::jsonb,
        cloud_tasks_name text NOT NULL UNIQUE,
        cancel_requested boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL,
        started_at timestamptz NULL,
        finished_at timestamptz NULL
    )
    """,
    """
    CREATE UNIQUE INDEX uq_video_jobs_retry_source_job_id
    ON video_jobs (retry_source_job_id)
    WHERE retry_source_job_id IS NOT NULL
    """,
]


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL 미설정 — Postgres 통합 테스트 건너뜀")
    return url


@pytest.fixture
async def repository(database_url: str) -> PostgresVideoJobRepository:
    async with await AsyncConnection.connect(_to_libpq(database_url)) as conn:
        for statement in _VIDEO_JOBS_DDL:
            await conn.execute(statement)
        await conn.commit()

    return PostgresVideoJobRepository(database_url)


def _sample_input() -> VideoJobInput:
    return VideoJobInput(problem_text="2x + 1 = 7을 풀어라.")


async def test_postgres_video_job_round_trip_and_retry_limit(
    repository: PostgresVideoJobRepository,
) -> None:
    """Postgres 저장소가 JSONB round-trip과 원본당 retry 1회 제한을 보장한다."""
    thread_id = f"thread-{uuid.uuid4()}"
    source = await repository.create(
        user_id="user-1",
        thread_id=thread_id,
        input_snapshot=_sample_input(),
    )

    loaded = await repository.get(source.id)
    assert loaded == source
    assert loaded is not None
    assert loaded.input_snapshot == _sample_input()

    failed_source = await repository.finalize(
        source.id,
        status=VideoJobStatus.FAILED,
        error_stage=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
    )
    retry = await repository.create(
        user_id="user-1",
        thread_id=thread_id,
        retry_source_job_id=failed_source.id,
    )

    assert retry.retry_source_job_id == source.id
    assert retry.input_snapshot == source.input_snapshot

    with pytest.raises(RetryAlreadyUsedError):
        await repository.create(
            user_id="user-1",
            thread_id=thread_id,
            retry_source_job_id=source.id,
        )


async def test_postgres_unique_violations_are_not_all_retry_errors(
    repository: PostgresVideoJobRepository,
) -> None:
    """PK/cloud task unique 위반은 retry 이미 사용 오류로 오분류하지 않는다."""
    job_id = f"job-{uuid.uuid4()}"
    await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
        job_id=job_id,
    )

    with pytest.raises(VideoJobStoreError) as exc_info:
        await repository.create(
            user_id="user-1",
            thread_id="thread-1",
            input_snapshot=_sample_input(),
            job_id=job_id,
        )

    assert not isinstance(exc_info.value, RetryAlreadyUsedError)
    assert "unique constraint violation" in str(exc_info.value)


async def test_postgres_terminal_job_ignores_late_progress_write(
    repository: PostgresVideoJobRepository,
) -> None:
    """Terminal job은 stale progress write로 running 상태로 되돌아가지 않는다."""
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    failed = await repository.finalize(
        job.id,
        status=VideoJobStatus.FAILED,
        error_stage=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
    )

    late_update = await repository.update_progress(
        job.id,
        status=VideoJobStatus.RUNNING,
        stage=StageName.RENDER,
        progress={"segments_done": 1, "segments_total": 3},
    )

    assert late_update == failed
    assert late_update.status is VideoJobStatus.FAILED
    assert late_update.progress == {}


async def test_postgres_terminal_job_ignores_late_finalize_write(
    repository: PostgresVideoJobRepository,
) -> None:
    """Terminal job은 stale finalize write로 성공 상태로 덮이지 않는다."""
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    failed = await repository.finalize(
        job.id,
        status=VideoJobStatus.FAILED,
        error_stage=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
    )

    late_finalize = await repository.finalize(
        job.id,
        status=VideoJobStatus.SUCCEEDED,
        artifact_object_key="video-jobs/final.mp4",
    )

    assert late_finalize == failed
    assert late_finalize.status is VideoJobStatus.FAILED
    assert late_finalize.artifact_object_key is None


async def test_postgres_request_cancel_ignores_terminal_job(
    repository: PostgresVideoJobRepository,
) -> None:
    """Terminal job cancel 요청은 terminal 결과를 유지한다."""
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    failed = await repository.finalize(
        job.id,
        status=VideoJobStatus.FAILED,
        error_stage=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
    )

    canceled = await repository.request_cancel(job.id)

    assert canceled == failed
    assert canceled.status is VideoJobStatus.FAILED
    assert canceled.cancel_requested is False
