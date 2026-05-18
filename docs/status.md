# 덱스트 자동화 프로젝트 — TF 진행 현황

> 이 파일은 각 TF가 작업 완료 시 자동 업데이트한다.
> 오케스트레이터는 세션 시작 시 이 파일을 먼저 읽는다.

## TF1: 입찰공고

| 항목 | 내용 |
|------|------|
| 상태 | 🟢 Phase 1 MVP 운영 시작 (2026-05-18) |
| 마지막 업데이트 | 2026-05-18 |
| 완료한 작업 | **Phase 1 MVP — 일일 다이제스트 메일 운영 시작.** `projects/bidding-mvp/daily_digest.py` 단일 파일로 G2B PubDataOpnStdService fetch → 필터 (대학교 endswith + INCLUDE/EXCLUDE 키워드 + 예산 1M~10억, null 허용) → refNtceNo 기반 재공고 분류 → 날짜별 그룹핑 → Gmail SMTP 발송. **GitHub Actions cron**: KST 09:00 (3 영업일치, 매일 의무 발송) + KST 15:00 (당일 신규만, 있을 때만). 영업일 기준 age 필터로 월요일 cron이 직전 금/목 잡음. 모니터링용 fetch 통계 footer 포함. **수신자 5명**: psk@mncapro.com (박이사), leehj2603 (이효진), choinr404 (최나린), rlgus8469 (명기현 대리), sookim2002@naver.com (본인). **발송 채널**: Gmail SMTP (`ysmnc139@gmail.com` 회사용 Gmail) — Daum SMTP는 GitHub runner cloud IP를 spam-block해서 전환. **검증**: 2026-05-18 e2e 발송 성공 (5명 동시, 3건 다이제스트). **Phase 2+ 후보 (보존)**: `projects/bidding/` FastAPI 라이프사이클 거버넌스 시스템 — decide endpoint, 9-state lifecycle, reminder cron, decision tokens, 대시보드. Codex critique 결과 Phase 1 검증 후 단계적 통합. |
| 다음 할 일 | 1) The Assignment — 박이사·실행자 4명 메일 reach 검증 (카톡으로 "메일 받으셨는지" 확인). 2) 운영 1주 후 박이사·실행자 피드백 받아 INCLUDE_KEYWORDS 확장 결정. 3) Phase 2 진입 결정 — 결정 추적 (lifecycle) / 자동 reminder / 결과 트래킹 (낙찰/유찰). |
| 블로커 | 없음 |

## TF2: 수식추출

| 항목 | 내용 |
|------|------|
| 상태 | 🔴 미착수 |
| 마지막 업데이트 | - |
| 완료한 작업 | - |
| 다음 할 일 | Phase 3 착수 대기 |
| 블로커 | 없음 |

## TF3: 견적서

| 항목 | 내용 |
|------|------|
| 상태 | 🔴 미착수 |
| 마지막 업데이트 | - |
| 완료한 작업 | - |
| 다음 할 일 | Phase 3 착수 대기 |
| 블로커 | 없음 |

## TF4: 결제정리

| 항목 | 내용 |
|------|------|
| 상태 | 🔴 미착수 |
| 마지막 업데이트 | - |
| 완료한 작업 | - |
| 다음 할 일 | Phase 4 착수 대기 (혜정팀장님 업무 프로세스 파악 필요) |
| 블로커 | 업무 프로세스 미파악 |
