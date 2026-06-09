---
id: "2.09"
phase: 2
title: "Real GCP integration E2E (Cloud Tasks + Cloud Run + GCS)"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "125"
depends_on: ["2.01", "2.04", "2.05", "2.06", "2.07", "2.08"]
blocks: ["3.01", "3.02", "3.03", "3.05", "3.06", "3.09"]
estimate: "L"
status: "todo"
owner: ""
sprint: ""
---

# Task 2.09 — Real GCP integration E2E

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#125](https://github.com/Team-Proovy/proovy-agent/issues/125)

## 의존성

- 2.01 (잡 모델·Cloud Tasks 클라이언트) — 실제 queue enqueue와 status/progress API
- 2.04 (워커 서비스) — Cloud Run `/jobs/run` dispatch 대상
- 2.05 (sandbox) — 실제 worker render 격리 경계
- 2.06 (Mode B + capture) — API graph에서 job enqueue + 즉시 반환
- 2.07 (취소/재접속/환불/lazy detection) — 실제 GCP retry/cancel/stuck 복구
- 2.08 (워커 이미지 + health check) — 배포 가능한 worker runtime

## 사전 준비

- [ ] GCP 프로젝트 / region / billing / 서비스 계정 권한 확인
- [ ] Cloud Tasks queue, dispatch deadline, retry config, rate limit, IAM(OIDC 또는 Phase B 임시 token) 확인
- [ ] Cloud Run gen2 worker 서비스 URL, ingress/auth, concurrency=1, max instances, timeout 확인
- [ ] Artifact Registry worker image, Secret Manager, runtime env 설정 확인
- [ ] 2.05 sandbox runtime 확인: worker image non-root `USER`, Landlock write
      allowlist 사용 가능 커널, `VIDEO_RENDER_WORKSPACE_ROOT` 쓰기 권한, 크기제한
      in-memory volume mount, render subprocess secret/env scrub smoke 확인
- [ ] GCS bucket, object key prefix, lifecycle, signed URL 또는 public access 정책 확인
- [ ] DB `DATABASE_URL` / migration 적용 / `video_jobs` 상태 갱신 권한 확인
- [ ] dev E2E 실행 환경에 manim / TeX / CJK 폰트 전제가 필요한지 분리 확인

## 사용자 조치 누적 규칙

- [ ] 2.01, 2.04, 2.05, 2.06, 2.07, 2.08 최종 보고에 `사용자 조치 필요` 항목이 있으면 이 태스크의 사전 준비 또는 구현 체크리스트에 누적한다.
- [ ] 특히 GCP 배포, IAM, service account, Secret Manager, env var, Cloud Tasks 헤더/인증, GCS bucket 권한은 2.09에서 실제 리소스로 검증한다.
- [ ] 2.04 완료 보고에서 확인된 항목: 배포 시 `VIDEO_WORKER_AUTH_TOKEN` 설정과 Cloud Tasks 호출 헤더 설정은 실제 GCP 연결 검증 대상이다.
- [ ] 2.05 완료 보고에서 확인된 항목: render sandbox는 root runtime 또는 Landlock
      미지원 런타임에서 실패하도록 fail-closed 처리한다. Cloud Run gen2 worker 이미지와
      startup smoke에서 non-root, Landlock, 크기제한 workspace volume, secret/env 미전달을 검증한다.
- [ ] 2.06 완료 보고에서 확인된 항목: API runtime에는 `DATABASE_URL`,
      `VIDEO_CLOUD_TASKS_QUEUE_PATH`, `VIDEO_WORKER_URL`, `VIDEO_WORKER_AUTH_TOKEN`을
      함께 설정해야 한다. 실제 Cloud Tasks task name(`video-{job_id}`), worker header
      전달, createTask 실패 후 getTask reconciliation, enqueue 실패 환불 경로를 실제
      GCP 리소스로 검증한다.

## 구현 체크리스트

- [ ] GCS uploader/resolver가 최종 mp4 object key를 기록하고 status API가 결과 URL을 반환한다.
- [ ] Cloud Tasks `createTask`가 실제 queue에 task를 만들고 Cloud Run worker `/jobs/run`으로 dispatch한다.
- [ ] `createTask` 실패가 발생하면 `getTask` 확인 결과에 따라 `NOT_FOUND` 확정 시에만 failed+refund되고, 확인 모호/존재 확인 시에는 lazy detection 대상으로 남는지 검증한다.
- [ ] Cloud Tasks → Cloud Run worker 인증을 실제 설정으로 검증한다 (OIDC 권장, token 방식이면 header/secret 일치 검증).
- [ ] 샘플 문제 1건이 solve → video job create/capture → enqueue → worker render → GCS mp4 upload → 결과 표시까지 통과한다.
- [ ] worker health check가 실제 이미지/서비스에서 manim, TeX, CJK 폰트, ffmpeg 존재를 검증한다.
- [ ] 취소, transient retry, permanent failure, lazy detection 중 최소 smoke 경로를 실제 GCP에서 확인한다.
- [ ] GCP 리소스·env·secret·배포 절차와 실패 시 진단 위치를 문서화한다.

## Definition of Done

- [ ] 샘플 요청 1건이 실제 GCP 리소스에서 최종 mp4 생성, GCS 업로드, status API 결과 표시까지 통과한다.
- [ ] Cloud Tasks dispatch가 solve/capture 이전에 실행되지 않으며, Mode B enqueue 후 API/graph는 즉시 반환한다.
- [ ] worker auth가 없는 호출은 거부되고, Cloud Tasks 호출은 허용된다.
- [ ] GCS object key / signed URL / `video_jobs` terminal 상태가 일관되게 기록된다.
- [ ] secret/raw token이 logs, diagnostics, user-facing response에 노출되지 않는다.
- [ ] 자동화 가능한 E2E smoke 또는 실행 절차가 남아 Phase C 시작 전 재검증할 수 있다.

## 리스크 / 메모

- 2.09는 Phase B 최종 실제 GCP 검증 게이트다. 실제 worker/GCS/GCP 기반을 전제로 하는 Phase C 태스크는 2.09 완료 후 진행한다.
- Phase A inline runner와 fake/local uploader 검증은 실제 GCS 업로드 검증을 대체하지 않는다.
- Cloud Tasks 인증은 OIDC를 기본 방향으로 두되, Phase B 임시 token 방식이 남아 있으면 장기 구조로 굳히지 않는다.
- GCS upload 성공 후 DB finalize 실패 시 orphan object 정리 또는 idempotent finalize 정책을 확인한다.
