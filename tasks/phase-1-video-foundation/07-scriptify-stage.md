---
id: "1.07"
phase: 1
title: "scriptify stage (LLM 스크립트 생성 + DirectorBriefPolicy 주입)"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "79"
depends_on: ["1.06"]
blocks: ["1.10", "2.04"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 1.07 — scriptify stage

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#79](https://github.com/Team-Proovy/proovy-agent/issues/79)

## 의존성

- 1.06 (파이프라인 스켈레톤) — Registry + StageContext + orchestrator 위에 stage 구현

## 사전 준비

- [ ] 설계 §2.2.2 DirectorBriefPolicy / PoC scriptify 보수적 기본값 확인

## 구현 체크리스트

- [ ] `stage_scriptify`: `SolutionPlan` + `VideoHints` → 세그먼트 스크립트(narration + visual_type + params)
- [ ] `DirectorBriefPolicy`를 scriptify 프롬프트에 주입 (visual_description 품질 유도)
- [ ] 보수적 기본값 유지(`disable_equation_chain` / `disable_prev_scene_state` / `scene_bridge_enabled=false` — PoC 결론, PR 없이 변경 금지)
- [ ] 단위 테스트 (스크립트 구조 + visual_type 유효성)

## Definition of Done

- [ ] SolutionPlan fixture → 유효한 세그먼트 스크립트 생성
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- deterministic enforcer / forbidden_requirements는 MVP 제외 — 위험 코드 차단은 AST(3.01)+sandbox가 hard gate
- Phase A는 deterministic 템플릿만 선택 (visual_scene/graph_plot은 Phase C)
