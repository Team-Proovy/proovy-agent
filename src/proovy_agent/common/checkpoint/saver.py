"""LangGraph checkpointer 팩토리.

`database_url`이 있으면 Supabase Postgres(AsyncPostgresSaver)에 영속화하고,
없으면 InMemorySaver로 폴백한다 (dev/test — 프로세스 수명 동안만 유지).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

logger = logging.getLogger(__name__)


def _to_libpq(url: str) -> str:
    """SQLAlchemy식 드라이버 접미사를 제거해 libpq conninfo로 변환한다.

    AsyncPostgresSaver.from_conn_string은 libpq 형식(postgresql://)을 요구한다.
    .env에 `postgresql+psycopg://`처럼 SQLAlchemy URL이 들어와도 동작하도록 정규화.
    """
    return url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )


@asynccontextmanager
async def open_checkpointer(database_url: str) -> AsyncIterator[BaseCheckpointSaver]:
    """앱 수명 동안 유지되는 checkpointer를 연다.

    database_url이 설정돼 있으면 AsyncPostgresSaver(연결 풀)를 열고 최초 1회
    setup()으로 체크포인트 테이블을 생성한다. 비어 있으면 InMemorySaver로 폴백한다.
    """
    if database_url:
        async with AsyncPostgresSaver.from_conn_string(_to_libpq(database_url)) as saver:
            await saver.setup()
            logger.info("AsyncPostgresSaver 체크포인터 초기화 완료")
            yield saver
    else:
        logger.warning(
            "database_url 미설정 — InMemorySaver로 폴백 (프로세스 재시작 시 멀티턴 소실)"
        )
        yield InMemorySaver()
