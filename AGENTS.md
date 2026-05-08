# AGENTS.md

AI 코딩 어시스턴트를 위한 이 레포 가이드입니다.

## 프로젝트 개요

LangGraph 기반 수학 문제 풀이 AI 에이전트 백엔드.
사용자가 수학 문제를 입력하면 OCR → 라우팅 → 계획 수립 → 코드 실행 검증 → 풀이 결과를 SSE로 스트리밍합니다.

## 기술 스택 핵심 사항

**LangGraph**
- `create_react_agent`는 deprecated. 반드시 `langchain.agents`의 `create_agent`를 사용합니다.
- 노드 간 라우팅은 `Command API` (`langgraph.types.Command`)를 사용합니다.
- 병렬 실행은 `Send API` (`langgraph.types.Send`)를 사용합니다.
- State는 `TypedDict`가 아닌 **Pydantic `BaseModel`** 로 정의합니다.

**LLM**
- OpenRouter를 사용합니다.
- `ChatOpenAI(base_url="https://openrouter.ai/api/v1")` 방식은 사용하지 않습니다.
- 반드시 `langchain_openrouter`의 `ChatOpenRouter`를 사용합니다.

**Daytona (샌드박스)**
- 패키지명: `daytona` (`daytona-sdk` 아님)
- import: `from daytona import AsyncDaytona, DaytonaConfig`

## 개발 명령어

```bash
uv run ruff check .   # 린트
uv run ruff format .  # 포맷
uv run pytest         # 테스트
```

## 커밋 컨벤션

`type: 메시지` 형식을 사용합니다. 메시지는 한국어로 작성합니다.

| 타입 | 사용 시점 |
|---|---|
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `chore` | 빌드, 설정, 의존성 등 기능 변화 없는 작업 |
| `refactor` | 동작 변화 없는 코드 구조 변경 |
| `docs` | 문서 수정 |

브랜치명은 `type/이슈번호-간단한설명` 형식을 사용합니다.

```text
feat/7-core-solver
fix/12-credit-calculation
chore/1-project-init-setting
```

## GitHub CLI (gh)

```bash
# 이슈 목록 조회
gh issue list

# 이슈 상세 조회
gh issue view <번호>

# PR 생성
gh pr create --base dev  # 기본 대상 브랜치는 dev

# PR 목록 조회
gh pr list
```

PR 작성 시 `.github/pull_request_template.md`를 참고해 내용을 채웁니다.
별도 요청이 없으면 base 브랜치는 항상 `dev`로 합니다.

## 코드 컨벤션

- Python 3.12+, 타입 힌트 필수
- `Optional[str]` 대신 `str | None` 사용 (ruff UP 규칙)
- `async def` 함수 안에서 blocking call 금지 (ruff ASYNC 규칙)
- import 순서: stdlib → third-party → first-party (`proovy_agent`)
