# Phase C — 보안 강화 + 강건화 (설계 Phase C)

> 매핑: 설계 문서 `docs/architecture/video-generation-design.md §7`의 **Phase C** = 본 `specs/phase-3`. 선행: Phase B (`specs/phase-2`).

## Purpose
자유형 `visual_scene`·`graph_plot`을 안전하게 도입하고, AST allowlist 강화·intent-preserving fallback·관측성·TTS 동기로 영상 파이프라인을 강건화한다.

## Requirements
- `code_validator.py`의 AST 거부 검사를 강화하고 자유 영역 import를 화이트리스트(manim/numpy/math만 허용)로 좁히며, smoke render 직전 검증 실패 시 사유를 주입해 LLM 재시도(3회)하도록 한다.
- `graph_plot`의 `func_python` lambda를 제거하고 sympy 기반 expression DSL(`{expr, domain, features[]}`)로 교체하며 기존 호출부를 마이그레이션한다.
- `script_repair.py` intent-preserving fallback을 도입한다: `visual_scene` 3회 실패 시 script_repair LLM이 narration에 맞는 visual_type/params로 재작성 → consistency 검증 → 실패면 `equation_write`/`highlight_result` + SKIPPED.
- OpenTelemetry span(stage 단위)과 메트릭(`render_fallback_rate`·`llm_codegen_failure_rate`·`visual_type_distribution`)을 추가하고, internal/user 2-tier diagnostic을 GCS에 기록하며 user tier를 잡 상태 API로 즉시 조회 가능하게 한다.
- word-timestamp 기반 시각 강조 동기(`common/video/timeline.py`)와 TTS-first 양방향 적응(미세 동작·압축 화이트리스트·narration 길이 band)을 구현한다.

## Approach
`visual_scene`는 제거 대상이 아니라 AST 검증 + smoke render + retry taxonomy + intent-preserving fallback으로 감싸 안전하게 유지하고, 템플릿은 자유형의 대체재가 아니라 품질 하한선·fallback 품질을 높이는 기반으로 둔다. 규칙기반 IntentRouter 대신 script_repair LLM이 더 유연한 fallback을 담당하며, consistency validator는 narration↔화면 일치만 보고 정확성은 hint_extractor의 code+stdout evidence가 담당한다(별개 책임). `func_python` lambda는 정적 검증 불가·보안 결함이라 expression DSL로 대체하고 AST allowlist는 자유 영역에만 적용한다. cross-invocation 캐시·부분 재시도는 재시도가 잦거나 비싸질 때만 검토하고 MVP에서는 제외한다.

## Verification
- AST allowlist가 금지 import/call과 미허가 import를 모두 거부하고, 거부 사유가 prior_errors로 주입되어 LLM 재시도가 동작한다.
- `graph_plot`이 lambda 없이 expression DSL만으로 렌더되고 기존 호출부가 DSL로 마이그레이션되어 동작한다.
- `visual_scene` 실패가 script_repair → consistency 검증을 거쳐 잡 전체 실패 없이 복구되거나 SKIPPED로 안전 처리된다.
- user diagnostic·user-facing 오류 메시지에 API key·raw stderr·생성 코드가 포함되지 않고 `UserErrorCode` enum + 한국어 메시지로만 구성된다 (redaction).
- word-timestamp 동기로 시각 강조가 해당 단어 발화 시점에 정렬된다.
