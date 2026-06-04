# Active Plan — 덱스트 자동화 프로젝트
업데이트: 2026-05-12

## 지금 상태

TF1(입찰공고) 코드 골격은 있지만 G2B API가 실제로 안 터진다.
- api_client.py, filters.py, scheduler.py, app.py, 대시보드 UI 존재
- G2B API 키: `projects/bidding/.env`에 저장됨
- 모든 엔드포인트(`apis.data.go.kr`, `openapi.g2b.go.kr`) 403/500 오류

TF3(견적서)는 코드 있음 (status.md에 완료로 표시). 미검증.
TF2(수식추출), TF4(결제정리)는 미착수.

## 다음 할 일

### TF1 최우선
1. **data.go.kr 마이페이지 → 인증키 신청 목록** 확인
   - 어떤 API 서비스가 승인됐는지 확인
   - 승인된 서비스의 정확한 엔드포인트 URL 복사
2. `api_client.py` 엔드포인트 수정
3. 설계 결정사항 코드 반영:
   - 필터에 "병원" 제외 로직 (`대학교` 포함 + `병원` 미포함)
   - 스케줄러 8:30/13:30/17:00 3회로 변경
   - 새 공고 있을 때만 다이제스트 이메일 발송 (Daum SMTP)
   - 48시간 미처리 시 Slack 에스컬레이션 (`SLACK_WEBHOOK_URL`)
   - `DECISION_MAKER_EMAIL` 환경변수로 담당자 관리

## 결정된 것들

| 항목 | 결정 |
|------|------|
| 배포 | Railway/Fly.io 먼저, 사내 서버는 나중 |
| G2B API 키 | `projects/bidding/.env`에 저장 완료 |
| 이메일 발송 | Daum SMTP (`smtp.daum.net:465`) |
| 발주기관 필터 | "대학교" 포함 + "병원" 미포함 (문자열) |
| 크론 주기 | 8:30 / 13:30 / 17:00 |
| 알림 방식 | 새 공고 있을 때만 다이제스트 1통 |
| 담당자 관리 | `.env`의 `DECISION_MAKER_EMAIL` |
| 에스컬레이션 | 48시간 미처리 → 개인 Slack 웹훅 |

## 보류 중인 것들

- TF3 견적서 실제 동작 검증 (코드 있지만 테스트 안 됨)
- Slack webhook URL 생성 (개인 워크스페이스)
- 배포 환경 셋업 (Railway/Fly.io)
