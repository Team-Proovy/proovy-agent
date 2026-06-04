---
id: "3.01"
phase: 3
title: "AST allowlist 강화 (code_validator + 화이트리스트 + 재시도 주입)"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "91"
depends_on: ["2.05"]
blocks: ["3.03"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 3.01 — AST allowlist 강화

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#91](https://github.com/Team-Proovy/proovy-agent/issues/91)

## 의존성

- 2.05 (sandbox) — validator는 워커 render 경로의 smoke render 직전에 실행 **[cross-phase]**

## 사전 준비

- [ ] PoC §9.1 거부 리스트 / §8.2 화이트리스트 재확인

## 구현 체크리스트

- [ ] `features/video/code_validator.py`: `_FORBIDDEN_IMPORTS` / `_FORBIDDEN_NAMES` + `_ALLOWED_IMPORT_ROOTS`(manim/numpy/math)
- [ ] smoke render 직전 검증, 실패 시 `prior_errors`에 사유 주입 → LLM 재시도 3회
- [ ] 거부 케이스 단위 테스트 (금지 import/call + 미허가 import)

## Definition of Done

- [ ] 금지/미허가 코드 모두 거부 + 재시도 배선 테스트
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- allowlist가 좁아 정상 manim 패턴을 거부할 수 있음 — 케이스 수집해 화이트리스트 보강
- **`sympy`는 의도적 제외**: graph_plot DSL의 sympy는 워커(트러스트)에서 도므로 allowlist 무관(#3.02), visual_scene(untrusted)엔 `sympify`/`parse_expr` eval성 위험 → 기본 제외, 수요 입증 시 안전 subset만 검토
- AST는 자유 영역(`visual_scene`)에만 적용. deterministic 템플릿/`graph_plot` DSL은 대상 아님
- 2026-06-04 PR #122 review follow-up: Python AST allowlist는 TeX 문자열 자체를
  검증하지 않는다. renderer에서 LaTeX/MathTex 명령 allowlist를 별도로 두기로
  결정했으므로, `\input{}` 등 위험 명령 차단 규칙을 2.05 sandbox audit과
  함께 테스트한다.
