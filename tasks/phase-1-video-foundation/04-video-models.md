---
id: "1.04"
phase: 1
title: "features/video 모델·예외 (Pydantic 계약 + PipelineError)"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "76"
depends_on: []
blocks: ["1.05", "1.06", "2.01"]
estimate: "S"
status: "todo"
owner: ""
sprint: ""
---

# Task 1.04 — features/video 모델·예외

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#76](https://github.com/Team-Proovy/proovy-agent/issues/76)

## 의존성

- 없음 (독립 task — 영상 데이터 계층 토대. hint_extractor·파이프라인·잡 모델이 공유)

## 사전 준비

- [ ] 설계 §2.2 입력 계약(VideoJobInput) / §2.2.1 SolutionPlan / §2.2.2 VideoHints 재확인

## 구현 체크리스트

- [ ] `features/video/models.py`: `SolutionPlan`, `SolutionStep`, `VideoJobInput`, `VideoHints`, `DirectorBriefPolicy`, `VideoOptions`, `UserErrorCode`
- [ ] `features/video/exceptions.py`: `PipelineError` 계열
- [ ] 모델 직렬화 / 검증 단위 테스트

## Definition of Done

- [ ] 모델 import + 검증 테스트 통과
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- SolutionPlan/VideoHints 스키마가 소비처(hint_extractor 1.05·파이프라인 1.06)의 요구와 어긋나지 않게 — 소비 task와 함께 검토
- `visualization_hints`는 SolutionPlan이 아니라 VideoHints 소유 (시각화는 video 소관)
