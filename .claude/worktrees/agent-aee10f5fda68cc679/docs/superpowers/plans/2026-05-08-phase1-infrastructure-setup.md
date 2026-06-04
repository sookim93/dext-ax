# Phase 1: 멀티에이전트 기반 세팅 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 4개 독립 모듈을 병렬 개발할 수 있는 오케스트레이터 + TF 서브에이전트 인프라를 구축한다.

**Architecture:** git monorepo에 모듈별 독립 폴더(`projects/xxx/`)를 두고, 루트 CLAUDE.md가 오케스트레이터 역할을 정의하며, 각 모듈 폴더의 AGENTS.md가 TF 서브에이전트의 컨텍스트를 정의한다. `docs/status.md`가 세션 간 진행 상황을 유지한다.

**Tech Stack:** Markdown 설정 파일 (CLAUDE.md, AGENTS.md), Git, Claude Code Agent 도구 (worktree 격리 모드)

**Design Spec:** `docs/superpowers/specs/2026-05-08-dext-multi-agent-design.md`

---

## Task 1: Git 초기화 + 폴더 구조 생성

**Files:**
- Create: `.gitignore`
- Create: `projects/bidding/` (디렉토리)
- Create: `projects/formula/` (디렉토리)
- Create: `projects/quotation/` (디렉토리)
- Create: `projects/payment/` (디렉토리)
- Create: `docs/` (디렉토리)
- Create: `.github/workflows/` (디렉토리)

- [ ] **Step 1: Git 저장소 초기화**

```bash
cd /Users/a0000/dext-ax
git init
```

Expected: `Initialized empty Git repository in /Users/a0000/dext-ax/.git/`

- [ ] **Step 2: 프로젝트 폴더 구조 생성**

```bash
mkdir -p projects/bidding projects/formula projects/quotation projects/payment
mkdir -p docs/superpowers/specs docs/superpowers/plans
mkdir -p .github/workflows
```

- [ ] **Step 3: .gitignore 생성**

```gitignore
# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp
*.swo

# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
env/
*.egg-info/
dist/
build/

# Node
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Environment
.env
.env.local
.env.*.local

# Logs
*.log
logs/

# Claude Code
.omc/
```

- [ ] **Step 4: 각 프로젝트 폴더에 .gitkeep 추가**

git은 빈 폴더를 추적하지 않으므로, 아직 파일이 없는 폴더에 `.gitkeep`을 추가한다.

```bash
touch projects/bidding/.gitkeep projects/formula/.gitkeep projects/quotation/.gitkeep projects/payment/.gitkeep
touch .github/workflows/.gitkeep
```

- [ ] **Step 5: 초기 커밋**

```bash
git add .gitignore projects/ docs/ .github/
git commit -m "chore: initialize monorepo folder structure

4개 모듈 독립 폴더 + docs + GitHub Actions 구조 생성"
```

---

## Task 2: 오케스트레이터 CLAUDE.md 작성

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: CLAUDE.md 작성**

```markdown
# 덱스트 자동화 프로젝트 — 오케스트레이터

## 프로젝트 개요

덱스트 업무 자동화를 위한 4개 독립 모듈을 병렬 개발한다.
각 모듈은 직원 누구나 브라우저로 사용할 수 있는 독립 웹 애플리케이션이다.

설계서: `docs/superpowers/specs/2026-05-08-dext-multi-agent-design.md`

## 세션 시작 프로토콜

1. `docs/status.md`를 읽어 전체 TF 진행 상황을 파악한다
2. 사용자에게 현재 상태를 간략히 보고한다
3. 사용자 지시에 따라 행동한다

## TF 라우팅

| TF | 모듈 | 폴더 | 핵심 기능 |
|----|------|------|----------|
| TF1 | 입찰공고 | `projects/bidding/` | 나라장터 Open API + 필터링 + 웹 대시보드 |
| TF2 | 수식추출 | `projects/formula/` | 모집요강 PDF → 점수 산출 공식 추출 |
| TF3 | 견적서 | `projects/quotation/` | 견적서 작성 + Daum 메일 발송 |
| TF4 | 결제정리 | `projects/payment/` | 결제 정리 업무 자동화 (상세 TBD) |

## TF 파견 방법

사용자가 특정 모듈 작업을 지시하면, Agent 도구를 worktree 격리 모드로 호출한다.

### 단일 TF 파견

```
Agent({
  description: "TF1: 입찰공고 — [구체적 작업]",
  prompt: "[모듈 AGENTS.md의 컨텍스트를 포함한 구체적 지시]. 작업 완료 후 반드시 docs/status.md를 업데이트하라.",
  isolation: "worktree"
})
```

### 병렬 TF 파견

독립 모듈이므로 여러 TF를 동시에 파견할 수 있다. 하나의 메시지에 여러 Agent 호출을 포함한다.

## 규칙

- 각 TF는 자기 폴더(`projects/xxx/`) 안에서만 작업한다
- TF에게 작업 지시 시 반드시 "작업 완료 후 docs/status.md를 업데이트하라"를 포함한다
- TF에게 지시할 때 해당 모듈의 AGENTS.md 내용을 프롬프트에 포함한다
- 결과물은 Claude Code 없이 독립 동작하는 웹 애플리케이션이어야 한다
- 기술 스택은 각 TF가 모듈 특성에 맞게 자율 결정한다
- 진행 상황 보고 요청 시 `docs/status.md`를 읽어 답한다
```

- [ ] **Step 2: 커밋**

```bash
git add CLAUDE.md
git commit -m "feat: add orchestrator CLAUDE.md

오케스트레이터 역할 정의 — 세션 프로토콜, TF 라우팅, 파견 방법, 규칙"
```

---

## Task 3: TF1 입찰공고 AGENTS.md 작성

**Files:**
- Create: `projects/bidding/AGENTS.md`

- [ ] **Step 1: AGENTS.md 작성**

```markdown
# TF1: 입찰공고 모듈

## 역할

나라장터(G2B) 입찰공고 자동 모니터링, 필터링, 의사결정 지원 웹 대시보드를 개발한다.

## 작업 범위

- `projects/bidding/` 폴더 안에서만 작업한다
- 다른 프로젝트 폴더를 절대 수정하지 않는다

## 요구사항

1. 나라장터 Open API (data.g2b.go.kr) 호출로 입찰공고 데이터 수집
2. 1차 자동 필터: 키워드 + 발주기관 유형(대학) + 금액 범위 + 커스텀 규칙
3. 웹 대시보드: 필터 통과 공고 목록 표시
4. 담당자 2차 확인: 참여/패스 버튼
5. 자동 정리: 참여 결정 시 관련 서류 다운로드 + 구글 스프레드시트 기입
6. 크론 스케줄링: 매일 자동 체크

## 기술 스택

모듈 특성에 맞는 최적 스택을 자율 결정한다.
참고 방향: Python 중심 (API 호출 + 자동화 생태계)

## 사용자

- 담당자 (개발자가 아닌 직원, 수시 변경 가능)
- 인증: 의사결정 추적 필요 시 간단 인증 도입 검토

## 참고 자료

- 설계서: `docs/superpowers/specs/2026-05-08-dext-multi-agent-design.md` (섹션 3-1)
- 나라장터 Open API: https://data.g2b.go.kr
- 공공데이터포털 인증키 필요

## 작업 완료 규칙

작업이 끝나면 반드시 프로젝트 루트의 `docs/status.md`를 업데이트한다:
- 무엇을 했는지
- 다음에 할 일
- 현재 상태 (진행중 / 완료 / 블로커)
```

- [ ] **Step 2: .gitkeep 제거 + 커밋**

```bash
rm projects/bidding/.gitkeep
git add projects/bidding/AGENTS.md
git commit -m "feat: add TF1 bidding module AGENTS.md

입찰공고 모듈 서브에이전트 역할/규칙/요구사항 정의"
```

---

## Task 4: TF2 수식추출 AGENTS.md 작성

**Files:**
- Create: `projects/formula/AGENTS.md`

- [ ] **Step 1: AGENTS.md 작성**

```markdown
# TF2: 수식추출 모듈

## 역할

대학 모집요강 PDF에서 수시/정시 점수 산출 공식을 자동 추출하는 웹 애플리케이션을 개발한다.

## 작업 범위

- `projects/formula/` 폴더 안에서만 작업한다
- 다른 프로젝트 폴더를 절대 수정하지 않는다

## 요구사항

1. 모집요강 PDF 업로드 기능
2. PDF 파싱: 텍스트 + 표 추출
3. 점수 산출 공식 추출: 수시/정시 배점 비율, 반영 비율, 가중치 테이블, 가산점 규칙
4. 구조화된 결과 표시 + 다운로드 옵션

## "수식"이란

수학 수식이 아닌 입시 점수 산출 공식.
예: "학생부 40% + 수능 60%", 영역별 반영 비율표, 가산점 규칙 등.
모집요강 PDF 내 텍스트/표 형태로 존재.

## 기술 스택

모듈 특성에 맞는 최적 스택을 자율 결정한다.
참고 방향: Python 중심 (PDF 파싱 + AI 라이브러리)

## 사용자

- 담당 직원 (변경 가능)
- 인증: 불필요 (PDF 올려서 결과 받는 도구)

## 참고 자료

- 설계서: `docs/superpowers/specs/2026-05-08-dext-multi-agent-design.md` (섹션 3-2)

## 작업 완료 규칙

작업이 끝나면 반드시 프로젝트 루트의 `docs/status.md`를 업데이트한다:
- 무엇을 했는지
- 다음에 할 일
- 현재 상태 (진행중 / 완료 / 블로커)
```

- [ ] **Step 2: .gitkeep 제거 + 커밋**

```bash
rm projects/formula/.gitkeep
git add projects/formula/AGENTS.md
git commit -m "feat: add TF2 formula module AGENTS.md

수식추출 모듈 서브에이전트 역할/규칙/요구사항 정의"
```

---

## Task 5: TF3 견적서 AGENTS.md 작성

**Files:**
- Create: `projects/quotation/AGENTS.md`

- [ ] **Step 1: AGENTS.md 작성**

```markdown
# TF3: 견적서 모듈

## 역할

대학별 견적서를 작성하고 담당자 확인 후 메일로 자동 발송하는 웹 애플리케이션을 개발한다.

## 작업 범위

- `projects/quotation/` 폴더 안에서만 작업한다
- 다른 프로젝트 폴더를 절대 수정하지 않는다

## 요구사항

1. 대학, 금액, 담당자 메일 선택 UI
2. 견적서 자동 생성 (템플릿 기반)
3. 미리보기 + 담당자 확인
4. 메일 자동 발송 (담당자 개인 Daum 회사 메일 계정에서 발송)
5. 모바일 반응형 — 이동 중에도 확인/발송 가능

## 메일 발송

- 발송 주체: 담당자 개인 Daum 회사 메일 계정
- 연동 방식: SMTP 또는 Daum 메일 API (개발 시 최적 방식 결정)

## 기술 스택

모듈 특성에 맞는 최적 스택을 자율 결정한다.
참고 방향: 풀스택 JS 또는 Python — 모바일 UX가 핵심

## 사용자

- 담당자 (변경 가능)
- 인증: Daum 메일 연동 자체가 인증 역할

## 참고 자료

- 설계서: `docs/superpowers/specs/2026-05-08-dext-multi-agent-design.md` (섹션 3-3)

## 작업 완료 규칙

작업이 끝나면 반드시 프로젝트 루트의 `docs/status.md`를 업데이트한다:
- 무엇을 했는지
- 다음에 할 일
- 현재 상태 (진행중 / 완료 / 블로커)
```

- [ ] **Step 2: .gitkeep 제거 + 커밋**

```bash
rm projects/quotation/.gitkeep
git add projects/quotation/AGENTS.md
git commit -m "feat: add TF3 quotation module AGENTS.md

견적서 모듈 서브에이전트 역할/규칙/요구사항 정의"
```

---

## Task 6: TF4 결제정리 AGENTS.md 작성

**Files:**
- Create: `projects/payment/AGENTS.md`

- [ ] **Step 1: AGENTS.md 작성**

```markdown
# TF4: 결제정리 모듈

## 역할

혜정팀장님이 수행하는 결제 정리 업무를 자동화하는 웹 애플리케이션을 개발한다.

## 작업 범위

- `projects/payment/` 폴더 안에서만 작업한다
- 다른 프로젝트 폴더를 절대 수정하지 않는다

## 현재 상태

상세 워크플로우 미파악. 혜정팀장님 업무 프로세스 파악 후 이 파일을 구체적 요구사항으로 업데이트한다.

## 기술 스택

업무 파악 후 결정

## 사용자

- 혜정팀장님 및 후임자

## 참고 자료

- 설계서: `docs/superpowers/specs/2026-05-08-dext-multi-agent-design.md` (섹션 3-4)

## 작업 완료 규칙

작업이 끝나면 반드시 프로젝트 루트의 `docs/status.md`를 업데이트한다:
- 무엇을 했는지
- 다음에 할 일
- 현재 상태 (진행중 / 완료 / 블로커)
```

- [ ] **Step 2: .gitkeep 제거 + 커밋**

```bash
rm projects/payment/.gitkeep
git add projects/payment/AGENTS.md
git commit -m "feat: add TF4 payment module AGENTS.md

결제정리 모듈 서브에이전트 역할/규칙 정의 (상세 요구사항 TBD)"
```

---

## Task 7: docs/status.md 진행 현황 대시보드 생성

**Files:**
- Create: `docs/status.md`

- [ ] **Step 1: status.md 작성**

```markdown
# 덱스트 자동화 프로젝트 — TF 진행 현황

> 이 파일은 각 TF가 작업 완료 시 자동 업데이트한다.
> 오케스트레이터는 세션 시작 시 이 파일을 먼저 읽는다.

## TF1: 입찰공고

| 항목 | 내용 |
|------|------|
| 상태 | 🔴 미착수 |
| 마지막 업데이트 | - |
| 완료한 작업 | - |
| 다음 할 일 | Phase 2 착수 대기 |
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
```

- [ ] **Step 2: 커밋**

```bash
git add docs/status.md
git commit -m "feat: add TF progress dashboard (docs/status.md)

세션 간 컨텍스트 유지를 위한 진행 현황 대시보드 초기 템플릿"
```

---

## Task 8: 프로젝트 README.md 작성

**Files:**
- Create: `README.md`

- [ ] **Step 1: README.md 작성**

```markdown
# dext-ax — 덱스트 업무 자동화

4개 독립 모듈을 Claude Code 멀티에이전트 체제로 병렬 개발한다.

## 모듈

| 모듈 | 폴더 | 설명 | 상태 |
|------|------|------|------|
| 입찰공고 | `projects/bidding/` | 나라장터 입찰공고 모니터링 + 필터링 + 대시보드 | 미착수 |
| 수식추출 | `projects/formula/` | 모집요강 PDF → 점수 산출 공식 추출 | 미착수 |
| 견적서 | `projects/quotation/` | 견적서 작성 + 메일 발송 | 미착수 |
| 결제정리 | `projects/payment/` | 결제 정리 업무 자동화 | 미착수 |

## 구조

각 `projects/xxx/`는 자기만의 의존성, 기술 스택, 배포 방식을 가진 완전 독립 프로젝트.

## 개발 방식

- 오케스트레이터(CLAUDE.md)가 모듈별 TF 서브에이전트를 worktree로 파견
- 각 TF는 자기 폴더의 AGENTS.md에 정의된 역할/규칙에 따라 독립 개발
- 진행 현황: `docs/status.md`

## 설계 문서

- 설계서: `docs/superpowers/specs/2026-05-08-dext-multi-agent-design.md`
- 구현 계획: `docs/superpowers/plans/`
```

- [ ] **Step 2: 커밋**

```bash
git add README.md
git commit -m "docs: add project README

프로젝트 개요, 모듈 목록, 개발 방식 설명"
```

---

## Task 9: 설정 검증

**Files:** (수정 없음 — 검증만)

- [ ] **Step 1: 폴더 구조 확인**

```bash
find . -not -path './.git/*' -not -path './.git' | sort
```

Expected output:
```
.
./.github
./.github/workflows
./.github/workflows/.gitkeep
./.gitignore
./CLAUDE.md
./README.md
./docs
./docs/status.md
./docs/superpowers
./docs/superpowers/plans
./docs/superpowers/plans/2026-05-08-phase1-infrastructure-setup.md
./docs/superpowers/specs
./docs/superpowers/specs/2026-05-08-dext-multi-agent-design.md
./projects
./projects/bidding
./projects/bidding/AGENTS.md
./projects/formula
./projects/formula/AGENTS.md
./projects/payment
./projects/payment/AGENTS.md
./projects/quotation
./projects/quotation/AGENTS.md
```

- [ ] **Step 2: 모든 핵심 파일 존재 확인**

```bash
for f in CLAUDE.md docs/status.md projects/bidding/AGENTS.md projects/formula/AGENTS.md projects/quotation/AGENTS.md projects/payment/AGENTS.md; do
  [ -f "$f" ] && echo "✅ $f" || echo "❌ $f MISSING"
done
```

Expected: 모두 ✅

- [ ] **Step 3: git log로 커밋 이력 확인**

```bash
git log --oneline
```

Expected: Task 1~8의 커밋 8개가 순서대로 나열됨

- [ ] **Step 4: 오케스트레이터 동작 시뮬레이션**

새 Claude Code 세션에서 다음을 확인:
1. CLAUDE.md가 자동으로 로드되는지
2. "현재 진행 상황 알려줘"라고 하면 `docs/status.md`를 읽고 보고하는지
3. "입찰공고 모듈 시작해"라고 하면 TF1을 worktree로 파견하려고 하는지

이 검증은 수동 확인이며, 자동 테스트 대상이 아니다.
