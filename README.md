# proovy-agent

LangGraph 기반 수학 문제 풀이 AI 에이전트

## 기술 스택

- **Agent**: LangGraph + LangChain (`create_agent`, Command API)
- **LLM**: OpenRouter (`ChatOpenRouter`)
- **API**: FastAPI + SSE
- **Sandbox**: Daytona (코드 실행 격리)
- **Checkpoint**: PostgreSQL (`AsyncPostgresSaver`)
- **패키지 매니저**: uv

## 시작하기

### 요구사항

- Python 3.12
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### 설치

```bash
# 의존성 설치
uv sync

# pre-commit 훅 등록 (최초 1회, 컴퓨터마다 실행 필요)
uv run pre-commit install

# 환경변수 파일 생성
cp .env.example .env
# .env 파일을 열어 API 키 입력
```

### 환경변수

`.env.example`을 복사한 후 아래 값을 채워넣으면 됩니다.

| 변수 | 필수 | 설명 |
|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | [OpenRouter](https://openrouter.ai/keys) 에서 발급 |
| `DAYTONA_API_KEY` | ✅ | [Daytona Dashboard](https://app.daytona.io/dashboard/keys) 에서 발급 |
| `DAYTONA_API_URL` | ✅ | `https://app.daytona.io/api` |
| `DAYTONA_TARGET` | ❌ | 샌드박스 실행 리전 (`us` / `eu`), 생략 시 계정 기본값 사용 |
| `DATABASE_URL` | ✅ | PostgreSQL 연결 문자열 |

## 개발

```bash
# 린트
uv run ruff check .

# 포맷
uv run ruff format .

# 테스트
uv run pytest
```

## 커밋 컨벤션

`type: 메시지` 형식을 사용합니다.

| 타입 | 사용 시점 |
|---|---|
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `chore` | 빌드, 설정, 의존성 등 기능 변화 없는 작업 |
| `refactor` | 동작 변화 없는 코드 구조 변경 |
| `docs` | 문서 수정 |
