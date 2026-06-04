"""Video worker HTTP handler tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proovy_agent.features.video.models import VideoJobStatus
from proovy_agent.features.video.worker.http_handler import router
from proovy_agent.features.video.worker.runner import (
    VideoWorkerRetryableError,
    VideoWorkerRunResult,
    VideoWorkerRunStatus,
)


class _FakeRunner:
    def __init__(self, result: VideoWorkerRunResult | None = None) -> None:
        self.result = result
        self.job_ids: list[str] = []
        self.retry = False

    async def run(self, job_id: str) -> VideoWorkerRunResult:
        self.job_ids.append(job_id)
        if self.retry:
            raise VideoWorkerRetryableError(job_id)
        return self.result or VideoWorkerRunResult(
            job_id=job_id,
            status=VideoWorkerRunStatus.COMPLETED,
            job_status=VideoJobStatus.SUCCEEDED,
            attempt_id="attempt-1",
        )


def _client_with_runner(runner: _FakeRunner) -> TestClient:
    app = FastAPI()
    app.state.video_worker_runner = runner
    app.include_router(router)
    return TestClient(app)


def test_worker_http_handler_runs_job() -> None:
    runner = _FakeRunner()
    client = _client_with_runner(runner)

    response = client.post("/jobs/run", json={"job_id": "job-1"})

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-1",
        "outcome": "completed",
        "job_status": "succeeded",
        "attempt_id": "attempt-1",
    }
    assert runner.job_ids == ["job-1"]


def test_worker_http_handler_returns_503_for_retryable_failure() -> None:
    runner = _FakeRunner()
    runner.retry = True
    client = _client_with_runner(runner)

    response = client.post("/jobs/run", json={"job_id": "job-1"})

    assert response.status_code == 503
    assert response.json()["detail"] == "video worker retry requested"
