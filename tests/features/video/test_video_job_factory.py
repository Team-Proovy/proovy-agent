"""Video job infrastructure factory tests."""

import pytest

from proovy_agent.common.config import Settings
from proovy_agent.features.video.jobs import (
    CloudRunVideoJobClient,
    CloudTasksVideoTaskQueue,
    NoopVideoTaskQueue,
    PostgresVideoJobRepository,
    create_video_job_client,
)


def test_video_job_client_factory_allows_in_memory_only_in_debug() -> None:
    """DATABASE_URL 없는 in-memory fallback은 debug runtime으로 제한한다."""
    client = create_video_job_client(
        Settings(_env_file=None, debug=True, database_url=""),
    )

    assert isinstance(client, CloudRunVideoJobClient)
    assert isinstance(client._queue, NoopVideoTaskQueue)


def test_video_job_client_factory_ignores_cloud_tasks_env_without_database_in_debug() -> None:
    """debug/no-DB에서는 stale queue env가 있어도 외부 Cloud Tasks로 보내지 않는다."""
    client = create_video_job_client(
        Settings(
            _env_file=None,
            debug=True,
            database_url="",
            VIDEO_CLOUD_TASKS_QUEUE_PATH="projects/p/locations/us-central1/queues/video",
            VIDEO_WORKER_URL="https://worker.example/jobs/run",
            VIDEO_WORKER_AUTH_TOKEN="secret",
        ),
    )

    assert isinstance(client, CloudRunVideoJobClient)
    assert isinstance(client._queue, NoopVideoTaskQueue)


def test_video_job_client_factory_requires_database_url_outside_debug() -> None:
    """운영 모드에서 DATABASE_URL 누락 시 startup에서 명확히 실패한다."""
    with pytest.raises(RuntimeError, match="database_url must be set"):
        create_video_job_client(Settings(_env_file=None, debug=False, database_url=""))


def test_video_job_client_factory_requires_cloud_tasks_outside_debug() -> None:
    """운영 모드에서 Cloud Tasks 설정 누락 시 no-op queue로 시작하지 않는다."""
    with pytest.raises(RuntimeError, match="Cloud Tasks queue must be configured"):
        create_video_job_client(
            Settings(
                _env_file=None,
                debug=False,
                database_url="postgres://user:pass@localhost:5432/proovy",
            )
        )


def test_video_job_client_factory_requires_worker_auth_with_cloud_tasks() -> None:
    """worker가 header token을 요구하므로 Cloud Tasks 구성도 token 없이 시작하지 않는다."""
    with pytest.raises(RuntimeError, match="VIDEO_WORKER_AUTH_TOKEN"):
        create_video_job_client(
            Settings(
                _env_file=None,
                debug=False,
                database_url="postgres://user:pass@localhost:5432/proovy",
                VIDEO_CLOUD_TASKS_QUEUE_PATH="projects/p/locations/us-central1/queues/video",
                VIDEO_WORKER_URL="https://worker.example/jobs/run",
            )
        )


def test_video_job_client_factory_uses_postgres_and_cloud_tasks_outside_debug() -> None:
    """운영 모드에서 DATABASE_URL과 queue 설정이 있으면 Postgres+Cloud Tasks를 선택한다."""
    client = create_video_job_client(
        Settings(
            _env_file=None,
            debug=False,
            database_url="postgres://user:pass@localhost:5432/proovy",
            VIDEO_CLOUD_TASKS_QUEUE_PATH="projects/p/locations/us-central1/queues/video",
            VIDEO_WORKER_URL="https://worker.example/jobs/run",
            VIDEO_WORKER_AUTH_TOKEN="secret",
        ),
    )

    assert isinstance(client, CloudRunVideoJobClient)
    assert isinstance(client._repository, PostgresVideoJobRepository)
    assert isinstance(client._queue, CloudTasksVideoTaskQueue)
