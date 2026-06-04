# 덱스트 자동화 — TODOS

> 별도 티켓으로 관리되는 follow-up. 각 티켓은 독립 PR/사이클 단위.
> 우선순위 순서대로 정렬.

---

## Ticket #1 — 낙찰 결과 자동 매칭 (계약정보 sync)

**Status:** 별도 티켓 — 이번 사이클(메일 prototype) 이후
**Module:** TF1 입찰공고
**Owner:** TBD

### Why

박이사·실행자가 외부(학교) 통지 받기 전 회사가 먼저 알아야 함. 현재 lifecycle은 `SUBMITTED → 결과 대기 (passive)`. 자동 sync로 `AWARDED/LOST` 전환되면 monitor에 즉시 표시 + 본인 알림.

### What

- `api_client.py`에 `fetch_contracts(days_back)` 메소드 추가
- `scheduler.py`에 새 잡: 매일 09:30 계약정보 sync + 사업자번호 매칭
- 매칭 로직:
  - `cntrct.rprsntCorpBizrno == "105-87-28721"` AND `cntrct.bidNtceNo` IN our SUBMITTED notices → AWARDED 전환 + 축하 알림
  - `cntrct.bidNtceNo` 매칭됐는데 다른 회사 → LOST 전환
  - 우리 사업자번호 매칭 + bidNtceNo 비어있음 (수의계약) → "manual review" 큐
- monitor view의 AWARDED/LOST 섹션이 placeholder에서 실제 데이터로 변환됨

### Context

- **API endpoint 검증됨:** `getDataSetOpnStdCntrctInfo` HTTP 200 정상. 44 필드.
- **결정적 필드:** `rprsntCorpBizrno` (사업자등록번호) + `bidNtceNo` (원공고 link) + `cntrctAmt` (계약금액) + `cntrctCnclsDate` (체결일)
- **우리 회사:** (주)엠엔씨에이프로, 사업자번호 `105-87-28721`
- **검증 데이터 부재:** 60일 sweep에서 우리 회사 매칭 0건 (자주 발생 안 함). 매칭 로직 자체는 미래 데이터로 자동 검증.
- **별도 endpoint `getDataSetOpnStdScsbidInfo` (낙찰)** 존재하지만 "필수값 입력 에러" — 추가 params 필요. 계약정보로 동일 목적 달성 가능해 보류.
- **수원대 우리 회사 낙찰 사례 검증 필요** — sweep 다시 돌릴 때 사업자번호 표기 variation (105-87-28721 vs 1058728721 등) 확인.

### Depends on / blocked by

- 이번 사이클 (메일 한 사이클 prototype) 완료 후 시작
- 사업자번호 표기 variation 검증 sweep 결과

### Pros / Cons

✅ 외부 학교 통지 받기 전 회사 내부에서 먼저 결과 인지 — 3.5억 사건 방지 인프라
✅ AWARDED일 때 통계 추적 → 우리 회사 입찰 효율 metric 가능
❌ 매칭 로직이 사업자번호 표기 차이에 fragile할 수 있음 — fallback 회사명 부분 매칭 필요할 수도

---

## Ticket #2 — 카톡 push 채널 (escalation)

**Status:** 별도 티켓 — Ticket #1과 병렬 가능
**Module:** TF1 입찰공고
**Owner:** TBD

### Why

박이사·실행자가 메일 안 보는 주간 (외근·주말) 24h 무응답 시 카톡 push로 escalation. 진짜 fail-safe 시스템 완성.

### What

- Aligo SMS API 또는 카카오 알림톡 비즈니스 채널 등록
- `notifier.py`에 `send_kakao_push(notice, recipient)` 함수
- escalation 체인:
  - DISCOVERED + 24h 무결정 → 박이사 카톡
  - DECIDED_PARTICIPATE + 마감 D-3 → 최나린·이효진 카톡 reminder
  - REPOST_DETECTED + 24h 무처리 → 최나린·이효진 카톡
  - REPOST_DETECTED + 48h 무처리 → 박이사 카톡 escalation
- `.env`에 `KAKAO_API_KEY`, `ALIGO_API_KEY` 등 추가

### Context

- 카카오톡 비즈니스 채널 검수 1-2주 소요
- Aligo는 사업자 인증만 (3-7일)
- 박이사·최나린·이효진 회사 카톡 ID 확보 필요 (The Assignment에서 답장으로 받음)
- 회사 카톡은 최근 도입 — 박이사 PC 운영 능력 낮음 고려해 단순 push만

### Depends on / blocked by

- Aligo 또는 카카오 비즈니스 채널 계약 결제
- 박이사·실행자 카톡 ID 확보 (The Assignment 답장)
- 이번 사이클 prototype 완료 후

### Pros / Cons

✅ 박이사가 메일 안 보는 주간에도 안전망 — 진짜 fail-safe
✅ 운영 측면에서 박이사·실행자 reach 채널 다중화
❌ 외부 의존성 (API 검수, 비용)
❌ 카톡 검수 일정이 불확실 — 사용자 퇴사 timing과 충돌 가능

---

## Ticket #3 — AWARDED/LOST 수동 입력 UI (Ticket #1 ship 전까지)

**Status:** 별도 티켓 — Ticket #1 ship 후 dead code 됨
**Module:** TF1 입찰공고

### Why

Ticket #1 완료 전 박이사가 외부 학교 통지 받으면 수동으로 결과 입력할 수 있게.

### What

- monitor view의 SUBMITTED 공고 옆 [낙찰]/[패찰] 버튼
- 같은 `/decide/{id}/{action}/{token}` endpoint 패턴 확장

### Depends on / blocked by

Ticket #1이 ship되면 자동 매칭으로 대체. Ticket #1보다 먼저 ship되면 가치 있고, 후면 dead code.

### Pros / Cons

✅ Ticket #1 검수/구현 기간 동안 수동 fallback
❌ Ticket #1 ship 후 dead code — Ticket #1 우선 ship되면 이 티켓 자체가 무효

---

## Ticket #4 — Filter Settings UI (코드 변경 없이 운영)

**Status:** 별도 티켓 — 운영 시작 후 박이사 피드백 받고
**Module:** TF1 입찰공고

### Why

박이사·사용자가 include/exclude 키워드를 코드 변경 없이 운영 중 조정. 사용자(소르) 퇴사 후에도 시스템 운영 유연성 유지.

### What

- `/settings` 페이지에 키워드 칩 토글 UI
- 예가 범위 슬라이더
- `max_age_days` 조정
- 변경 즉시 sync 잡에 적용 (DB에 저장하고 NoticeFilter가 그것을 읽음)

### Depends on / blocked by

박이사 운영 시작 후 "키워드 더 추가/제외" 같은 실제 피드백 받고

### Pros / Cons

✅ 운영 유연성 — 사용자 퇴사 후에도 사장님 또는 후임이 조정 가능
❌ 우선순위 낮음 — 처음엔 사용자가 `.env`로 조정해도 충분

---

## Ticket #6 — 재공고 자동 감지 정확도 검증 (refNtceNo)

**Status:** 별도 티켓 — 이번 사이클 ship 후 운영 시작 시점에 검증
**Module:** TF1 입찰공고

### Why

시스템의 재공고 자동 감지는 API 응답의 `refNtceNo` 필드로 원공고와 link. 그런데 학교가 "재공고"라고 부르는 모든 케이스가 refNtceNo로 link된다는 보장 없음.

3.5억 사건의 진짜 재공고 패턴이 refNtceNo와 일치하는지 검증 안 되면 — 시스템이 의도된 fail-prevent 못 함.

### What

- 3.5억 사건의 원공고 bidNtceNo + 재공고 bidNtceNo 데이터 확보 (사용자 또는 명기현·최나린이 보유)
- 두 데이터의 refNtceNo 관계 확인:
  - 재공고의 refNtceNo == 원공고 bidNtceNo → OK, 시스템 잡음
  - refNtceNo 비어있음 → 시스템 못 잡음, fallback 로직 필요 (공고명 유사도 + 발주기관 + 마감일 패턴 매칭)
- 운영 시작 후 1-2건 재공고 실제 발생 시 시스템이 자동 잡는지 verify

### Context

- API endpoint: PubDataOpnStdService의 `bidNtceNo` + `refNtceNo` 필드
- 우리 시스템 현재 로직: `refNtceNo` 있으면 원공고와 link, 없으면 일반 신규로 처리
- 학교의 "재공고" 정의는 학교마다 다를 수 있음 — 일관성 검증 필요

### Depends on / blocked by

- 이번 사이클 ship 후 운영 시작
- 3.5억 사건 또는 미래 재공고 발생 시 데이터 분석

### Pros / Cons

✅ 시스템 신뢰성의 핵심 — 재공고 못 잡으면 fail-prevent 실패
❌ 검증을 위한 실제 재공고 데이터 의존 (자주 발생 안 함)

---

## Ticket #5 — TF1 ↔ TF3 (입찰공고 ↔ 견적서) 통합

**Status:** 별도 티켓 — 두 모듈 운영 후 검증
**Module:** TF1 + TF3

### Why

박이사가 [참여] 결정한 공고는 견적서 생성으로 이어짐. 두 모듈을 라이프사이클로 연결하면 자동화 흐름 완성:
DECIDED_PARTICIPATE → 견적서 자동 생성 트리거 → 박이사 검토 → 메일 발송

### What

- TF1의 `/decide/{id}/participate/{token}` 직후 TF3 견적서 endpoint trigger
- 또는 monitor view에 [견적서 생성] 버튼 추가

### Depends on / blocked by

- TF3 견적서가 실제로 사용 중인지 검증 필요 (현재 status.md엔 "완료"지만 실사용 데이터 미확인)
- 두 모듈 동일 인증/세션 체계

### Pros / Cons

✅ 입찰 → 견적 → 결제 → 결제정리 라이프사이클 통합 — 4-TF 시너지 시작점
❌ TF3가 실사용 안 되고 dormant면 통합 의미 없음 — 먼저 TF3 사용 검증
