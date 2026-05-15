"""Sandbox lifecycle manager."""

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
    """Create and destroy Daytona sandbox executors."""

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
            raise SandboxCreationError(f"Sandbox creation failed: {exc}") from exc

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
                logger.exception("Executor cleanup failed")
            finally:
                try:
                    await asyncio.wait_for(sandbox.delete(), timeout=5.0)
                except Exception:
                    logger.warning(
                        "Sandbox deletion failed; Daytona auto_stop will be used as fallback",
                        exc_info=True,
                    )

        try:
            await asyncio.wait_for(_destroy(), timeout=timeout)
        except TimeoutError:
            logger.error(
                "destroy_executor timed out after %.1f seconds; Daytona auto_stop will be used as fallback",
                timeout,
            )
