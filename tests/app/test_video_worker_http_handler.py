"""Video worker HTTP handler tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proovy_agent.features.video.models import VideoJobStatus
from proovy_agent.features.video.worker.healthcheck import WorkerHealthCheck, WorkerHealthReport
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
    app.state.video_worker_auth_token = "worker-secret"
    app.include_router(router)
    return TestClient(app)


def test_worker_http_handler_runs_job() -> None:
    runner = _FakeRunner()
    client = _client_with_runner(runner)

    response = client.post(
        "/jobs/run",
        json={"job_id": "job-1"},
        headers={"X-Proovy-Worker-Token": "worker-secret"},
    )

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

    response = client.post(
        "/jobs/run",
        json={"job_id": "job-1"},
        headers={"Authorization": "Bearer worker-secret"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "video worker retry requested"


def test_worker_http_handler_rejects_missing_credentials() -> None:
    runner = _FakeRunner()
    client = _client_with_runner(runner)

    response = client.post("/jobs/run", json={"job_id": "job-1"})

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid video worker credentials"
    assert runner.job_ids == []


def test_worker_http_handler_rejects_missing_auth_configuration() -> None:
    app = FastAPI()
    app.state.video_worker_runner = _FakeRunner()
    app.state.video_worker_auth_token = ""
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/jobs/run",
        json={"job_id": "job-1"},
        headers={"X-Proovy-Worker-Token": "worker-secret"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "video worker auth token is not configured"


def test_worker_health_endpoint_returns_startup_probe_report_without_auth() -> None:
    async def healthcheck() -> WorkerHealthReport:
        return WorkerHealthReport(
            status="ok",
            checks=[WorkerHealthCheck(name="manim", status="ok", detail="Manim Community")],
        )

    app = FastAPI()
    app.state.video_worker_runner = _FakeRunner()
    app.state.video_worker_auth_token = "worker-secret"
    app.state.video_worker_healthcheck = healthcheck
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/jobs/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": [{"name": "manim", "status": "ok", "detail": "Manim Community"}],
    }


def test_worker_health_endpoint_returns_503_for_failed_runtime_check() -> None:
    async def healthcheck() -> WorkerHealthReport:
        return WorkerHealthReport(
            status="failed",
            checks=[WorkerHealthCheck(name="cjk_font", status="failed", detail="missing")],
        )

    app = FastAPI()
    app.state.video_worker_runner = _FakeRunner()
    app.state.video_worker_auth_token = "worker-secret"
    app.state.video_worker_healthcheck = healthcheck
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/jobs/health")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "failed",
        "checks": [{"name": "cjk_font", "status": "failed", "detail": "missing"}],
    }
