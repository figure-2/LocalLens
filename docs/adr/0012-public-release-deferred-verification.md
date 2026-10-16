# ADR 0012: Public release verification deferred

날짜: 2026-06-15

## 상태

Accepted

## 배경

LocalLens repository는 현재 private 상태로 유지한다. 전체 정리, 검증, README, evidence가 완료된 뒤 사용자가 직접 public 전환을 수행할 예정이다.

private 상태에서는 비인증 GitHub page와 raw image URL이 404를 반환한다. 이는 렌더링 실패가 아니라 repository visibility boundary다.

## 결정

public 전환 전에는 다음만 완료 기준으로 둔다.

- README가 image asset을 참조하는 경우 local image file이 존재하는지 확인
- local HEAD와 remote `main`이 일치하는지 확인
- GitHub 인증 API로 `README.md` 존재 확인
- README가 image asset을 참조하는 경우 GitHub 인증 API와 Markdown API로 image 변환 확인

public 전환 후에는 다음을 추가로 확인한다.

- 비로그인 GitHub repository page 접근이 200을 반환하는지 확인
- README가 image asset을 참조하는 경우 비로그인 raw image URL 접근이 200을 반환하는지 확인
- README가 image asset을 참조하는 경우 GitHub README 화면에서 image가 실제로 보이는지 확인
- 확인 결과를 release evidence에 추가

## 검증 도구

`scripts/ll_public_readme_check.ps1`을 사용한다.

private 상태:

```powershell
.\scripts\ll_public_readme_check.ps1
```

public 전환 후:

```powershell
.\scripts\ll_public_readme_check.ps1 -ExpectPublic
```

## claim boundary

public 전환 전 주장 가능한 것:

- private GitHub repository에 README와 demo image asset이 반영됐다.
- 인증된 GitHub API 기준으로 README가 확인됐다.
- README가 image를 참조하는 경우에만 GitHub Markdown API 기준 image tag 변환을 주장할 수 있다.

public 전환 전 주장하면 안 되는 것:

- 비로그인 사용자가 GitHub README를 볼 수 있다.
- README에 image가 없는 상태에서 image 렌더링을 확인했다.
- public GitHub page 렌더링을 확인했다.
- GitHub Pages 또는 외부 배포 URL에서 확인했다.

## 다음 작업 지시서

`LL-PUBLIC-002`

| id | depends_on | scope | acceptance_tests | risk_level | rollback_plan |
|---|---|---|---|---|---|
| LL-PUBLIC-002 | 사용자의 repo public 전환 | 비로그인 GitHub README 렌더링 확인 | `scripts/ll_public_readme_check.ps1 -ExpectPublic`, 브라우저 README screenshot 확인 | 낮음 | repo visibility를 private으로 되돌리고 evidence에 실패 원인 기록 |
