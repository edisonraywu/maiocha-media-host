param(
    [string]$Workspace = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'HostingSafety.ps1')
$repo = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -Raw -LiteralPath (Join-Path $repo 'legacy/install-manifest.json') | ConvertFrom-Json
$plans = @()
foreach ($entry in $manifest.files) {
    $source = Assert-LocalPathBoundary (Join-Path $repo 'legacy/maiocha') (Join-Path $repo $entry.source)
    $target = Assert-LocalPathBoundary (Join-Path $Workspace '買房喵查局內容系統/11_系統工具') (Join-Path $Workspace $entry.destination)
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw 'LEGACY_DEPLOYMENT_TARGET_MISSING' }
    $before = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    $desired = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($before -cne $desired -and $before -cne $entry.original_sha256) { throw 'LEGACY_DEPLOYMENT_LOCAL_CHANGES_REQUIRE_REVIEW' }
    $plans += [pscustomobject]@{entry=$entry;source=$source;target=$target;before=$before;desired=$desired}
}
if ($VerifyOnly) {
    $mismatch = @($plans | Where-Object { $_.before -cne $_.desired })
    [pscustomobject]@{result=if($mismatch.Count){'FAIL'}else{'PASS'};files_checked=$plans.Count;outdated_count=$mismatch.Count;file_writes=0} | ConvertTo-Json
    if ($mismatch.Count) { exit 2 }
    exit 0
}
$backupRoot = Join-Path $Workspace ('.local/isolation-backup/' + [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss-ffff'))
$changed = @()
foreach ($plan in $plans) {
    if ($plan.before -ceq $plan.desired) { continue }
    if ((Get-FileHash -LiteralPath $plan.target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $plan.before) { throw 'LEGACY_DEPLOYMENT_CONCURRENT_CHANGE' }
    $backup = Assert-LocalPathBoundary $backupRoot (Join-Path $backupRoot $plan.entry.destination)
    New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
    Copy-Item -LiteralPath $plan.target -Destination $backup
    Copy-Item -LiteralPath $plan.source -Destination $plan.target -Force
    if ((Get-FileHash -LiteralPath $plan.target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $plan.desired) { throw 'LEGACY_DEPLOYMENT_HASH_MISMATCH' }
    $changed += [pscustomobject]@{path=$plan.entry.destination;before_sha256=$plan.before;after_sha256=$plan.desired}
}
$report = [pscustomobject]@{result='PASS';files_checked=$plans.Count;changed=$changed;backup_root=$backupRoot;content_files_moved=0}
$report | ConvertTo-Json -Depth 6
if ($changed.Count) { $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $backupRoot 'deployment.json') -Encoding utf8 }
