# Test Evidence: LL-GIT-004 GitHub README image verification

날짜: 2026-06-15

## 범위

`git push origin main` 이후 GitHub repository의 README와 demo screenshot asset이 정상적으로 올라갔는지 확인했다.

## 확인 결과

| 항목 | 결과 |
|---|---|
| Repository | `figure-2/LocalLens` |
| Visibility | Private |
| Branch | `main` |
| README verification target commit | `489ba99969d9bf2064f9b6a8ac3c4d49d6dd2707` |
| Remote `main` at verification time | `489ba99969d9bf2064f9b6a8ac3c4d49d6dd2707` |
| `git push origin main` | PASS |
| GitHub API `README.md` 확인 | PASS |
| GitHub API demo image asset 확인 | PASS |
| Demo image path | `docs/assets/locallens-real-demo-ui.png` |
| Demo image size | 576,820 bytes |
| GitHub Markdown API image reference | PASS |
| GitHub Markdown API `<img>` tag | PASS |
| 비인증 GitHub repository page | 404, private repo visibility boundary |
| 비인증 raw image URL | 404, private repo visibility boundary |

## 실행 근거

확인한 명령:

```powershell
git rev-parse HEAD
git ls-remote origin refs/heads/main
gh repo view figure-2/LocalLens --json name,visibility,defaultBranchRef,url
gh api repos/figure-2/LocalLens/readme
gh api repos/figure-2/LocalLens/contents/docs/assets/locallens-real-demo-ui.png
gh api markdown -X POST
```

보안상 GitHub API 응답의 tokenized `download_url`은 기록하지 않는다.

## claim boundary

이 evidence로 주장 가능한 것:

- 공개 repo push 전 코드와 문서가 GitHub private repository `main`에 반영됐다.
- 인증된 GitHub API 기준 README와 demo screenshot asset이 존재한다.
- GitHub Markdown API 기준 README image markdown이 `<img>` tag로 변환된다.

주장하면 안 되는 것:

- 비로그인 사용자가 GitHub repository page에서 README 이미지를 볼 수 있다.
- repository가 public으로 공개된 상태다.
- GitHub Pages 또는 외부 배포 환경에서 렌더링을 확인했다.
