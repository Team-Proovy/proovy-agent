"""Video job infrastructure factory tests."""

import pytest

from proovy_agent.common.config import Settings
from proovy_agent.features.video.jobs import (
    CloudRunVideoJobClient,
    PostgresVideoJobRepository,
    create_video_job_client,
)


def test_video_job_client_factory_allows_in_memory_only_in_debug() -> None:
    """DATABASE_URL 없는 in-memory fallback은 debug runtime으로 제한한다."""
    client = create_video_job_client(
        Settings(_env_file=None, debug=True, database_url=""),
    )

    assert isinstance(client, CloudRunVideoJobClient)


def test_video_job_client_factory_requires_database_url_outside_debug() -> None:
    """운영 모드에서 DATABASE_URL 누락 시 startup에서 명확히 실패한다."""
    with pytest.raises(RuntimeError, match="database_url must be set"):
        create_video_job_client(Settings(_env_file=None, debug=False, database_url=""))


def test_video_job_client_factory_uses_postgres_outside_debug() -> None:
    """운영 모드에서 DATABASE_URL이 있으면 Postgres 저장소를 선택한다."""
    client = create_video_job_client(
        Settings(
            _env_file=None,
            debug=False,
            database_url="postgres://user:pass@localhost:5432/proovy",
        ),
    )

    assert isinstance(client, CloudRunVideoJobClient)
    assert isinstance(client._repository, PostgresVideoJobRepository)
