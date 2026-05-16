"""Sandbox lifecycle을 관리합니다."""

from __future__ import annotations

import asyncio
import logging

from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams, Resources

from proovy_agent.common.config import settings
from proovy_agent.common.sandbox.exceptions import SandboxCreationError
from proovy_agent.common.sandbox.executor import CodeExecutor
from proovy_agent.common.sandbox.models import SandboxConfig

logger = logging.getLogger(__name__)


class SandboxManager:
    """Daytona Sandbox executor를 생성하고 정리합니다."""

    def __init__(self, client: AsyncDaytona) -> None:
        self._client = client

    async def create_executor(
        self,
        thread_id: str,
        config: SandboxConfig | None = None,
    ) -> CodeExecutor:
        cfg = config or SandboxConfig.from_settings(settings)
        try:
            params = CreateSandboxFromSnapshotParams(
                snapshot=cfg.snapshot,
                labels={"thread_id": thread_id},
                resources=Resources(cpu=cfg.cpu, memory=cfg.memory, disk=cfg.disk),
                auto_stop_interval=cfg.auto_stop_interval,
                network_block_all=cfg.network_block_all,
            )
            sandbox = await self._client.create(params)
        except Exception as exc:
            raise SandboxCreationError(f"Sandbox 생성 실패: {exc}") from exc

        return CodeExecutor(
            sandbox=sandbox,
            code_timeout=cfg.code_timeout,
            max_output_chars=cfg.max_output_chars,
            preamble_code=cfg.preamble_code,
        )

    async def destroy_executor(
        self,
        executor: CodeExecutor,
        *,
        timeout: float = 10.0,  # noqa: ASYNC109
    ) -> None:
        sandbox = executor.sandbox

        async def _destroy() -> None:
            try:
                await asyncio.wait_for(executor.cleanup(), timeout=3.0)
            except Exception:
                logger.exception("Executor cleanup 실패")
            finally:
                try:
                    await asyncio.wait_for(sandbox.delete(), timeout=5.0)
                except Exception:
                    logger.warning(
                        "Sandbox 삭제 실패; Daytona auto_stop을 fallback으로 사용합니다",
                        exc_info=True,
                    )

        try:
            await asyncio.wait_for(_destroy(), timeout=timeout)
        except TimeoutError:
            logger.error(
                "destroy_executor 전체 timeout (%.1f초); Daytona auto_stop을 fallback으로 사용합니다",
                timeout,
            )
