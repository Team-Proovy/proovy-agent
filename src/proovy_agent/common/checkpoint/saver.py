"""LangGraph checkpointer 팩토리.

`database_url`이 있으면 Supabase Postgres(AsyncPostgresSaver)에 영속화하고,
없으면 InMemorySaver로 폴백한다 (dev/test — 프로세스 수명 동안만 유지).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

logger = logging.getLogger(__name__)

# 체크포인트 채널에 들어가는 커스텀 Pydantic 타입 — Postgres 역직렬화 allowlist.
# 등록하지 않으면 "Deserializing unregistered type" 경고가 나고, 향후 strict
# msgpack 모드에서 차단될 수 있어 dict로 복원돼 PlanStep/CreditEntry가 깨진다.
_ALLOWED_MSGPACK_MODULES = [
    ("proovy_agent.graph.state", "PlanStep"),
    ("proovy_agent.graph.state", "CreditEntry"),
    ("proovy_agent.graph.state", "VideoJobRef"),
]


def _to_libpq(url: str) -> str:
    """connection string을 libpq 형식(postgresql://)으로 정규화한다.

    AsyncPostgresSaver.from_conn_string은 libpq scheme을 요구한다. SQLAlchemy식
    드라이버 접미사(`+psycopg`, `+psycopg2`, `+asyncpg` 등)와 `postgres://` 별칭을
    모두 `postgresql://`로 맞춘다.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0]
    if scheme == "postgres":
        scheme = "postgresql"
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


@asynccontextmanager
async def open_checkpointer(
    database_url: str,
    *,
    allow_memory_fallback: bool = True,
) -> AsyncIterator[BaseCheckpointSaver]:
    """앱 수명 동안 유지되는 checkpointer를 연다.

    database_url이 설정돼 있으면 AsyncPostgresSaver(연결 풀)를 열고 최초 1회
    setup()으로 체크포인트 테이블을 생성한다. 비어 있으면 allow_memory_fallback에
    따라 InMemorySaver로 폴백하거나(dev) RuntimeError를 던진다(prod fail-fast).
    """
    if database_url:
        serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
        async with AsyncPostgresSaver.from_conn_string(
            _to_libpq(database_url), serde=serde
        ) as saver:
            await saver.setup()
            logger.info("AsyncPostgresSaver 체크포인터 초기화 완료")
            yield saver
    elif allow_memory_fallback:
        logger.warning(
            "database_url 미설정 — InMemorySaver로 폴백 (프로세스 재시작/다중 워커 시 멀티턴 소실)"
        )
        yield InMemorySaver()
    else:
        raise RuntimeError(
            "database_url이 설정되지 않았습니다. 프로덕션에서는 InMemory 폴백이 "
            "워커/재시작 시 멀티턴을 조용히 소실시키므로 기동을 중단합니다. "
            "database_url을 설정하거나 debug 모드로 실행하세요."
        )
