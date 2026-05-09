# 프로젝트 디렉토리 구조

> 상태: 채택  
> 목적: LangGraph 기반 수학 문제 풀이 에이전트 백엔드의 초기 코드 구조를 정의한다.

## 결정 요약

이 프로젝트는 `src/proovy_agent/` 기반의 Python 패키지 구조를 사용한다.

- `src/`: Python 소스 루트
- `proovy_agent/`: 프로젝트 고유 import namespace
- `app/`: FastAPI 전용 계층
- `graph/`: LangGraph 실행 계층
- `features/`: 제품 도메인 기능
- `common/`: 공통 인프라 및 외부 연동

## 최종 디렉토리 구조

아래 트리는 최종 목표 구조다. 초기 세팅 단계에서는 모든 파일을 미리 만들지 않고,
구현이 시작되는 영역부터 필요한 파일을 추가한다.

```text
proovy-agent/
├── src/
│   └── proovy_agent/                         # 프로젝트 고유 Python 패키지 namespace
│       ├── __init__.py                       # 패키지 인식용
│       │
│       ├── app/                              # FastAPI 전용 계층
│       │   ├── __init__.py
│       │   ├── main.py                       # FastAPI app 생성, lifespan, middleware, router 등록
│       │   ├── deps.py                       # FastAPI Depends: DB, 인증, 서비스 주입
│       │   ├── errors.py                     # 전역 예외 핸들러
│       │   ├── api/
│       │   │   └── v1/
│       │   │       ├── router.py             # v1 라우터 통합
│       │   │       ├── health.py             # 헬스체크
│       │   │       ├── solve.py              # 문제 풀이 요청 + SSE 시작
│       │   │       ├── threads.py            # thread/page 조회, 재접속 복구
│       │   │       └── credits.py            # 크레딧 조회 API
│       │   ├── schemas/                      # API 요청/응답 DTO
│       │   │   ├── solve.py
│       │   │   ├── threads.py
│       │   │   ├── events.py
│       │   │   └── credits.py
│       │   └── middleware/                   # API key, request id 등 FastAPI 미들웨어
│       │
│       ├── graph/                            # LangGraph 핵심 계층
│       │   ├── __init__.py
│       │   ├── builder.py                    # StateGraph 노드/엣지 구성
│       │   ├── compiled.py                   # compile된 graph 제공
│       │   ├── state.py                      # ProovyState, PlanStep, CreditEntry
│       │   ├── reducers.py                   # messages, credit_log reducer
│       │   ├── commands.py                   # Command API / Send API 유틸
│       │   ├── events.py                     # graph 이벤트 → SSE 이벤트 변환
│       │   ├── render.py                     # messages → 화면 표시 데이터 변환
│       │   ├── nodes/                        # 설계 문서의 각 노드 구현
│       │   │   ├── preprocessor.py           # OCR + @커맨드 파싱
│       │   │   ├── router.py                 # general_chat / math_task 라우팅
│       │   │   ├── planner.py                # plan 생성, 모델 선택, 크레딧 예약
│       │   │   ├── plan_executor.py          # Command API / Send API 실행 제어
│       │   │   ├── core_solver.py            # 2-Phase verify → explain
│       │   │   ├── general_chat.py           # off-topic 대화
│       │   │   ├── video.py                  # 해설 영상 생성
│       │   │   ├── pdf.py                    # 해설지 PDF 생성
│       │   │   └── credit_settler.py         # 크레딧 정산
│       │   ├── agents/
│       │   │   └── core_solver/
│       │   │       ├── factory.py            # create_agent 생성
│       │   │       ├── middleware.py         # dynamic_prompt, before_model, after_model
│       │   │       └── prompts.py            # CoreSolver 프롬프트
│       │   └── tools/
│       │       ├── code_generate.py          # 검증 코드 생성
│       │       ├── code_execute.py           # Daytona 코드 실행
│       │       └── image_generate.py         # 비동기 이미지 생성
│       │
│       ├── features/                         # 도메인 기능
│       │   ├── credits/                      # 크레딧 예약/정산/TTL
│       │   ├── threads/                      # thread/page/messages 복구
│       │   └── artifacts/                    # pdf/video/image 결과물 관리
│       │
│       └── common/                           # 공통 인프라/외부 연동
│           ├── config.py                     # pydantic-settings 환경변수
│           ├── logging.py                    # 로깅 설정
│           ├── exceptions.py                 # 공통 예외
│           ├── llm/                          # ChatOpenRouter
│           ├── sandbox/                      # Daytona
│           ├── checkpoint/                   # PostgresSaver
│           ├── db/                           # DB session/base
│           ├── sse/                          # SSE emitter/broker/constants
│           └── utils/                        # ids, time 등 범용 유틸
│
├── tests/                                    # 테스트는 패키지 구조를 미러링
├── alembic/                                  # DB migration
├── scripts/                                  # 운영/개발 스크립트
├── langgraph.json                            # LangGraph CLI/Studio 설정
├── pyproject.toml
├── uv.lock
├── README.md
└── .env.example
```

## 계층별 책임

### `app/`

FastAPI 애플리케이션 계층이다. HTTP, SSE, middleware, request/response schema처럼
웹 프레임워크에 가까운 코드만 둔다. LangGraph 노드 구현이나 크레딧 정산 로직은 직접 넣지 않는다.

### `graph/`

LangGraph 실행 계층이다. 설계 문서의 `Preprocessor`, `Router`, `Planner`,
`PlanExecutor`, `CoreSolver`, `VideoNode`, `PDFNode`, `CreditSettler`를 이 영역에 둔다.

`graph/`는 다음 책임을 가진다.

- Pydantic 기반 `ProovyState` 정의
- `StateGraph` 구성 및 compile
- Command API / Send API 라우팅 유틸
- `messages` reducer 및 display render 로직
- CoreSolver agent factory, middleware, tools 관리

### `features/`

제품 도메인 기능 계층이다. LangGraph 노드가 사용하는 실제 비즈니스 로직을 둔다.

- `credits/`: 예약, 정산, 환불, TTL 만료 처리
- `threads/`: thread/page 조회, messages 복구, 재접속 처리
- `artifacts/`: PDF, 영상, 이미지 결과물 관리

### `common/`

여러 계층에서 공유하는 공통 인프라와 외부 연동을 둔다.

- 설정과 로깅
- OpenRouter LLM client
- Daytona sandbox client
- LangGraph PostgresSaver
- DB session/base
- SSE emitter/broker
- 공통 유틸

## 패키지 설치 방식 결정

이 프로젝트는 `src/` 레이아웃을 사용하므로, 프로젝트 자체를 editable package로 설치한다.
이를 위해 `pyproject.toml`에 `build-system`과 `tool.setuptools.packages.find`를 둔다.

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

### 장점

- `proovy_agent` namespace로 import 경로가 명확하다.
- `app`, `graph`, `common` 같은 일반적인 이름이 외부 패키지와 충돌하는 것을 방지한다.
- 테스트와 런타임에서 동일한 import 경로를 사용한다.
- Docker, CI, LangGraph CLI/Studio 환경에서 경로 설정이 단순해진다.
- 프로젝트 규모가 커져도 모듈 경계를 유지하기 쉽다.

### 단점

- 서비스 프로젝트임에도 패키지 설치 설정이 추가된다.
- 루트 레이아웃보다 초기 설정이 조금 더 많다.
- `uv sync` 시 프로젝트가 editable package로 설치된다.

### 선택한 이유

이 프로젝트는 FastAPI 단일 서버를 넘어 LangGraph 노드, agent, tool, checkpoint,
credit, SSE 등 모듈이 빠르게 늘어날 구조다. 따라서 초기부터 명확한 namespace와
import 안정성을 확보하는 편이 장기 유지보수에 유리하다고 판단했다.

## 루트 레이아웃과 비교

루트 레이아웃은 아래처럼 `proovy_agent/`를 저장소 루트에 직접 둔다.

```text
proovy-agent/
├── proovy_agent/
├── tests/
└── pyproject.toml
```

루트 레이아웃은 단순하지만, 테스트나 실행 환경에 따라 현재 작업 디렉토리 기반 import에
의존하기 쉽다. 반면 `src/` 레이아웃은 editable install을 전제로 하므로 설정은 조금 더 필요하지만,
실제 설치된 패키지 기준으로 import 경로를 검증할 수 있다.

## 운영 규칙

- 새 FastAPI endpoint는 `app/api/v1/`에 추가한다.
- 새 LangGraph node는 `graph/nodes/`에 추가한다.
- agent tool은 `graph/tools/`에 두고, 외부 서비스 client는 `common/` 또는 `features/`를 통해 호출한다.
- 표시용 데이터는 설계 원칙에 따라 `messages`를 단일 소스로 사용한다.
- 빈 폴더만 미리 만들지 않는다. 구현이 시작되는 계층부터 파일을 추가한다.
