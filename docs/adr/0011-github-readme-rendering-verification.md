# ADR 0011: GitHub README rendering verification boundary

날짜: 2026-06-15

## 상태

Accepted

## 배경

LL-GIT 단계에서 `main` 브랜치 push 후 GitHub README 이미지 렌더링 확인이 필요했다. 다만 대상 repository는 private 상태이므로, 비인증 웹 요청으로 GitHub repository page와 raw image URL을 확인하면 404가 반환된다.

따라서 공개 웹 접근 성공을 claim하지 않고, 인증된 GitHub CLI/API 확인과 GitHub Markdown 렌더링 API 결과를 release evidence로 기록하기로 했다.

## 결정

GitHub README 확인은 다음 기준으로 기록한다.

- `git push origin main` 성공 여부
- local HEAD와 remote `origin/main` commit hash 일치 여부
- GitHub CLI 인증 API로 `README.md` 존재 확인
- GitHub CLI 인증 API로 `docs/assets/locallens-real-demo-ui.png` 존재 확인
- GitHub Markdown API 변환 결과에 image reference와 `<img>` tag가 생성되는지 확인
- private repo 특성상 비인증 browser/raw URL 404는 실패가 아니라 visibility boundary로 기록

## claim boundary

주장 가능한 것:

- GitHub remote `main`이 local HEAD와 일치한다.
- 인증된 GitHub API 기준 README와 demo image asset이 repository에 존재한다.
- GitHub Markdown API 기준 README의 image markdown이 `<img>` tag로 변환된다.

주장하면 안 되는 것:

- private repository를 비로그인 브라우저에서 확인 가능하다.
- GitHub public page에서 이미지가 공개 렌더링된다.
- GitHub Pages 또는 배포 URL에서 렌더링이 확인됐다.

## 검증

검증 결과는 `docs/test_evidence/2026-06-15-ll-github-readme-rendering.md`에 기록한다.
