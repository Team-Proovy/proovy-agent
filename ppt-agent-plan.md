---

# 포트폴리오 PPT 생성 에이전트 — 구현 Plan

---

## 1. 개요

| 항목 | 선택 |
|------|------|
| **LLM API** | OpenRouter (OpenAI SDK 호환) |
| **실행 환경** | Daytona Sandbox |
| **PPT 조작 방식** | Anthropic/Claude PPTX Skill 스타일 유지 (unpack → OOXML 분석/편집 → pack) |
| **MVP 범위** | 기존의 풀 자동 PPT 생성 흐름 유지 (텍스트 치환만 하는 축소 MVP 아님) |
| **에이전트 루프** | 직접 구현 (프레임워크 없음), tool execution 기반 유지 |
| **언어** | Python |

---

## 2. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│  너의 서비스 서버 (FastAPI 등)                                     │
│                                                                   │
│  ┌───────────┐     ┌──────────────┐     ┌────────────────────┐  │
│  │ Portfolio │     │   Agent      │     │   Daytona          │  │
│  │ DB/API    │────▶│   Runner     │◀───▶│   Sandbox          │  │
│  │           │     │              │     │                    │  │
│  └───────────┘     │  ┌────────┐  │     │  - template.pptx   │  │
│                     │  │while   │  │     │  - scripts/        │  │
│                     │  │ loop   │  │     │  - python3, lxml   │  │
│                     │  └───┬────┘  │     │                    │  │
│                     │      │       │     └────────────────────┘  │
│                     │      ▼       │                              │
│                     │  OpenRouter  │                              │
│                     │  (LLM API)  │                              │
│                     └──────────────┘                              │
│                            │                                      │
│                            ▼                                      │
│                      output.pptx                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

### 2-1. Anthropic/Claude PPTX Skill 작동 방식

본 계획의 기준 아키텍처는 기존 Claude/Anthropic PPTX Skill 방식입니다.

| 단계 | 설명 |
|------|------|
| **unpack** | `.pptx`를 zip으로 풀어 `ppt/slides/*.xml`, `ppt/slides/_rels/*.rels`, `ppt/presentation.xml`, theme/layout 관계 파일 등 OOXML 구조로 분해 |
| **inspect** | 슬라이드 XML, rels, presentation 구조를 직접 읽어 텍스트 박스·이미지·레이아웃·슬라이드 참조 관계를 파악 |
| **edit** | 구조적 XML 편집은 `sed` 같은 문자열 치환보다 Python + `lxml` 스크립트를 우선 사용. 필요한 경우 안전한 편집 스크립트를 생성해 실행 |
| **pack** | 수정된 OOXML 디렉토리를 다시 `.pptx`로 패키징 |

이 방식은 MVP에서도 유지합니다. 다만 서비스 프로덕션 자동화에서는 단순히 LLM에게 bash 권한을 주는 수준으로 끝내면 안 됩니다. 다음 guardrail을 반드시 추가합니다.

- XML 구조를 깨지 않도록 안전한 Python/lxml 편집 스크립트를 우선 사용
- pack 이후 런타임 validation을 통과해야만 사용자에게 결과 반환
- 실패 시 rollback/retry가 가능하도록 중간 산출물과 이전 정상 상태를 보존
- turn, command, 파일 상태, validation 결과를 추적하는 state tracking/logging 추가

에이전트 루프와 tool execution은 원래 Claude PPTX Skill 워크플로우와 정렬된 선택입니다. 단, runner는 관측 가능하고 제어 가능한 방식으로 제한되어야 합니다.

---

## 3. 프로젝트 구조

```
ppt-agent/
├── agent/
│   ├── __init__.py
│   ├── runner.py          # 에이전트 루프 (핵심)
│   ├── llm.py             # OpenRouter 클라이언트
│   ├── sandbox.py         # Daytona 샌드박스 관리
│   ├── tools.py           # Tool 정의 & 실행
│   └── prompts.py         # 시스템 프롬프트 빌더
│
├── skills/                 # Anthropic PPTX Skill에서 가져올 것
│   ├── SKILL.md
│   ├── editing.md
│   └── scripts/
│       ├── office/
│       │   ├── unpack.py
│       │   └── pack.py
│       ├── build_ppt.py       # 템플릿에서 슬라이드 선택·조립 (신규)
│       └── thumbnail.py
│
├── templates/
│   ├── modern.pptx            # 템플릿 A (표지/목차/타입1/타입2/... 포함)
│   ├── modern.json            # 템플릿 A 슬라이드 메타데이터 (등록 시 1회 생성)
│   ├── classic.pptx           # 템플릿 B
│   ├── classic.json
│   ├── minimal.pptx           # 템플릿 C
│   └── minimal.json
│
├── tools/
│   └── analyze_template.py    # 템플릿 등록 시 1회 실행 — 슬라이드 분석 & 메타데이터 생성
│
├── config.py
└── requirements.txt
```

> **디렉토리 분리 이유:**
> - `skills/scripts/office/` — PPTX XML 조작 관련 (unpack/pack)
> - `skills/scripts/` — 슬라이드 조립, 썸네일 등 고수준 스크립트
> - `templates/` — `.pptx` + `.json` 쌍으로 관리. json은 등록 시 1회 생성되는 슬라이드 메타데이터
> - `tools/` — 개발/운영용 CLI 도구 (서비스 런타임에는 사용되지 않음)

---

## 3-1. 템플릿 파일 구조

각 `.pptx` 템플릿 파일은 **여러 종류의 슬라이드를 한 파일에** 담고 있습니다.

```
example: modern.pptx 내부 슬라이드 구성
┌──────────────────────────────────────┐
│  Slide 1  — 표지 (Cover)             │  ← 이름·직함·사진
│  Slide 2  — 목차 (TOC)               │  ← 섹션 목록
│  Slide 3  — 섹션 구분선              │  ← 섹션 타이틀만
│  Slide 4  — 타입A: 텍스트 중심       │  ← 큰 텍스트 + 설명
│  Slide 5  — 타입B: 텍스트 + 이미지  │  ← 좌우 분할
│  Slide 6  — 타입C: 불릿 리스트       │  ← 항목 나열
│  Slide 7  — 타입D: 기술스택 그리드   │  ← 뱃지/태그형
│  Slide 8  — 마무리/연락처            │  ← 이메일·깃헙 등
└──────────────────────────────────────┘
```

### LLM의 슬라이드 선택 & 편집 방식

| 단계 | 시점 | 설명 |
|------|------|------|
| **1. 슬라이드 선택** | 생성 시작 | 프롬프트에 주입된 메타데이터(`role` + `description`)를 보고 포트폴리오 각 섹션에 맞는 슬라이드 결정 |
| **2. 조립** | 생성 시작 | 선택한 슬라이드 XML을 순서대로 output에 복사. 같은 슬라이드 여러 번 복사 가능 (예: 프로젝트 N개) |
| **3. XML 분석** | 슬라이드 편집 직전 | 해당 슬라이드의 XML을 직접 읽어 텍스트박스 위치·크기·구조 파악 |
| **4. 지능적 편집** | 슬라이드 편집 | 포트폴리오 내용을 슬라이드 구조에 맞게 적응 — 내용이 길면 요약, 항목 수가 다르면 재구성 등 |

> **LLM이 필요한 이유:** 단순 텍스트 치환이라면 스크립트로 충분합니다. LLM은 내용이 넘치거나 구조가 안 맞을 때 **판단해서 유연하게 처리**하는 역할을 합니다.
> 메타데이터는 슬라이드 선택(라우팅)을 위한 정보이고, 실제 편집 제약은 LLM이 해당 XML을 직접 보고 파악합니다.
> 메타데이터 생성 방법은 본 문서 말미의 **[관리도구] 템플릿 등록 가이드**를 참고하세요.

### 품질 요구사항

- 이미지/미디어가 포함된 포트폴리오도 지원해야 하며, slide rels와 `ppt/media/*` 참조가 깨지면 안 됩니다.
- 한국어 포트폴리오를 기본 케이스로 보고, 생성/preview 변환 환경에 한국어 폰트를 준비합니다.
- 텍스트 overflow는 무시하지 않습니다. LLM은 요약, 줄바꿈, 항목 선별, 글자 크기 조정 가능 여부를 판단하고 개발-time visual check로 회귀를 확인합니다.

---

## 4. 의존성

```txt
# requirements.txt
openai>=1.0.0          # OpenRouter 호환 (OpenAI SDK 사용)
daytona-sdk>=0.21.0    # Daytona Python SDK (최신)
```

---

## 5. 모듈별 구현 상세

### 5-1. config.py

```python
import os

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "anthropic/claude-sonnet-4-20250514"

DAYTONA_API_KEY = os.getenv("DAYTONA_API_KEY")

TEMPLATES_DIR = "templates"   # 템플릿 .pptx 파일들이 있는 디렉토리
DEFAULT_TEMPLATE = "modern"   # template_id 미지정 시 기본값

MAX_TURNS = 30          # 무한루프 방지
COMMAND_TIMEOUT = 60    # 단일 명령어 타임아웃 (초)
```

---

### 5-2. llm.py — OpenRouter 클라이언트

```python
from openai import OpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL

client = OpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=OPENROUTER_API_KEY,
)

def call_llm(messages: list, tools: list) -> dict:
    """OpenRouter에 tool use 요청. OpenAI SDK 호환."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=tools,
    )
    return response.choices[0]
```

> **OpenRouter 공식 문서 기준:**
> - OpenAI Chat Completions API 100% 호환
> - `tools` 파라미터로 function 정의
> - 응답에서 `message.tool_calls` 배열로 tool call 반환
> - `finish_reason`: `"stop"` (종료) / `"tool_calls"` (tool 사용)

---

### 5-3. sandbox.py — Daytona 샌드박스 관리

```python
from daytona import Daytona, CreateSandboxFromSnapshotParams
from config import DAYTONA_API_KEY, COMMAND_TIMEOUT
import os

daytona_client = Daytona(api_key=DAYTONA_API_KEY)


def create_sandbox(template_id: str):
    """샌드박스 생성 + 선택된 템플릿/스크립트 업로드"""
    import os
    from config import TEMPLATES_DIR

    # 샌드박스 생성 (Python 이미지 기반)
    sandbox = daytona_client.create(
        CreateSandboxFromSnapshotParams(
            snapshot="default-python"  # 또는 커스텀 스냅샷
        )
    )

    # 필요한 패키지 설치
    sandbox.process.exec("pip install python-pptx lxml Pillow", timeout=COMMAND_TIMEOUT)

    # 작업 디렉토리 생성
    sandbox.process.exec("mkdir -p /home/user/scripts/office")

    # 스크립트 업로드
    scripts_to_upload = [
        ("skills/scripts/office/unpack.py", "/home/user/scripts/office/unpack.py"),
        ("skills/scripts/office/pack.py",   "/home/user/scripts/office/pack.py"),
        ("skills/scripts/build_ppt.py",     "/home/user/scripts/build_ppt.py"),
        ("skills/scripts/thumbnail.py",     "/home/user/scripts/thumbnail.py"),
    ]

    for local_path, remote_path in scripts_to_upload:
        with open(local_path, "rb") as f:
            sandbox.fs.upload_file(f.read(), remote_path)

    # 선택된 템플릿 업로드 (template_id → 파일명 매핑)
    template_path = os.path.join(TEMPLATES_DIR, f"{template_id}.pptx")
    meta_path     = os.path.join(TEMPLATES_DIR, f"{template_id}.json")

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"템플릿을 찾을 수 없습니다: {template_path}")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(
            f"메타데이터 JSON이 없습니다: {meta_path}\n"
            f"'python tools/analyze_template.py {template_path}' 를 먼저 실행하세요."
        )

    with open(template_path, "rb") as f:
        sandbox.fs.upload_file(f.read(), "/home/user/template.pptx")

    # 슬라이드 메타데이터는 샌드박스에 업로드하지 않음
    # → prompts.py에서 읽어서 시스템 프롬프트에 직접 주입

    return sandbox


def exec_command(sandbox, command: str) -> dict:
    """샌드박스에서 명령어 실행 후 결과 반환"""
    response = sandbox.process.exec(command, timeout=COMMAND_TIMEOUT)
    return {
        "stdout": response.stdout or "",
        "stderr": response.stderr or "",
        "exit_code": response.exit_code,
    }


def download_result(sandbox, path="/home/user/output.pptx") -> bytes:
    """완성된 PPT 파일 다운로드"""
    return sandbox.fs.download_file(path)


def cleanup(sandbox):
    """샌드박스 정리"""
    sandbox.delete()
```

> **Daytona 공식 문서 기준 (v0.21+):**
> - `from daytona import Daytona` (패키지명 변경됨, 구 `daytona_sdk`)
> - `sandbox.process.exec(command)` → `stdout`, `stderr`, `exit_code` 반환
> - `sandbox.fs.upload_file(source: bytes, destination: str)` — bytes 또는 로컬 경로
> - `sandbox.fs.download_file(path)` → bytes 반환
> - Snapshot 기반 생성: `CreateSandboxFromSnapshotParams`

---

### 5-4. tools.py — Tool 정의 & 실행

```python
from sandbox import exec_command

# LLM에게 알려줄 Tool 스펙
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_bash",
            "description": (
                "샌드박스 환경에서 bash 명령어를 실행합니다. "
                "python 스크립트 실행, 파일 읽기/쓰기, 디렉토리 조작 등 가능합니다. "
                "한 번에 하나의 명령어만 실행하세요. "
                "PPTX OOXML의 구조적 편집은 sed 대신 Python/lxml 스크립트를 우선 사용하세요. "
                "긴 출력이 예상되면 head/tail로 제한하세요."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "실행할 bash 명령어"
                    }
                },
                "required": ["command"]
            }
        }
    }
]


def handle_tool_call(tool_name: str, tool_input: dict, sandbox) -> str:
    """Tool 실행 후 결과를 문자열로 반환"""

    if tool_name == "execute_bash":
        result = exec_command(sandbox, tool_input["command"])

        output_parts = []
        if result["stdout"]:
            output_parts.append(result["stdout"])
        if result["stderr"]:
            output_parts.append(f"[STDERR] {result['stderr']}")
        if result["exit_code"] != 0:
            output_parts.append(f"[EXIT CODE] {result['exit_code']}")

        output = "\n".join(output_parts) if output_parts else "(실행 완료, 출력 없음)"

        # 토큰 절약: 너무 긴 출력은 잘라냄
        if len(output) > 10000:
            output = output[:5000] + "\n\n... (truncated) ...\n\n" + output[-3000:]

        return output

    return f"[ERROR] Unknown tool: {tool_name}"
```

---

### 5-5. prompts.py — 시스템 프롬프트

```python
import json


def build_system_prompt(portfolio_data: dict, template_id: str) -> str:
    with open("skills/SKILL.md", "r") as f:
        skill_md = f.read()
    with open("skills/editing.md", "r") as f:
        editing_md = f.read()

    # 템플릿 메타데이터 로드
    meta_path = f"templates/{template_id}.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        template_meta = json.load(f)

    return f"""당신은 PPT 생성 전문 에이전트입니다.

## 사용 가능한 스킬 문서

<skill_reference>
{skill_md}
</skill_reference>

<editing_reference>
{editing_md}
</editing_reference>

## 작업 환경

- 작업 디렉토리: /home/user/
- 템플릿 파일: /home/user/template.pptx
- 스크립트:
  - /home/user/scripts/office/unpack.py — pptx를 XML로 분해
  - /home/user/scripts/office/pack.py   — XML을 pptx로 재조립
  - /home/user/scripts/build_ppt.py     — 슬라이드 선택·복사·조립 헬퍼
  - /home/user/scripts/thumbnail.py     — 미리보기 생성
- 사용 가능: python3, pip, cat, ls 등 기본 bash 도구
- XML 구조 편집은 Python + lxml 스크립트를 우선 사용하세요. sed는 구조적 XML 편집에 사용하지 마세요.

## 템플릿 슬라이드 정보 (사전 분석 완료)

아래 정보는 템플릿 등록 시 사전 분석된 결과입니다. 매 요청마다 재탐색하지 않아도 됩니다.

<template_metadata>
{json.dumps(template_meta, ensure_ascii=False, indent=2)}
</template_metadata>

## 작업 대상 데이터

```json
{json.dumps(portfolio_data, ensure_ascii=False, indent=2)}
```

## 작업 지시

### Phase 1 — 슬라이드 선택 & 조립
1. 위의 슬라이드 메타데이터와 포트폴리오 데이터를 함께 분석하여 필요한 슬라이드 목록을 결정하세요.
   - 각 슬라이드의 `role`과 `description`을 보고 포트폴리오 섹션에 가장 적합한 슬라이드를 고르세요.
   - 같은 슬라이드를 여러 번 써도 됩니다 (예: 프로젝트 3개 → 프로젝트용 슬라이드 3번 복사).
   - 템플릿의 모든 슬라이드를 다 쓸 필요는 없습니다.
2. 템플릿을 unpack하고, `build_ppt.py`를 통해 **새 출력 구조**(`/home/user/output_unpacked/`)를 만드세요.
   - 선택한 슬라이드를 원하는 순서대로 output_unpacked에 복사합니다.
   - presentation.xml의 슬라이드 참조 목록도 함께 업데이트됩니다.

### Phase 2 — 슬라이드별 분석 & 편집
3. output_unpacked의 각 슬라이드에 대해 다음 순서로 작업하세요:
   a. 해당 슬라이드 XML을 직접 읽어 텍스트박스 수·위치·크기 등 구조를 파악합니다.
   b. 포트폴리오 내용을 슬라이드 구조에 맞게 **지능적으로 적응**시킵니다:
      - 내용이 너무 길면 → 핵심만 남기도록 요약
      - 항목 수가 슬라이드 칸 수와 다르면 → 우선순위 기준으로 선별 또는 재구성
      - 텍스트박스가 넘칠 것 같으면 → 글자 수를 줄이거나 줄바꿈 조정
    c. 결정한 내용으로 XML을 편집합니다. 구조적 XML 편집은 Python/lxml 스크립트를 작성해 실행하세요.
    d. XML 구조를 절대 깨뜨리지 마세요.

### Phase 3 — 완료
4. `pack.py`로 output_unpacked를 `/home/user/output.pptx`로 재조립하세요.
5. pack 이후 validation 스크립트를 실행하고, 통과한 경우에만 완료로 판단하세요.

## 규칙

- 한 번에 하나의 명령어만 실행하세요.
- 단순 텍스트 치환이 아닌, 내용을 슬라이드에 맞게 판단해서 편집하세요.
- slide XML, rels, presentation 구조를 직접 확인한 뒤 편집하세요.
- 구조적 XML 변경은 Python/lxml 기반 안전 스크립트로 수행하세요.
- sed는 로그 확인이나 단순 비구조 텍스트 처리에는 사용할 수 있지만, OOXML 구조 편집에는 사용하지 마세요.
- 작업이 완료되면 "작업 완료" 메시지를 텍스트로 응답하세요. (tool 호출 없이)
"""
```

---

### 5-6. runner.py — 에이전트 루프 (핵심)

```python
import json
from llm import call_llm
from sandbox import create_sandbox, download_result, cleanup
from tools import TOOLS, handle_tool_call
from prompts import build_system_prompt
from config import MAX_TURNS


def run_ppt_agent(portfolio_data: dict, template_id: str = DEFAULT_TEMPLATE) -> bytes:
    """
    포트폴리오 데이터 → PPT 파일(bytes) 반환

    Args:
        portfolio_data: 포트폴리오 JSON 데이터
        template_id: 사용할 템플릿 이름 (templates/{template_id}.pptx)

    전체 에이전트 흐름:
    1. 샌드박스 생성 + 선택된 템플릿 업로드
    2. LLM ↔ 샌드박스 루프
    3. 결과 다운로드
    """

    # 1. 샌드박스 준비
    sandbox = create_sandbox(template_id)

    try:
        # 2. 메시지 초기화
        messages = [
            {"role": "system", "content": build_system_prompt(portfolio_data, template_id)},
            {"role": "user", "content": "포트폴리오 PPT를 생성해주세요."},
        ]

        # 3. 에이전트 루프
        for turn in range(MAX_TURNS):

            # LLM 호출
            choice = call_llm(messages, TOOLS)
            message = choice.message

            # --- 종료 조건 ---
            if choice.finish_reason == "stop":
                # LLM이 tool을 더 이상 호출하지 않음 = 작업 완료
                break

            # --- Tool Call 처리 ---
            if message.tool_calls:
                # assistant 메시지 기록
                messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                })

                # 각 tool call 실행
                for tc in message.tool_calls:
                    tool_input = json.loads(tc.function.arguments)
                    result = handle_tool_call(tc.function.name, tool_input, sandbox)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

        # 4. 결과 다운로드
        pptx_bytes = download_result(sandbox)
        return pptx_bytes

    finally:
        # 5. 항상 샌드박스 정리
        cleanup(sandbox)
```

> **Runner 안전성 원칙:** MVP도 agent loop + tool execution 구조를 유지합니다. 대신 각 turn의 입력/출력, 실행 command, 변경된 파일, validation 결과를 기록해 관측 가능하게 만들고, 실패 시 이전 산출물로 rollback하거나 제한된 retry를 수행할 수 있어야 합니다.

---

## 5-7. 에이전트 Turn-by-Turn 흐름 예시

실제로 에이전트가 동작할 때의 대화 흐름입니다.

```
═══ Phase 1: 슬라이드 선택 & 조립 ═══
# 메타데이터가 이미 프롬프트에 주입되어 있으므로 탐색 없이 바로 선택

Turn 1:
  LLM → "메타데이터 확인: slide1=cover, slide2=toc, slide5=content_text_image ...
         포트폴리오 분석: 표지1 + 목차1 + 프로젝트2개 + 스킬1 + 연락처1
         → 슬라이드 순서: 1, 2, 5, 5, 7, 8 선택"
       → tool_call: execute_bash("python3 scripts/office/unpack.py template.pptx template_unpacked/")
  샌드박스 → "Unpacked successfully"

Turn 2:
       → tool_call: execute_bash("python3 scripts/build_ppt.py \
            --template template_unpacked/ \
            --slides 1,2,5,5,7,8 \
            --output output_unpacked/")
  샌드박스 → "Built output structure with 6 slides"
  # slide5 두 번 → 프로젝트 슬라이드 2장

═══ Phase 2: 슬라이드별 분석 & 편집 ═══
# 각 슬라이드 편집 전, 해당 XML을 직접 읽어 구조 파악 후 지능적으로 편집

Turn 3:
  LLM → "slide1.xml (표지) XML 구조 확인"
       → tool_call: execute_bash("cat output_unpacked/ppt/slides/slide1.xml")
  샌드박스 → (XML 내용 — 텍스트박스 3개 확인)

Turn 4:
  LLM → "표지 편집: 이름·직함·소개 삽입"
       → tool_call: execute_bash("python3 -c \"...\"")

Turn 5:
  LLM → "slide3.xml (프로젝트1) XML 구조 확인"
       → tool_call: execute_bash("cat output_unpacked/ppt/slides/slide3.xml")
  샌드박스 → (XML 내용 — 텍스트박스 구조 파악)

Turn 6:
  LLM → "프로젝트 설명이 텍스트박스보다 길어 3줄로 요약 후 삽입"
       → tool_call: execute_bash("python3 -c \"...\"")
  # 단순 치환이 아닌 — 내용을 슬라이드에 맞게 판단해서 편집

Turn 7~N:
  LLM → 나머지 슬라이드 동일하게 (XML 확인 → 판단 → 편집) 반복

═══ Phase 3: 완료 ═══

Turn N+1:
  LLM → "pack하여 output.pptx로 저장하겠습니다"
       → tool_call: execute_bash("python3 scripts/office/pack.py output_unpacked/ output.pptx")
  샌드박스 → "Packed successfully"

Turn N+2:
  LLM → "포트폴리오 PPT가 성공적으로 생성되었습니다."
       → finish_reason: "stop"

루프 종료 → output.pptx 다운로드
```

> **`build_ppt.py` 역할:**
> - 템플릿 unpacked 디렉토리에서 지정한 슬라이드 인덱스를 순서대로 output에 복사
> - 같은 인덱스 중복 지정 가능 (→ 같은 레이아웃 여러 장 생성)
> - `presentation.xml`의 슬라이드 참조 목록 자동 업데이트
> - 슬라이드 레이아웃/테마 파일도 함께 복사

---

## 6. 서비스 통합 예시 (FastAPI)

### 테스트용 포트폴리오 데이터 예시

```python
portfolio_example = {
    "name": "김개발",
    "title": "풀스택 개발자",
    "summary": "5년차 웹 개발자입니다.",
    "projects": [
        {
            "name": "커머스 플랫폼",
            "description": "React + Node.js 기반 이커머스 서비스",
            "period": "2023.03 - 2024.01",
            "tech_stack": ["React", "Node.js", "PostgreSQL"],
            "achievements": ["MAU 10만 달성", "주문 처리 속도 3배 개선"]
        },
        {
            "name": "사내 어드민",
            "description": "운영팀을 위한 백오피스 시스템",
            "period": "2022.06 - 2023.02",
            "tech_stack": ["Vue.js", "FastAPI", "MongoDB"],
            "achievements": ["수작업 80% 자동화"]
        }
    ],
    "skills": ["TypeScript", "Python", "AWS", "Docker"],
    "contact": {
        "email": "dev@example.com",
        "github": "github.com/devkim"
    }
}
```

### FastAPI 엔드포인트

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from agent.runner import run_ppt_agent
from io import BytesIO

app = FastAPI()


@app.post("/api/portfolio/generate-ppt")
async def generate_ppt(user_id: str, template_id: str = DEFAULT_TEMPLATE):
    """
    Args:
        user_id: 포트폴리오 소유자 ID
        template_id: 사용할 템플릿 이름 (예: "modern", "classic", "minimal")
                     templates/{template_id}.pptx 파일이 존재해야 함
    """
    # 1. DB에서 포트폴리오 데이터 조회
    portfolio_data = get_portfolio_from_db(user_id)

    if not portfolio_data:
        raise HTTPException(404, "포트폴리오를 찾을 수 없습니다.")

    # 2. PPT 생성 (선택된 템플릿으로)
    try:
        pptx_bytes = run_ppt_agent(portfolio_data, template_id=template_id)
    except FileNotFoundError as e:
        raise HTTPException(400, f"템플릿 없음: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"PPT 생성 실패: {str(e)}")

    # 3. 파일 반환
    return StreamingResponse(
        BytesIO(pptx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename=portfolio_{user_id}.pptx"},
    )
```

---

### 6-1. UX/API 범위

MVP UX는 단순 다운로드 API만으로 두지 않고, 생성 요청자가 결과를 확인할 수 있는 기본 흐름까지 포함합니다.

| 기능 | 범위 |
|------|------|
| **템플릿 카탈로그** | 사용 가능한 `template_id`, 이름, 설명, 대표 썸네일/미리보기 제공 |
| **템플릿 preview** | 템플릿 등록 시 생성한 썸네일 또는 PDF/image preview를 노출 |
| **job status/progress** | 생성 요청을 job으로 관리하고 `queued/running/validating/succeeded/failed` 등 상태와 현재 단계 표시 |
| **web preview** | 생성된 PPT를 PDF 또는 slide image로 변환해 브라우저에서 확인 가능하게 제공 |
| **friendly errors** | 내부 exception/log를 그대로 노출하지 않고, 템플릿 없음·validation 실패·시간 초과 등 사용자가 이해 가능한 메시지로 변환 |

부분 재생성, 특정 슬라이드 직접 편집, 생성 후 인터랙티브 수정 UI는 이번 범위에서 제외합니다. 먼저 전체 자동 생성 + preview + download 흐름을 안정화한 뒤 별도 단계로 다룹니다.

---

## 7. 에러 핸들링 & 안전장치

Validation은 두 층으로 나눕니다.

| 구분 | 시점 | 목적 |
|------|------|------|
| **런타임 validation** | 사용자 요청마다 `pack.py` 실행 후, 결과 반환 전 | 깨진 PPTX가 사용자에게 전달되는 것을 차단 |
| **개발-time validation** | 템플릿/스크립트/프롬프트 변경 시 | 샘플 포트폴리오와 템플릿 조합에서 품질 회귀를 조기에 발견 |

런타임 validation은 가능한 한 자동화하고, 실패하면 사용자에게 friendly error를 반환하며 내부 로그에는 실패 단계와 파일 상태를 남깁니다.

| 런타임 검사 | 설명 |
|------------|------|
| **파일 존재/크기** | `/home/user/output.pptx` 존재 여부와 0 byte 여부 확인 |
| **zip/pptx 구조** | zip으로 열리는지, `[Content_Types].xml`, `ppt/presentation.xml`, `ppt/slides/*.xml` 등 필수 파일이 있는지 확인 |
| **XML well-formedness** | practical한 범위에서 slide XML, rels, presentation XML을 `lxml`로 parse |
| **python-pptx load** | `Presentation('/home/user/output.pptx')`로 로드 가능한지 확인 |
| **PDF/image 변환** | LibreOffice/headless 또는 별도 변환기로 PDF/images를 생성해 preview와 시각 검수 기반 확보 |

개발-time validation은 샘플 포트폴리오, 다양한 템플릿, 이미지 포함/미포함 케이스, 긴 한국어 텍스트 케이스를 포함해야 합니다. 생성 결과는 자동 검사뿐 아니라 visual quality check로 레이아웃 붕괴, 텍스트 overflow, 이미지 깨짐, 폰트 fallback 문제를 확인합니다.

```python
# runner.py에 추가할 방어 로직

class PPTGenerationError(Exception):
    pass


def validate_output_pptx(sandbox, path="/home/user/output.pptx"):
    """pack 이후, 사용자 반환 전에 실행하는 런타임 validation."""
    commands = [
        f"test -s {path}",
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "from zipfile import ZipFile\n"
        "from lxml import etree\n"
        "from pptx import Presentation\n"
        "path = Path('/home/user/output.pptx')\n"
        "with ZipFile(path) as z:\n"
        "    names = set(z.namelist())\n"
        "    required = {'[Content_Types].xml', 'ppt/presentation.xml'}\n"
        "    missing = required - names\n"
        "    if missing:\n"
        "        raise RuntimeError(f'missing pptx parts: {missing}')\n"
        "    slide_names = sorted(n for n in names if n.startswith('ppt/slides/slide') and n.endswith('.xml'))\n"
        "    if not slide_names:\n"
        "        raise RuntimeError('no slide XML files')\n"
        "    for name in ['ppt/presentation.xml', *slide_names]:\n"
        "        etree.fromstring(z.read(name))\n"
        "Presentation(str(path))\n"
        "PY",
        # preview 생성까지 통과해야 웹 미리보기와 최종 반환을 허용
        "python3 scripts/thumbnail.py /home/user/output.pptx /home/user/preview/",
    ]

    for command in commands:
        result = sandbox.process.exec(command, timeout=COMMAND_TIMEOUT)
        if result.exit_code != 0:
            raise PPTGenerationError(result.stderr or result.stdout or "PPT validation failed")


def run_ppt_agent(portfolio_data: dict) -> bytes:
    sandbox = create_sandbox()

    try:
        messages = [...]

        for turn in range(MAX_TURNS):
            try:
                choice = call_llm(messages, TOOLS)
            except Exception as e:
                # LLM API 에러 → 재시도 1회
                choice = call_llm(messages, TOOLS)

            message = choice.message

            if choice.finish_reason == "stop":
                break

            if message.tool_calls:
                # ... tool call 처리 ...
                pass

        else:
            # MAX_TURNS 초과
            raise PPTGenerationError("최대 턴 수 초과. 생성 실패.")

        # pack 이후, 사용자 반환 전 런타임 validation
        validate_output_pptx(sandbox)

        return download_result(sandbox)

    finally:
        cleanup(sandbox)
```

---

## 8. 성능 & 비용 최적화

| 전략 | 방법 |
|------|------|
| **템플릿 메타데이터 사전 분석** | 등록 시 1회만 LLM 분석 → JSON 저장 → 이후 모든 요청에서 재사용 (탐색 turn 0개로 좋임) |
| **스냅샷 사용** | pip install 등 환경 세팅이 된 스냅샷을 미리 만들어두면 샌드박스 생성 시간 단축 |
| **출력 truncation** | XML cat 결과가 길면 잘라서 토큰 절약 |
| **모델 선택** | 단순한 포트폴리오면 `claude-haiku` 등 저렴한 모델도 가능 |
| **캐싱** | 동일 포트폴리오 데이터면 결과물 캐싱 |
| **타임아웃** | 전체 프로세스 타임아웃 (예: 3분) 설정 |
| **PDF/image 변환 비용 관리** | preview 변환은 필수 validation 경로에 포함하되, 변환 산출물 캐싱·해상도 제한·비동기 job 처리로 지연을 완화 |
| **런타임 validation 오버헤드 관리** | 빠른 구조 검사와 무거운 시각 preview 변환 단계를 분리해 progress에 노출하고 timeout을 별도 설정 |
| **폰트/overflow 사전 대응** | 한국어 폰트가 포함된 스냅샷 사용, 긴 텍스트 샘플로 템플릿별 overflow 기준을 검증 |

---

## 9. Daytona 스냅샷 사전 준비 (권장)

매번 `pip install`하면 느리니까, 커스텀 스냅샷을 만들어두는 걸 추천:

```python
from daytona import Daytona, CreateSnapshotParams

daytona = Daytona()

# 한 번만 실행하여 스냅샷 생성
snapshot = daytona.snapshot.create(
    CreateSnapshotParams(
        image="python:3.11-slim",
        entrypoint="sleep infinity",
        # 또는 Dockerfile로 python-pptx, lxml 등 사전 설치
    )
)

# 이후 sandbox 생성 시 이 스냅샷 사용
# CreateSandboxFromSnapshotParams(snapshot=snapshot.id)
```

---

## 10. 구현 순서 (Part-based)

정확한 일 단위 일정은 템플릿 품질, 변환 도구 선택, 샌드박스 준비 상태에 따라 크게 달라질 수 있으므로 primary plan으로 두지 않습니다. 구현은 다음 part 단위로 쪼개고, 각 part마다 동작 산출물과 validation을 확인합니다.

| Part | 목표 | 주요 산출물 |
|------|------|-------------|
| **Part 1. PPTX Skill baseline** | Claude PPTX Skill 스타일의 unpack/inspect/edit/pack 흐름을 로컬에서 재현 | `unpack.py`, `pack.py`, Python/lxml 편집 예제, 샘플 PPTX round-trip 테스트 |
| **Part 2. 템플릿/조립 기반** | 템플릿 카탈로그와 슬라이드 선택·복사·조립 구조 준비 | 템플릿 `.pptx/.json`, `analyze_template.py`, `build_ppt.py`, 중복 슬라이드 복사 테스트 |
| **Part 3. Agent runner** | OpenRouter tool calling + Daytona command execution loop 구현 | `runner.py`, `tools.py`, `prompts.py`, turn/state logging, command timeout |
| **Part 4. 안전한 편집/validation** | XML 편집 guardrail과 런타임 validation 추가 | Python/lxml 편집 규칙, output validation, rollback/retry 기준, preview 변환 |
| **Part 5. 서비스/UX 통합** | API, job status, template preview, output preview/download 연결 | FastAPI endpoint, job 상태 API, friendly error, PDF/image preview |
| **Part 6. 품질 검증/운영화** | 샘플 포트폴리오와 다양한 템플릿으로 visual quality 회귀 확인 | 이미지/미디어 케이스, 한국어 폰트, 긴 텍스트 overflow 체크리스트, 성능 측정 |

---

## 11. 리스크 & 대응

| 리스크 | 확률 | 대응 |
|--------|------|------|
| LLM이 XML 깨뜨림 | 중 | 프롬프트에 "python 스크립트로 편집하라" 강조 + pack 후 validation |
| 무한 루프 | 하 | MAX_TURNS + 전체 타임아웃 |
| Daytona 냉시작 느림 | 중 | 스냅샷 사전 준비로 해결 |
| 토큰 비용 폭증 | 중 | XML 출력 truncation + 저렴 모델 옵션 |
| 템플릿 복잡도 | 상황별 | 슬라이드마다 역할이 명확한 레이아웃 구성 + 플레이스홀더 텍스트 명확히 (`{{name}}` 등) |
| LLM이 슬라이드 타입 오판 | 중 | 메타데이터 JSON에 `description`·`recommended_for` 명확히 작성, 필요시 슬라이드 노트로 힌트 보완 |
| 템플릿 수정 후 메타데이터가 취소(stale)됨 | 중 | .pptx 수정 시는 반드시 `analyze_template.py` 재실행 규칙화. 또는 .pptx·.json 수정 시간 기록을 비교하여 경고 |
| 동일 템플릿 슬라이드 중복 복사 시 관계 파일 오류 | 중 | `build_ppt.py`에서 slide rels 파일도 함께 복사하고 ID 충돌 방지 처리 |
| 이미지/미디어 관계 파일 누락 | 중 | slide XML뿐 아니라 `ppt/slides/_rels/*.rels`, `ppt/media/*` 복사와 참조 경로를 validation에 포함 |
| 한국어 폰트 fallback/깨짐 | 중 | 샌드박스와 변환 환경에 한국어 폰트 설치, 템플릿 폰트 지정, PDF/image preview로 확인 |
| 텍스트 overflow | 높음 | 긴 한국어 샘플로 개발-time visual check 수행, 프롬프트에 요약/줄바꿈/우선순위 선별 규칙 강화 |
| PDF/image 변환 비용 증가 | 중 | 변환 timeout, 해상도 제한, preview 캐싱, 비동기 job progress로 사용자 대기 체감 완화 |
| 런타임 validation 오버헤드 | 중 | 빠른 구조 검사와 무거운 preview 변환을 단계화하고, 실패 위치를 job status에 기록 |

---

## 12. 핵심 개념 한눈에 정리

| 개념 | 설명 |
|------|------|
| **Tool 정의** | JSON 스펙일 뿐. LLM에게 "이런 함수 쓸 수 있어"라고 알려주는 것 |
| **Tool 실행** | LLM이 호출하면 실제 코드가 샌드박스에서 명령어를 실행 |
| **에이전트 루프** | `while` + LLM 호출 + tool 실행 + 결과 전달 반복 |
| **종료 조건** | `finish_reason == "stop"` = LLM이 tool을 더 이상 안 부름 |
| **안전장치** | `MAX_TURNS`로 무한루프 방지, 출력 truncation으로 토큰 절약 |

---

---

# [관리도구] 템플릿 등록 가이드

> ⚠️ **이 섹션은 에이전트 런타임과 완전히 무관합니다.**  
> 개발자 또는 운영자가 새 템플릿을 추가하거나 기존 템플릿을 수정할 때  
> **로컬 환경에서 별도로 실행**하는 1회성 CLI 작업입니다.  
> 서비스 API 흐름에 포함되지 않으며, 에이전트 tool로 등록되지 않습니다.

---

## T-1. 역할 & 위치

```
에이전트 런타임 (서비스 요청마다 실행)
┌─────────────────────────────────┐
│  FastAPI → runner → sandbox     │
│  prompts.py가 .json 읽어서 주입  │  ← .json은 이미 존재해야 함
└─────────────────────────────────┘

                 ↑ 의존

템플릿 관리 도구 (개발자/운영자가 수동 실행)
┌─────────────────────────────────┐
│  tools/analyze_template.py      │
│  .pptx 읽기 → LLM 분석 → .json │  ← 이 섹션에서 다루는 부분
└─────────────────────────────────┘
```

| 항목 | 내용 |
|------|------|
| **실행 주체** | 개발자 / 운영자 |
| **실행 시점** | 새 `.pptx` 추가 시, 또는 기존 `.pptx` 수정 후 |
| **실행 환경** | 로컬 머신 (샌드박스 불필요) |
| **출력물** | `templates/{template_id}.json` — 이후 서비스가 이 파일을 읽음 |
| **런타임 개입** | 없음 |

---

## T-2. 사용법

```bash
# 새 템플릿 등록
python tools/analyze_template.py templates/modern.pptx

# 템플릿 수정 후 재분석
python tools/analyze_template.py templates/modern.pptx

# 여러 템플릿 일괄 처리 (선택)
for f in templates/*.pptx; do
    python tools/analyze_template.py "$f"
done
```

출력 예시:
```
[1/8] slide1.xml 분석 중...
[2/8] slide2.xml 분석 중...
...
✓ Saved: templates/modern.json
```

---

## T-3. `tools/analyze_template.py` 구현

```python
"""
개발자/운영자 전용 CLI 도구.
새 템플릿 .pptx를 등록하거나 기존 템플릿 수정 후 메타데이터를 갱신할 때 실행.

사용법: python tools/analyze_template.py templates/modern.pptx
출력:   templates/modern.json
"""
import sys, json, datetime, tempfile, shutil
from pathlib import Path
from openai import OpenAI

# 로컬에서 실행하므로 skills 경로를 직접 임포트
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "scripts" / "office"))
from unpack import unpack_pptx  # skills/scripts/office/unpack.py 재활용

LLM_CLIENT = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=...)


def call_llm_for_slide_analysis(index: int, xml: str) -> dict:
    """슬라이드 XML → 메타데이터 dict 변환 (LLM 1회 호출)
    
    등록 시에는 슬라이드 선택(라우팅)에 필요한 정보만 추출.
    편집 제약(텍스트박스 크기 등)은 생성 시 LLM이 XML을 직접 보고 판단.
    """
    prompt = f"""
아래는 PowerPoint 슬라이드의 XML입니다 (슬라이드 인덱스: {index}).
이 슬라이드가 어떤 종류의 슬라이드인지 파악하여 다음 JSON 형식으로만 응답하세요:

{{
  "index": {index},
  "role": "(cover | toc | section_divider | content_text | content_text_image | content_list | skills_grid | closing 중 하나)",
  "description": "한 줄 설명 — 레이아웃 특징 위주 (예: '좌우 분할, 좌측 텍스트 영역 + 우측 이미지 영역')"
}}

세부 편집 정보(텍스트박스 ID, 크기, placeholder 좌표 등)는 추출하지 않아도 됩니다.
슬라이드를 '어떤 용도로 쓸 수 있는가'를 한눈에 파악할 수 있는 수준이면 충분합니다.

<slide_xml>
{xml[:8000]}
</slide_xml>
"""
    response = LLM_CLIENT.chat.completions.create(
        model="anthropic/claude-sonnet-4-20250514",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def analyze(pptx_path: str):
    template_id = Path(pptx_path).stem
    tmp = tempfile.mkdtemp()
    try:
        # 1. unpack
        unpack_pptx(pptx_path, tmp)

        # 2. 슬라이드 XML 수집 (번호순 정렬)
        slides_dir = Path(tmp) / "ppt" / "slides"
        slide_files = sorted(
            slides_dir.glob("slide[0-9]*.xml"),
            key=lambda p: int(p.stem.replace("slide", ""))
        )

        # 3. 슬라이드별 LLM 분석
        slides_meta = []
        for i, sf in enumerate(slide_files, start=1):
            print(f"[{i}/{len(slide_files)}] {sf.name} 분석 중...")
            xml_content = sf.read_text(encoding="utf-8")
            analysis = call_llm_for_slide_analysis(index=i, xml=xml_content)
            slides_meta.append(analysis)

        # 4. JSON 저장
        meta = {
            "template_id": template_id,
            "analyzed_at": datetime.datetime.utcnow().isoformat() + "Z",
            "source_file": Path(pptx_path).name,
            "total_slides": len(slides_meta),
            "slides": slides_meta,
        }
        out_path = Path(pptx_path).with_suffix(".json")
        out_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ Saved: {out_path}")

    finally:
        shutil.rmtree(tmp)  # 임시 디렉토리 항상 정리


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python tools/analyze_template.py templates/<name>.pptx")
        sys.exit(1)
    analyze(sys.argv[1])
```

---

## T-4. 출력 JSON 포맷 (`templates/modern.json`)

```json
{
  "template_id": "modern",
  "analyzed_at": "2025-01-15T10:00:00Z",
  "total_slides": 8,
  "slides": [
    {
      "index": 1,
      "role": "cover",
      "description": "표지. 중앙 상단 이름, 하단 직함·소개 텍스트 영역, 우측 이미지 영역."
    },
    {
      "index": 2,
      "role": "toc",
      "description": "목차. 섹션 제목을 세로로 나열하는 리스트 레이아웃."
    },
    {
      "index": 5,
      "role": "content_text_image",
      "description": "좌우 분할. 좌측 제목+본문 텍스트 영역, 우측 이미지 영역."
    }
  ]
}
```

---

## T-5. 언제 재실행해야 하나?

| 상황 | 재실행 필요 여부 |
|------|------------------|
| 새 `.pptx` 추가 | ✅ 반드시 실행 |
| 기존 `.pptx` 슬라이드 레이아웃/내용 수정 | ✅ 반드시 실행 |
| 기존 `.pptx` 텍스트 내용만 미세 조정 | 권장 (레이아웃 변화 없으면 생략 가능) |
| 서비스 배포 / 코드 변경만 | ❌ 불필요 |

> `.pptx`와 `.json`의 수정 시각을 비교하여 stale 여부를 경고하는 로직을 `sandbox.py`에 추가하면 실수를 예방할 수 있습니다.
