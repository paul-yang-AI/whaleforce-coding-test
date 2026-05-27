param(
    [Parameter(Mandatory = $true)]
    [string]$GitHubUser,
    [string]$RepoName = "whaleforce-coding-test",
    [string]$Branch = "master"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$trackedEnv = git ls-files .env 2>$null
if ($trackedEnv) {
    Write-Error ".env is tracked by git — remove it before push."
}

$remoteUrl = "https://github.com/$GitHubUser/$RepoName.git"
Write-Host "Target: $remoteUrl (private repo must exist on GitHub first)"

$hasOrigin = (git remote) -contains "origin"
if ($hasOrigin) {
    $existing = git remote get-url origin
    if ($existing -ne $remoteUrl) {
        Write-Host "Updating origin from $existing"
        git remote set-url origin $remoteUrl
    }
} else {
    git remote add origin $remoteUrl
}

Write-Host "Pushing branch $Branch ..."
git push -u origin $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Push failed. Create a PRIVATE empty repo first:"
    Write-Host "  https://github.com/new?name=$RepoName"
    Write-Host "Then re-run: .\scripts\push_private.ps1 -GitHubUser $GitHubUser"
    exit 1
}

Write-Host "Done. Private push OK. Make repo Public before final submission."
