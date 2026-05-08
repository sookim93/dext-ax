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
