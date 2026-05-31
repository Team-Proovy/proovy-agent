---
id: "1.10"
phase: 1
title: "VideoNode inline 스캐폴드 + builder 배선 + E2E 스모크"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "82"
depends_on: ["1.02", "1.03", "1.05", "1.07", "1.08", "1.09"]
blocks: ["2.06"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 1.10 — VideoNode inline 스캐폴드 + 배선 + E2E

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#82](https://github.com/Team-Proovy/proovy-agent/issues/82)

## 의존성

- 1.02 (CoreSolver 계약) · 1.03 (Planner explanation_mode) — 입력 생산
- 1.05 (hint_extractor) — verified_solution → SolutionPlan/VideoHints
- 1.07 (scriptify) · 1.08 (템플릿) — 파이프라인 실행 본체
- 1.09 (TTS) — 음성/타임스탬프

## 사전 준비

- [ ] dev 머신에 manim / TeX Live / CJK 폰트 (inline은 메인 프로세스 import)
- [ ] `VIDEO_SANDBOX_BACKEND=none` E2E 설정

## 구현 체크리스트

- [ ] `graph/nodes/video.py` 임시 inline 스캐폴드 (`inline_runner.run_now`, blocking 허용 — throwaway)
- [ ] `graph/builder.py`: Planner video plan_step 인식 + PlanExecutor dispatch (`_DEPENDS_ON_SOLVE` 게이트)
- [ ] 샘플 문제 1건 E2E 스모크 — 실제 mp4가 GCS에 업로드되고 결과 표시

## Definition of Done

- [ ] 샘플 1건이 mp4까지 생성 + 결과 표시 (inline blocking 허용)
- [ ] E2E 스모크 통과

## 리스크 / 메모

- inline runner가 manim/TeX/ffmpeg를 **메인 API 프로세스에서 import** — §5.3 격리 경계의 Phase A 한정 예외(throwaway). Phase B 2.06에서 제거 + 워커 분리
- 이 노드는 5~10분 blocking — Mode B는 2.06에서
