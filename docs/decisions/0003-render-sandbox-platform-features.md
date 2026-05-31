---
status: accepted
---

# 0003 — 렌더 샌드박스: platform-features (nsjail 제외)

## Context

영상 렌더는 LLM이 생성한 manim 코드를 실행하므로 격리가 필요하다. 초안(video-generation-design.md §8.4)은 **nsjail**을 기본으로 두고, gen2가 "플랫폼 gVisor를 제공"한다고 적었다. 조사 결과 두 전제가 틀렸다:

1. **gen1 = gVisor, gen2 = microVM(풀 Linux)** 다. 초안의 "gen2 = gVisor"는 오기.
2. Cloud Run(관리형)은 **이미 namespaces + 자체 seccomp**를 적용하고 privileged/eBPF/커스텀 seccomp를 금지한다 → nsjail이 필요로 하는 *중첩 namespace 생성*이 막힐 공산이 크다(차단 스파이크).

즉 nsjail은 gen2 격리와 중복이고, Cloud Run에서 안 돌 위험이 크다.

## Decision

렌더 격리는 **platform-features 조합**으로 한다 (nsjail 채택 안 함):

- ① **AST allowlist**(manim/numpy/math) — 위험 코드 거부 + 1차 네트워크 차단(네트워크 import 불가)
- ② **gen2 microVM + 인스턴스 VM 경계 + concurrency=1** — 커널 격리(공짜). 렌더마다 자기 VM이라 다른 잡/호스트에 못 닿음.
- ③ **비루트 + 크기제한 in-memory 볼륨(workspace) + 인스턴스 일회성** — FS 봉쇄. (Cloud Run은 read-only rootfs 노브가 없어 이 조합으로 대체. 기본 FS가 무제한 in-memory라 크기제한 볼륨이 OOM 방지에 필수.)
- ④ **in-process rlimit + timeout + 인스턴스 메모리 한도** — 무한루프·메모리 폭발(DoS) 방지.
- ⑤ **렌더 서브프로세스에 시크릿 env 미전달** — 유출 방지(빼돌릴 시크릿이 그 안에 없음).

렌더는 TeX/ffmpeg 풀 syscall 호환 + CPU 성능 때문에 **gen2**를 쓴다.

**MVP day-1 = ①②③④ + ⑤.** ⑤의 network-off 자체(렌더 서브프로세스 네트워크 차단)는 **Phase B** — Cloud Run은 커스텀 seccomp가 불가하므로 **egress 차단 별도 렌더 서비스**(VPC all-traffic egress + 인터넷 없는 VPC)로 한다. 그 전까지는 ①(import 불가) + ⑤(시크릿 없음) + ③(워커 파일 못 읽음)이 유출을 막는다.

## Considered Options

- **nsjail 기본**(초안): 한 도구로 ②~⑤를 번들하지만, Cloud Run에서 안 돌 위험(all-or-nothing 차단 스파이크) + gen2 격리와 중복 — 기각. 보안 사고/컴플라이언스가 생기면 platform-features *위에 얹는* 선택적 추가 계층으로만 도입.

## Consequences

- nsjail 호환 스파이크가 critical path에서 빠진다 → Phase B 선결은 "platform-features가 Cloud Run에서 실제 적용되는지 검증"(read-only rootfs 노브 없음→볼륨+일회성, 커스텀 seccomp 불가→egress 서비스)으로 바뀐다(가드된, 더 안전한 길).
- network-off가 day-1이 아니라 Phase B → 그동안 AST + 시크릿 미전달 + FS 봉쇄가 유출 위협을 커버.
- 각 층이 독립이라 한 조각이 막혀도 fallback이 있어 통째로 블로킹되지 않는다.
