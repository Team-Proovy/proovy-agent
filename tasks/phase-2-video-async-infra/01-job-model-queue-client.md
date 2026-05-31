---
id: "2.01"
phase: 2
title: "잡 모델(VideoJob)+migration + Cloud Tasks 클라이언트·progress API + 큐/IAM"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "83"
depends_on: ["1.04"]
blocks: ["2.04", "2.06"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 2.01 — 잡 모델 + Cloud Tasks 클라이언트

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#83](https://github.com/Team-Proovy/proovy-agent/issues/83)

## 의존성

- 1.04 (features/video 모델) — `VideoJob`이 `features/video/models.py`를 확장, `VideoJobInput` 재사용 **[cross-phase]**

## 사전 준비

- [ ] GCP 프로젝트 / Cloud Tasks 큐 권한 / OIDC 서비스 계정

## 구현 체크리스트

- [ ] `video_jobs` 테이블 (`progress_updated_at`, `retry_source_job_id` + **UNIQUE partial index**, `cloud_tasks_name`, checkpoint 필드 없음) + alembic
- [ ] `VideoJobClient` Protocol + `CloudRunVideoJobClient` (`create_and_enqueue` / `finalize` / `cancel`)
- [ ] progress write + 조회 API (`api/v1/video_jobs.py`, 기본 2초 hot endpoint)
- [ ] Cloud Tasks 큐 생성 + IAM (OIDC)
- [ ] `user_diagnostic` 매핑 골격 (상세 2-tier는 3.06)

## Definition of Done

- [ ] 잡 생성 → 조회 라운드트립 테스트
- [ ] `retry_source_job_id` unique 제약 테스트 (원본당 재시도 1회)
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- `VideoJobSegment` 테이블은 **Phase D로 미룸** — MVP는 `video_jobs.progress` dict + `internal.json`으로 충분
- `VideoJobClient`는 Protocol 유지 (테스트용 Fake + 향후 Cloud Run Jobs 전환 대비)
