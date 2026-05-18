# TF1: 입찰공고 모듈

나라장터(G2B) 입찰공고를 자동 모니터링하고, 필터링/정리/의사결정을 지원하는 웹 애플리케이션.

## 기능

- **자동 수집**: 나라장터 Open API 호출로 입찰공고 데이터 수집
- **1차 필터**: 키워드 + 발주기관 유형(대학) + 금액 범위 + 커스텀 규칙
- **웹 대시보드**: 필터 통과 공고 목록 표시
- **2차 확인**: 담당자가 참여/패스 결정
- **자동 정리**: 참여 결정 시 관련 서류 다운로드 + 구글 스프레드시트 기입 (stub)
- **크론 스케줄링**: 매일 자동 체크

## 시작하기

### 사전 요구사항

- Python 3.10 이상
- pip

### 설치

```bash
pip install -r requirements.txt
```

### 환경 설정

`.env.example`을 참고하여 `.env` 파일을 생성하세요:

```bash
cp .env.example .env
```

필수 환경 변수:
- `G2B_API_KEY`: 나라장터 Open API 인증키 (https://data.g2b.go.kr)
- `DATABASE_URL`: SQLite 데이터베이스 경로 (기본값: `sqlite:///./bidding.db`)
- `API_PORT`: 웹 서버 포트 (기본값: `8000`)
- `CRON_ENABLED`: 크론 스케줄 활성화 (기본값: `true`)

### 실행

```bash
python app.py
```

웹 브라우저에서 `http://localhost:8000`으로 접속하세요.

## 프로젝트 구조

```
projects/bidding/
├── README.md                 # 이 파일
├── AGENTS.md                 # TF1 에이전트 역할/규칙
├── requirements.txt          # Python 의존성
├── .env.example              # 환경 변수 예제
├── app.py                    # FastAPI 메인 애플리케이션
├── models.py                 # SQLAlchemy ORM 모델
├── api_client.py             # 나라장터 Open API 클라이언트
├── filters.py                # 필터링 로직
├── scheduler.py              # APScheduler 크론 작업
├── database.py               # 데이터베이스 초기화/세션
├── templates/
│   ├── base.html             # 기본 템플릿
│   ├── dashboard.html        # 대시보드 페이지
│   └── detail.html           # 공고 상세 페이지
└── static/
    ├── css/
    │   └── style.css         # 스타일시트
    └── js/
        └── main.js           # 클라이언트 스크립트
```

## API 엔드포인트

### 대시보드 페이지
- `GET /` - 메인 대시보드

### REST API
- `GET /api/notices` - 필터된 공고 목록 조회 (쿼리 파라미터: keyword, institution_type, min_amount, max_amount)
- `POST /api/notices/{notice_id}/decide` - 공고에 대한 의사결정 (payload: `{"decision": "participate" | "pass"}`)
- `GET /api/notices/{notice_id}` - 공고 상세 정보 조회
- `POST /api/sync` - 수동 동기화 트리거
- `GET /api/stats` - 통계 조회

## 데이터베이스

SQLite 데이터베이스 스키마:

### notices 테이블
- `id` - 공고 고유번호
- `bid_notice_no` - 나라장터 공고 번호
- `bid_notice_name` - 공고명
- `notice_status` - 공고 상태
- `notice_date` - 공고 일자
- `institution_name` - 발주기관명
- `institution_type` - 발주기관 유형
- `bid_amount_min` - 최소 금액
- `bid_amount_max` - 최대 금액
- `description` - 설명
- `url` - 나라장터 상세 페이지 URL
- `passes_filters` - 필터 통과 여부
- `created_at` - 생성 시간
- `updated_at` - 수정 시간

### decisions 테이블
- `id` - 결정 고유번호
- `notice_id` - 공고 ID (외래키)
- `decision` - 의사결정 ('participate' 또는 'pass')
- `decided_by` - 결정자 (선택사항)
- `decided_at` - 결정 시간

## 필터 규칙

기본 필터 규칙 (`filters.py`):

1. **키워드 필터**: 공고명에 특정 키워드 포함 여부
   - 기본값: ['용역', '위치도']

2. **발주기관 유형**: 대학교(UNIVERSITY)만 선택

3. **금액 범위**: 
   - 최소: 1,000,000원
   - 최대: 500,000,000원

4. **커스텀 규칙**: `filters.py`에서 추가 가능

## 크론 스케줄

기본 설정:
- 매일 오전 8시 자동 동기화 (서버 로컬 시간)
- 기간: 지난 30일 공고

설정은 `scheduler.py`에서 변경 가능.

## 개발 진행 상황

### 완료된 작업 (Phase 2)
- [x] 프로젝트 초기 구조 생성
- [x] FastAPI 기본 애플리케이션 설정
- [x] SQLAlchemy ORM 모델 정의
- [x] 나라장터 Open API 클라이언트 구현
- [x] 필터링 로직 구현
- [x] 웹 대시보드 HTML/CSS/JS 구현
- [x] REST API 엔드포인트 구현
- [x] SQLite 데이터베이스 통합
- [x] APScheduler 크론 작업 설정
- [x] 환경 변수 설정

### 다음 할 일 (Phase 2 추가 작업)
- [ ] 구글 스프레드시트 API 연동
- [ ] 서류 자동 다운로드 기능
- [ ] 더 세밀한 필터 UI/UX 개선
- [ ] 사용자 인증 (선택사항)
- [ ] 에러 로깅 및 모니터링

### 미결정 사항
- 구글 스프레드시트 정확한 형식/위치
- 서류 자동 다운로드 대상 문서
- 추가 알림 채널 (카톡 등)

## 문제 해결

### API 키 오류
```
G2B_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.
```
→ `.env` 파일에 `G2B_API_KEY` 환경 변수를 설정하세요.

### 데이터베이스 오류
데이터베이스가 손상된 경우, `bidding.db` 파일을 삭제하고 애플리케이션을 재시작하면 자동으로 재생성됩니다.

### 크론 작업이 실행되지 않음
`CRON_ENABLED=true`가 설정되어 있는지 확인하세요. 수동 동기화는 `/api/sync` 엔드포인트를 호출하세요.

## 라이선스

내부 프로젝트

## 담당자

- TF1 에이전트
