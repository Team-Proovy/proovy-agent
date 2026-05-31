---
id: "1.01"
phase: 1
title: "state.py 필드 정리 (영상·크레딧 필드 추가, dead 필드 제거)"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "73"
depends_on: []
blocks: ["1.02", "1.03", "2.02"]
estimate: "S"
status: "todo"
owner: ""
sprint: ""
---

# Task 1.01 — state.py 필드 정리

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#73](https://github.com/Team-Proovy/proovy-agent/issues/73)

## 의존성

- 없음 (독립 task — 그래프 state 스키마 토대. 모든 영상·크레딧 작업이 이 필드 위에 섬)

## 사전 준비

- [ ] ADR 0001(verified_solution은 state 필드 아님)·ADR 0004(reservation 폐기) 재확인
- [ ] 기존 checkpoint 스키마와의 호환 영향 파악

## 구현 체크리스트

- [ ] `graph/state.py`에 `explanation_mode: Literal["full","brief"] = "full"` 추가
- [ ] `hold_id: str | None = None` 추가 (Planner plan 단일 hold row id — ADR 0004)
- [ ] `VideoJobRef` 모델 + `video_jobs: Annotated[list[VideoJobRef], add_reducer]` 추가
- [ ] dead `reservation_id` / `credit_reserved` 제거 (ADR 0004로 폐기)
- [ ] state 직렬화 / checkpoint 라운드트립 단위 테스트

## Definition of Done

- [ ] 신규 필드 포함 state가 Pydantic 검증 통과
- [ ] 자동화된 테스트 통과 (직렬화 라운드트립)
- [ ] 기존 thread checkpoint 로드 회귀 없음

## 리스크 / 메모

- dead 필드 제거가 과거 thread checkpoint 로드를 깨지 않는지 확인 (마이그레이션/관용 처리)
- `verified_solution`은 절대 state 필드로 두지 않는다 — messages에 solve마다 적재 (멀티턴)
