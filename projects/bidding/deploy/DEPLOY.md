# 입찰공고 시스템 — Oracle Cloud Always Free 배포 가이드

## 사전 준비

- Oracle Cloud 계정 (도쿄 region — 한국 latency ~50ms)
- `mncapro.com` 도메인의 DNS 관리 권한 (사장님 IT 협조)
- VM SSH 키 쌍 (배포 머신에서 ssh-keygen으로 생성)

## Phase 1: Oracle VM 프로비저닝 (소요 30분)

### 1. Oracle Cloud 가입

1. https://www.oracle.com/cloud/free/ → "Start for free"
2. 가입 폼 (영문 주소 + 한국 휴대폰 +82-10-xxxx-xxxx)
3. **Home Region: Japan East (Tokyo)** ← 변경 불가, 정확히 선택
4. 카드 검증 ($1 hold, 자동 환불)
5. 가입 거절 시: VPN 끄고 재시도, 또는 한국 IP에서 직접 시도

### 2. ARM Compute Instance 생성

1. Console → Compute → Instances → **Create instance**
2. 이름: `bidding-prod`
3. **Image**: Canonical Ubuntu 22.04 (ARM 호환 — Ampere A1.Flex 사용 시)
4. **Shape**: VM.Standard.A1.Flex (Always Free)
   - OCPU: 1 (또는 최대 4)
   - Memory: 6GB (또는 최대 24)
5. **Networking**:
   - Public IP: Assign
   - VCN 자동 생성
6. **SSH Key**: 로컬에서 생성한 `~/.ssh/id_ed25519.pub` 내용 붙여넣기
7. Create → 약 1-2분 후 RUNNING

### 3. 방화벽 (Security List) 80/443 오픈

1. VM 인스턴스 → VCN → Security Lists → Default Security List
2. **Ingress Rules** → Add Rule:
   - Source: 0.0.0.0/0
   - Destination Port: 80
   - Add Rule again with Port: 443

### 4. VM 접속

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@<public-ip>
```

## Phase 2: 배포 스크립트 실행 (소요 10분)

VM 안에서:

```bash
# 1. 레포 클론 (또는 scp로 코드 업로드)
sudo apt update && sudo apt install -y git
git clone https://github.com/YOUR_GH/dext-ax.git /opt/bidding
cd /opt/bidding/projects/bidding/deploy

# 2. setup.sh 안의 REPO_URL, DOMAIN 변수 편집
sudo nano setup.sh

# 3. 실행
sudo bash setup.sh
```

setup.sh가 하는 일:
- Python 3.10 + venv + nginx + certbot 설치
- 방화벽 22/80/443 오픈 (Oracle Security List와 별개로 OS 레벨)
- systemd unit 등록 → `systemctl start bidding`
- nginx reverse proxy 설정 (8000 → 80)

## Phase 3: .env 셋업 + 도메인 + SSL (소요 30분)

### 1. .env 편집

```bash
sudo nano /opt/bidding/projects/bidding/.env
```

필수 값:
```
G2B_API_KEY=...
DECIDE_TOKEN_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
SMTP_USER=sookim93@mncapro.com
SMTP_PASSWORD=<Daum 앱 비밀번호>
EMAIL_SENDER_NAME=덱스트 입찰공고 봇
DECISION_RECIPIENTS=<박이사 메일>
EXECUTOR_RECIPIENTS=<최나린>,<이효진>
MONITOR_EMAIL=<본인>
DASHBOARD_URL=https://bidding.mncapro.com/
CRON_ENABLED=true
```

```bash
sudo systemctl restart bidding
```

### 2. DNS A record (사장님 IT)

`bidding.mncapro.com` → Oracle VM public IP

전파 확인 (DNS 변경 후 5-15분):
```bash
dig bidding.mncapro.com
```

### 3. Let's Encrypt SSL 인증서

DNS 전파 후:
```bash
sudo certbot --nginx -d bidding.mncapro.com
```
- 이메일 입력
- ToS 동의 (A)
- HTTP → HTTPS 강제 리다이렉트 (2)

자동 갱신 cron 자동 등록됨.

## Phase 4: 검증 (소요 10분)

### 1. 서버 동작 확인

```bash
curl https://bidding.mncapro.com/sync/status
# → {"running":false,...}
```

### 2. 첫 sync 트리거

```bash
curl -X POST https://bidding.mncapro.com/sync
# → {"status":"started",...}
```

5-7분 후 (bootstrap):
```bash
curl https://bidding.mncapro.com/sync/status
# → {"running":false, "last_result":{"inserted":N,...}}
```

### 3. 메일 도달 확인

본인 메일함 (`sookim2002@naver.com`)에 다이제스트 도착 확인.

### 4. 결정 링크 클릭 → confirmation 페이지

메일 안 [참여] 버튼 → 브라우저 새 탭 → `https://bidding.mncapro.com/decide/...` → "✅ 참여 결정 저장됨"

### 5. 대시보드 모바일 확인

박이사 폰에서 https://bidding.mncapro.com/ 접속 → 라이프사이클 board 정상 렌더링

## Phase 5: 운영 시작 — The Assignment

박이사·최나린·이효진에게 메일 한 통씩 보내 메일 도달 확인 + 본격 운영 시작.

## 로그 / 트러블슈팅

```bash
# 서비스 상태
sudo systemctl status bidding

# 실시간 로그
sudo tail -f /var/log/bidding.log

# nginx 로그
sudo tail -f /var/log/nginx/error.log

# 재시작
sudo systemctl restart bidding

# 환경변수 확인 (마스킹)
sudo cat /opt/bidding/projects/bidding/.env | sed 's/=.*/=***/'
```

## 보안 체크리스트

- [ ] .env 파일 권한 600 (`sudo chmod 600 /opt/bidding/projects/bidding/.env`)
- [ ] DECIDE_TOKEN_SECRET 외부 노출 X
- [ ] SSH password login 비활성 (key only)
- [ ] ufw 활성 + 22/80/443만 오픈
- [ ] Let's Encrypt 자동 갱신 cron 확인 (`sudo systemctl status certbot.timer`)

## 백업

SQLite DB는 단일 파일 `/opt/bidding/projects/bidding/bidding.db`. 일일 백업 권장:

```bash
# crontab -e
0 4 * * * cp /opt/bidding/projects/bidding/bidding.db /opt/bidding/backup/bidding-$(date +\%Y\%m\%d).db
0 4 * * * find /opt/bidding/backup -name "bidding-*.db" -mtime +30 -delete
```

## 다음 단계 — Sheets mirror (Phase 2 작업)

배포 안정화 후 Sheets API 통합 작업 (Task #17). 박이사·주니어·사장님이 Sheet으로 view.
