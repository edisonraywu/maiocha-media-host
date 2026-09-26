# Explicit multi-brand dispatcher. Existing named maiocha entry remains unchanged in location.
param(
    [ValidateSet('maiocha','baobao')][string]$Brand,
    [switch]$DescribeContext,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
)
$ErrorActionPreference = 'Stop'
if (-not $PSBoundParameters.ContainsKey('Brand') -or -not $Brand) { throw 'EXPLICIT_BRAND_REQUIRED' }
$Brand = $Brand.ToLowerInvariant()
if (@($Arguments | Where-Object { $_ -match '^(--?brand)(=|$)' }).Count -gt 0) { throw 'DUPLICATE_BRAND_ARGUMENT_FORBIDDEN' }
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$entry = if ($Brand -ceq 'maiocha') { Join-Path $PSScriptRoot '同步發布CampaignV2.ps1' } else { Join-Path $workspace 'baobao.ps1' }
if ($DescribeContext) {
    [pscustomobject]@{brand=$Brand; entry=$entry; publication_requested=$false} | ConvertTo-Json -Compress
    return
}
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw 'BRAND_ENTRY_NOT_FOUND' }
# A separate PowerShell invocation preserves named arguments for the existing maiocha CLI.
$engine = (Get-Process -Id $PID).Path
& $engine -NoProfile -File $entry @Arguments
exit $LASTEXITCODE
