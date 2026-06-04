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
