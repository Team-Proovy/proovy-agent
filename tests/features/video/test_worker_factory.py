"""Video worker factory tests."""

import pytest

from proovy_agent.common.config import Settings
from proovy_agent.features.video.jobs import PostgresVideoJobRepository
from proovy_agent.features.video.worker import VideoWorkerRunner, create_video_worker_runner
from proovy_agent.features.video.worker.sandbox import ManimRenderSandbox


def test_video_worker_factory_requires_database_url_even_in_debug() -> None:
    """워커는 instance 간 공유 저장소가 필수라 in-memory fallback을 허용하지 않는다."""
    with pytest.raises(RuntimeError, match="database_url must be set for video worker"):
        create_video_worker_runner(Settings(_env_file=None, debug=True, database_url=""))


def test_video_worker_factory_uses_postgres_repository() -> None:
    runner = create_video_worker_runner(
        Settings(
            _env_file=None,
            debug=False,
            database_url="postgres://user:pass@localhost:5432/proovy",
            video_worker_instance_id="worker-1",
        )
    )

    assert isinstance(runner, VideoWorkerRunner)
    assert isinstance(runner._repository, PostgresVideoJobRepository)
    assert isinstance(runner._render_sandbox, ManimRenderSandbox)
