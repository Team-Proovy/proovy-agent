# Phase A — VideoNode 골격 + 동기 PoC 호출 (설계 Phase A)

> 매핑: 설계 문서 `docs/architecture/video-generation-design.md §7`의 **Phase A** = 본 `specs/phase-1`.

## Purpose
워커·크레딧 인프라 없이 메인 그래프에 VideoNode를 끼우고 노드 안에서 영상 파이프라인을 inline으로 직접 호출해, 샘플 문제 1건이 실제 mp4까지 가는 end-to-end를 검증한다.

## Requirements
- CoreSolver Phase 1을 `create_agent`(tools=[code_generate, code_execute], max_iter=5, `before_model` trim)로 리워크하고, code/stdout을 `state.messages`에 풀텍스트로 영구 저장하며 마지막 메시지를 "단계+수식+답" 프로즈 + `kind="verified_solution"` 태깅으로 유도한다 (ADR 0001/0006).
- `features/video/`에 모델 5종(`models.py`)·예외(`exceptions.py`)·hint_extractor 2-step(Stage 1a 라우팅 Flash / 1b 추출 Sonnet / Step 2 VideoHints Flash)·파이프라인을 신규 구현한다 (PoC 이식 금지, 검증된 내용만 참조).
- 파이프라인은 처음부터 `VisualTypeRegistry` 통합 구조(core 5필드)와 stage 함수 5개 + `StageContext`로 작성하고, Phase A visual_type은 deterministic 템플릿 소수(`intro_problem`/`equation_write`/`equation_derivation`/`highlight_result`/`outro_summary`)만 둔다.
- `graph/state.py`에 `explanation_mode`·`hold_id`·`video_jobs: list[VideoJobRef]`를 추가하고 죽은 `reservation_id`/`credit_reserved`를 제거하며, Planner가 `explanation_mode`(full/brief)를 분류하도록 한다.
- `graph/nodes/video.py`를 임시 inline 스캐폴드(`inline_runner.run_now`)로 두고 Planner/PlanExecutor가 video plan_step을 dispatch하도록 배선한다 (Mode B·격리·크레딧은 Phase B로).

## Approach
설계 §1.5의 CoreSolver 생산 계약을 Phase A의 실질 첫 작업으로 두고, 그 위에 hint_extractor 2-step과 파이프라인을 얹는 의존 순서로 진행한다. 영상 생성은 PoC를 verbatim 이식하지 않고 설계 문서 기준으로 신규 구현하되, 검증된 동작·보수적 기본값(`disable_equation_chain` 등)은 PoC를 참조한다. VideoNode는 검증이 목적이므로 inline runner로 잠시 blocking을 허용하고, manim/TeX/CJK 폰트가 깔린 dev 환경에서 `VIDEO_SANDBOX_BACKEND=none`으로 E2E를 한 번 돌린다. 순수 파서 `solver_adapter`와 재-solve fallback, ffprobe 1초 fallback은 도입하지 않는다.

## Verification
- 한 solve 직후 `state.messages`에 `code_execute.args.code`·stdout ToolMessage·`kind="verified_solution"` AIMessage 셋이 모두 존재한다 (ADR 0006 evidence 회귀 가드).
- hint_extractor 단위 테스트가 Stage 1a 대상 식별 정확도와 Stage 1b 환각 회귀(stdout 숫자가 `final_answer`에 보존)를 통과한다.
- `brief` 모드에서 CoreSolver가 Phase 2 설명을 생략하고 verified_solution을 `display="content"`로 노출한다.
- 샘플 문제 1건 E2E 스모크가 실제 mp4를 GCS에 올리고 결과가 표시되는 것까지 통과한다.
