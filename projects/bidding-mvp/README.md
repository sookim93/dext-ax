# 입찰공고 일일 다이제스트 — Phase 1 MVP

매일 KST 오전 9시 (평일) 나라장터 입찰공고를 fetch → 필터 → Daum SMTP로 메일 1통 발송.

**상태(state) 없음.** Cron 한 번 = 메일 한 통. 인프라 0 (GitHub Actions).

## 동작 흐름

```
나라장터 API (어제~오늘)
   → 필터 (대학교 endswith + 키워드 + 예산)
   → refNtceNo 기반 신규/재공고 분류
   → Daum SMTP 메일 1통
```

## 설정

### 1. GitHub Secrets

레포 Settings → Secrets and variables → Actions → New repository secret 으로 등록:

| Key | 값 |
|---|---|
| `G2B_API_KEY` | 나라장터 Open API 키 (`data.go.kr`에서 발급) |
| `SMTP_USER` | `sookim93@mncapro.com` |
| `SMTP_PASSWORD` | Daum 메일 앱 비밀번호 (일반 비밀번호 X) |
| `EMAIL_RECIPIENTS` | 콤마 구분 (검증 단계: `sookim2002@naver.com`) |

### 2. 운영 시작 후 수신자 변경

`EMAIL_RECIPIENTS` 시크릿만 업데이트:
- 검증: `sookim2002@naver.com`
- 운영: `<박이사>,<최나린>,<이효진>,<본인>`

### 3. 발송 시각 변경

`.github/workflows/daily-digest.yml`의 `cron` 변경:
- 현재: `0 0 * * 1-5` (KST 09:00 평일 = UTC 00:00)
- 예: KST 10:00 → `0 1 * * 1-5`

### 4. 필터 조정 (코드 변경)

`daily_digest.py` 상단 상수:
- `INCLUDE_KEYWORDS` — 적어도 하나 매치해야 함
- `EXCLUDE_KEYWORDS` — 하나라도 매치하면 drop
- `BUDGET_MIN` / `BUDGET_MAX` — 예가 범위 (won)
- `DAYS_BACK` — 검색 시작점 (default 1 = 어제부터)

## 수동 실행 (즉시 발송)

GitHub repo → Actions 탭 → "입찰공고 일일 다이제스트" → "Run workflow" 클릭.

## 로컬 테스트

```bash
cd projects/bidding-mvp
cp .env.example .env
# .env 편집 (G2B_API_KEY, SMTP_PASSWORD, EMAIL_RECIPIENTS)
pip install -r requirements.txt
python daily_digest.py
```

## 검증 흐름

1. **본인 메일로 첫 발송** — 본인 Naver 메일함 확인
2. **메일 본문 확인** — 공고명 클릭 → 나라장터 원문 페이지로 이동 (정상)
3. **재공고 섹션 검증** — refNtceNo 있는 공고가 상단에 별도 그룹
4. **The Assignment** — 박이사·최나린·이효진에게 한 통씩 보내 reach 검증
5. **운영 시작** — 검증 통과 후 `EMAIL_RECIPIENTS`에 실제 사용자 추가

## Phase 2+ 로드맵 (나중에)

- 박이사 [참여]/[불참] 결정 추적 (HMAC 토큰)
- 주니어 자동 알림 (제출완료 버튼)
- 마감 D-3 / D-1 reminder
- 결과 (낙찰/유찰) 트래킹
- 대시보드 (라이프사이클 view)
- Google Sheets mirror (사장님 view)

기존 FastAPI 구현 (Phase 2+ 후보 코드)이 `projects/bidding/`에 보존되어 있음.

## 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| Gmail에서 메일 거부 (550 SPF/DKIM) | mncapro.com DNS에 SPF/DKIM 미설정. 수신자를 비-Gmail (Naver/Daum)로 |
| Daum SMTP timeout | 본인 발송 retry 3회 자동. 그래도 실패 시 다음 cron 주기에 재시도 |
| 메일 0건 발송 (필터 통과 0) | 정상. `INCLUDE_KEYWORDS` 너무 좁거나 어제 신규 공고 적었을 수 있음 |
| GitHub Actions cron 지연 | 무료 tier는 ±15분 wobble. 09:00 → 09:15 도착 가능 |
