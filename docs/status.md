# 덱스트 자동화 프로젝트 — TF 진행 현황

> 이 파일은 각 TF가 작업 완료 시 자동 업데이트한다.
> 오케스트레이터는 세션 시작 시 이 파일을 먼저 읽는다.

## TF1: 입찰공고

| 항목 | 내용 |
|------|------|
| 상태 | 🟢 v2 라이프사이클 거버넌스 — Office Hours + Plan Eng Review 통과, 12/12 e2e 테스트 PASS |
| 마지막 업데이트 | 2026-05-14 |
| 완료한 작업 | **v2 reframe: 검색 dashboard → 공고 라이프사이클 거버넌스 시스템.** Office Hours에서 3.5억 사건의 진짜 원인이 "재공고 처리 fail"임을 발견 → 시스템 정체성 reframe. Design doc: `~/.gstack/projects/dext-ax/ys-main-design-20260514-094623.md`. Plan Eng Review 통과. **이번 사이클 구현 (총 12개 파일)**: ① `models.py` — `LifecycleState` enum 9개 (DISCOVERED/DECIDED_PASS/DECIDED_PARTICIPATE/SUBMITTED/REPOST_DETECTED/RESUBMITTED/AWARDED/LOST/EXPIRED) + `Notice.ref_notice_no` + `Decision.token`/`used_at`/`transition_type`. ② `api_client.py` — `refNtceNo` 파싱 (재공고 자동 감지 키). ③ `filters.py` — 발주기관 매칭 substring → **endswith**("대학교"/"대학")으로 강화 (산학협력단·부속기관 제외). ④ `scheduler.py` — sync 시각 **3회 → 2회 (09:00/15:00)** + 라이프사이클별 다이제스트 분류 + REPOST_DETECTED 자동 진입 + **EXPIRED 자동 잡 (09:30)**. ⑤ `app.py` — `/decide/{id}/{action}/{token}` 4-action endpoint (participate/pass/submitted/resubmitted), itsdangerous 7일 만료 토큰, 단일사용 (`used_at` 스탬프), 라이프사이클 transition 검증, **monitor view 라이프사이클 8섹션 grouping**. ⑥ `notifier.py` (재작성) — 다이제스트 메일 **3섹션 (신규/결정완료/재공고)**, 각 row에 token 버튼, `send_decision_notification` 즉시 알림. ⑦ `tokens.py` (신규) — `make_decision_token` + `verify_decision_token` cycle-free 공유 helper. ⑧ `templates/decide.html` (신규) — 4가지 결과 (ok/already_done/invalid_transition/error) 모바일 친화. ⑨ `templates/dashboard.html` (재작성) — 히어로 유지 + lifecycle 8섹션 collapsible. ⑩ `static/css/style.css` — lifecycle board + decide 페이지 스타일. ⑪ `requirements.txt` — itsdangerous 2.2.0. ⑫ `.env.example` — `DECIDE_TOKEN_SECRET`. **검증**: 12/12 e2e 테스트 통과 (dashboard 렌더, participate/pass/submitted/resubmitted 전환, 토큰 재사용/위조/만료/mismatch 거부, EXPIRED sweep, sync 상태). **TODOS.md** 신규: #1 낙찰 자동 매칭(계약정보 sync), #2 카톡 push, #3 수동 AWARDED/LOST UI, #4 Settings UI, #5 TF3 통합, #6 refNtceNo 검증. **현재 DB**: 새 스키마로 재생성 필요 (구 bidding.db 제거됨). |
| 다음 할 일 | 1) (검증) `pip install -r requirements.txt` → `.env`에 `DECIDE_TOKEN_SECRET` (생성: `python -c "import secrets; print(secrets.token_urlsafe(32))"`) + SMTP 자격증명 (수신자=본인) → `python app.py` → `POST /sync` → 본인 메일 확인 → 메일 안 [참여] 버튼 클릭 → /decide 결과 페이지 → DB 라이프사이클 전환 확인. 2) (Office Hours The Assignment) 박이사·최나린·이효진에게 메일 한 통씩 보내 메일 도달 검증 + 카톡 ID 확보. 3) TODOS Ticket #1/#2 우선순위 결정. |
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
| 상태 | 🟢 완료 |
| 마지막 업데이트 | 2026-05-08 |
| 완료한 작업 | Flask 웹 애플리케이션 구현 완료: app.py (Flask + SQLite), templates/index.html (대학 검색 자동완성, 금액 입력, 미리보기 모달), templates/preview.html (전문 견적서 양식 — 실제 회사 정보 포함), templates/settings.html (Daum 계정 관리). 65개 대학 목록, Daum SMTP 메일 발송, 모바일 반응형 UI. |
| 다음 할 일 | 없음 (완료) |
| 블로커 | 없음 |

## TF4: 결제정리

| 항목 | 내용 |
|------|------|
| 상태 | 🔴 미착수 |
| 마지막 업데이트 | - |
| 완료한 작업 | - |
| 다음 할 일 | Phase 4 착수 대기 (혜정팀장님 업무 프로세스 파악 필요) |
| 블로커 | 업무 프로세스 미파악 |
