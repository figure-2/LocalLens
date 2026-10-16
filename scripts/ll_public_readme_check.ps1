param(
    [string]$Repo = "figure-2/LocalLens",
    [string]$ImagePath = "docs/assets/locallens-real-demo-ui.png",
    [switch]$ExpectPublic
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
[Console]::InputEncoding = $Utf8NoBom

$Root = Split-Path -Parent $PSScriptRoot
$ReadmePath = Join-Path $Root "README.md"
$ImageFile = Join-Path $Root ($ImagePath -replace "/", "\")

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-HttpStatus {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 30 -SkipHttpErrorCheck
        return [pscustomobject]@{
            Url = $Url
            Status = [int]$response.StatusCode
            ContentType = ($response.Headers["Content-Type"] -join ";")
        }
    } catch {
        return [pscustomobject]@{
            Url = $Url
            Status = -1
            ContentType = ""
            Error = $_.Exception.Message
        }
    }
}

Push-Location $Root
try {
    Write-Step "Local README asset reference check"
    if (-not (Test-Path -LiteralPath $ReadmePath)) {
        throw "README.md not found: $ReadmePath"
    }
    $readme = Get-Content -Raw -LiteralPath $ReadmePath
    $readmeReferencesImage = $readme -match [regex]::Escape($ImagePath)
    if (-not (Test-Path -LiteralPath $ImageFile)) {
        if ($readmeReferencesImage) {
            throw "README image asset not found: $ImageFile"
        }
    }
    if ($readmeReferencesImage) {
        Write-Host "PASS local README references $ImagePath"
    } else {
        Write-Host "SKIP local README does not reference $ImagePath"
    }

    Write-Step "Git remote commit check"
    $localHead = (git rev-parse HEAD).Trim()
    $remoteLine = (git ls-remote origin refs/heads/main).Trim()
    if (-not $remoteLine) {
        throw "origin main not found"
    }
    $remoteHead = ($remoteLine -split "\s+")[0]
    if ($localHead -ne $remoteHead) {
        throw "Local HEAD and remote main differ. local=$localHead remote=$remoteHead"
    }
    Write-Host "PASS local HEAD matches remote main: $localHead"
    $dirty = git status --porcelain
    if ($dirty) {
        Write-Host "WARN working tree has uncommitted changes; GitHub API checks reflect remote main, not local edits." -ForegroundColor Yellow
    }

    Write-Step "GitHub authenticated API check"
    $repoInfo = gh repo view $Repo --json name,visibility,defaultBranchRef,url | ConvertFrom-Json
    $readmeInfo = gh api "repos/$Repo/readme" | ConvertFrom-Json
    $imageInfo = $null
    if ($readmeInfo.path -ne "README.md") {
        throw "GitHub API README path mismatch: $($readmeInfo.path)"
    }
    if ($readmeReferencesImage) {
        $imageInfo = gh api "repos/$Repo/contents/$ImagePath" | ConvertFrom-Json
        if ($imageInfo.path -ne $ImagePath) {
            throw "GitHub API image path mismatch: $($imageInfo.path)"
        }
    }
    Write-Host "PASS GitHub API README: $($readmeInfo.html_url)"
    if ($readmeReferencesImage) {
        Write-Host "PASS GitHub API image: $($imageInfo.html_url)"
    } else {
        Write-Host "SKIP GitHub API image check because README has no image reference"
    }

    Write-Step "GitHub Markdown API image conversion check"
    $payload = @{
        text = $readme
        mode = "gfm"
        context = $Repo
    } | ConvertTo-Json -Compress
    $tmp = Join-Path $env:TEMP "locallens_readme_markdown_payload.json"
    Set-Content -Path $tmp -Value $payload -Encoding UTF8
    $html = (gh api markdown -X POST --input $tmp) -join "`n"
    if ($readmeReferencesImage) {
        $escapedImagePath = [regex]::Escape($ImagePath)
        if (($html -notmatch $escapedImagePath) -or ($html -notmatch "<img")) {
            throw "GitHub Markdown API did not produce expected image tag."
        }
        Write-Host "PASS GitHub Markdown API image tag conversion"
    } else {
        Write-Host "SKIP GitHub Markdown API image tag conversion because README has no image reference"
    }

    Write-Step "Unauthenticated public access check"
    $repoUrl = "https://github.com/$Repo"
    $rawUrl = "https://raw.githubusercontent.com/$Repo/main/$ImagePath"
    $repoStatus = Get-HttpStatus -Url $repoUrl
    $rawStatus = Get-HttpStatus -Url $rawUrl

    $summary = [ordered]@{
        repo = $Repo
        visibility = $repoInfo.visibility
        local_head = $localHead
        remote_head = $remoteHead
        readme_api = "PASS"
        image_api = if ($readmeReferencesImage) { "PASS" } else { "SKIP" }
        markdown_img = if ($readmeReferencesImage) { "PASS" } else { "SKIP" }
        unauth_repo_status = $repoStatus.Status
        unauth_raw_status = $rawStatus.Status
        expect_public = [bool]$ExpectPublic
    }
    $summary.GetEnumerator() | ForEach-Object {
        Write-Host ("{0}: {1}" -f $_.Key, $_.Value)
    }

    if ($ExpectPublic) {
        if ($repoStatus.Status -ne 200 -or $rawStatus.Status -ne 200) {
            throw "Expected public repository rendering, but unauthenticated checks did not return 200."
        }
        Write-Host "PASS public unauthenticated README/image access"
    } else {
        if ($repoStatus.Status -ne 200 -or $rawStatus.Status -ne 200) {
            Write-Host "INFO unauthenticated access is not required before public release." -ForegroundColor Yellow
        }
    }
} finally {
    Pop-Location
}
