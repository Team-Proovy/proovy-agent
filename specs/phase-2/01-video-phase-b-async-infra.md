# Phase B — 비동기 잡 인프라 (설계 Phase B)

> 매핑: 설계 문서 `docs/architecture/video-generation-design.md §7`의 **Phase B** = 본 `specs/phase-2`. 선행: Phase A (`specs/phase-1`).

## Purpose
Phase A의 inline 스캐폴드를 제거하고 Cloud Run gen2 워커 + Cloud Tasks 기반 Mode B(논블로킹) 비동기 영상 잡 인프라와 단일 크레딧 원장을 도입한다.

## Requirements
- `video_jobs` 테이블(`progress_updated_at`, `retry_source_job_id` + unique partial index, checkpoint 필드 없음)과 alembic migration, `VideoJobClient` Protocol + Cloud Tasks 클라이언트 + progress write/조회 API를 구현한다 (`VideoJobSegment` 테이블은 Phase D로 미룸).
- `features/video/worker/`에 http_handler(`/jobs/run`, gen2)와 runner를 두고, 잡 시작 시 progress-staleness 체크(succeeded skip / stale 전체 재실행), 10초 cancel poll + stage 경계 `cancel_requested` 확인, stage/segment마다 progress write를 한다.
- platform-features 격리(비루트 + 크기제한 in-memory 볼륨 + rlimit/timeout, 시크릿 미전달)를 Cloud Run에서 검증·적용하고 `manim render`를 sub-process로 실행한다 (network-off egress 차단은 후속, AST가 1차 차단; nsjail 미채택).
- `graph/nodes/video.py`를 잡 enqueue + 즉시 반환(Mode B)으로 전환하고, 영상 크레딧은 video_node가 createTask 직전 동기 capture(`balance −10`, `hold.amount −10`)하며 실패/취소 terminal에서만 idempotent refund 한다.
- `features/credits/`에 단일 balance+hold 원장(원자적 hold/capture/refund, Planner 전체 hold·CreditSettler 일괄 차감)을 구현하고 solve/pdf도 같은 balance에서 차감하도록 배선하며, 잡 취소 경로와 재접속 복구(`video_jobs[-1]` 상태 응답)를 추가한다 (ADR 0002/0004).
- Phase B 마지막에 실제 GCP 리소스(Cloud Tasks, Cloud Run gen2 worker, GCS, Artifact Registry, Secret Manager/IAM)를 연결해 샘플 영상 요청 1건이 enqueue부터 GCS mp4 결과 표시까지 통과하는 Real GCP integration E2E를 수행한다.

## Approach
메인 그래프 입장에서 VideoNode는 잡 launcher일 뿐이고 실제 렌더는 그래프 밖 워커가 비동기로 수행하므로, capture를 enqueue 직전에 두어 "워커 도착 시 capture가 반드시 끝나 있음"을 보장하고 refund race를 차단한다. DB row INSERT + 10cr capture + deterministic `cloud_tasks_name`은 single transaction으로 묶고 Cloud Tasks createTask는 best-effort + lazy reconciliation으로 보상한다. orphan hold는 별도 sweep 없이 TTL-on-read로 자동 회복하고, stuck 잡은 사용자 활동 endpoint의 lazy detection으로 정리한다. 워커 이미지 Dockerfile(비루트 + 폰트)·runtime health check를 CI에 포함한다. 각 Phase B 태스크 최종 보고에서 GCP 배포·IAM·secret·env·Cloud Tasks 헤더/인증 등 `사용자 조치 필요` 항목이 나오면 2.09 Real GCP integration E2E에 누적하고 실제 리소스로 검증한다.

## Verification
- video_node가 enqueue 후 즉시 반환해 API/그래프가 영상 렌더 동안 점유되지 않는다 (부하 테스트, MVP 성공 기준).
- sub-process가 허용 외 FS write·자원 한도 초과를 시도하면 모두 차단되고 잡 실패로 처리된다 (sandbox smoke: 워크스페이스 외 write·fork 폭탄·메모리/시간 초과).
- 영상 실패/취소 terminal을 잡은 주체만 10cr을 환불하고, retry가 이미 성공했으면 환불하지 않는다 (refund idempotency + 무료 영상 race 차단).
- queued 취소는 API가 terminal+refund, running 취소는 `cancel_requested=true` → 워커 감지 → 렌더 sub-process 종료 + 협조 종료+refund로 처리된다.
- 프론트 재접속 시 `video_jobs[-1]`로 현재 상태가 복원된다.
- 실제 GCP 환경에서 샘플 요청 1건이 solve → video job create/capture → Cloud Tasks enqueue → Cloud Run worker render → GCS mp4 upload → status API 결과 표시까지 통과한다.
