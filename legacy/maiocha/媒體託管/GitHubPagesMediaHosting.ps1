Set-StrictMode -Version Latest
$safetyRepo = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) 'maiocha-media-host-staging'
. (Join-Path $safetyRepo 'safety/HostingSafety.ps1')

function Get-GitHubPagesHostingConfig {
    param([Parameter(Mandatory = $true)][string]$ConfigPath)
    $full = [IO.Path]::GetFullPath($ConfigPath)
    $bundle = Split-Path -Parent (Split-Path -Parent $full)
    $scope = Get-ScopedCampaignConfig -BundleFolder $bundle
    if ($full -cne [IO.Path]::GetFullPath((Join-Path $scope.source_root 'Hosting/hosting_config.json'))) { throw 'HOSTING_CONFIG_PATH_MISMATCH' }
    return $scope
}

function Get-PublicUrl {
    param([Parameter(Mandatory = $true)]$Config, [Parameter(Mandatory = $true)][string]$ObjectKey)
    return Get-ScopedHostedUrl $Config $ObjectKey
}

function Upload-Media {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)][string]$ObjectKey,
        [Parameter(Mandatory = $true)][string]$LocalPath,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    $scope = Assert-HostingScope $Config
    $key = Assert-ObjectKeyBoundary $ObjectKey $scope.hosting_namespace
    $source = Assert-LocalPathBoundary $scope.source_root $LocalPath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'HOSTING_SOURCE_MISSING' }
    $actualHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($actualHash -ine $ExpectedSha256) { throw 'HOSTING_SOURCE_HASH_MISMATCH' }
    $scopeRoot = Join-Path $scope.staging_repository $scope.hosting_namespace
    $destination = Assert-LocalPathBoundary $scopeRoot (Join-Path $scope.staging_repository $key)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    $null = Assert-LocalPathBoundary $scopeRoot $destination
    Copy-Item -LiteralPath $source -Destination $destination -Force
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ine $ExpectedSha256) { throw 'HOSTING_COPIED_HASH_MISMATCH' }
    return [pscustomobject][ordered]@{
        hosting_provider = 'github_pages'; brand = $scope.brand; campaign_id = $scope.campaign_id
        hosting_namespace = $scope.hosting_namespace; hosted_object_key = $key
        public_url = Get-ScopedHostedUrl $scope $key
        upload_status = 'staged'; file_size = (Get-Item -LiteralPath $destination).Length; sha256 = $ExpectedSha256
    }
}

function Verify-PublicUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$ExpectedContentType,
        [Parameter(Mandatory = $true)][string]$LocalPath
    )
    if ($Url -notmatch '^https://') { return $false }
    $expectedHash = (Get-FileHash -LiteralPath $LocalPath -Algorithm SHA256).Hash
    $expectedSize = (Get-Item -LiteralPath $LocalPath).Length
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("maiocha-verify-" + [guid]::NewGuid().ToString('N'))
    $client = [Net.Http.HttpClient]::new()
    try {
        $client.Timeout = [TimeSpan]::FromMinutes(5)
        $response = $client.GetAsync($Url, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        try {
            if ([int]$response.StatusCode -ne 200) { return $false }
            if ([string]$response.Content.Headers.ContentType.MediaType -cne $ExpectedContentType) { return $false }
            $input = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $output = [IO.File]::Create($temp)
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        } finally { $response.Dispose() }
        return ((Get-Item -LiteralPath $temp).Length -eq $expectedSize -and (Get-FileHash -LiteralPath $temp -Algorithm SHA256).Hash -ceq $expectedHash)
    } finally {
        $client.Dispose()
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Remove-Media {
    param([Parameter(Mandatory = $true)]$Config, [Parameter(Mandatory = $true)][string]$ObjectKey, [switch]$Confirm)
    $scope = Assert-HostingScope $Config
    $key = Assert-ObjectKeyBoundary $ObjectKey $scope.hosting_namespace
    $target = Assert-LocalPathBoundary (Join-Path $scope.staging_repository $scope.hosting_namespace) (Join-Path $scope.staging_repository $key)
    if (-not $Confirm) { throw 'HOSTING_DELETE_REQUIRES_CONFIRM' }
    if (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target -Force }
}

function Cleanup-CampaignMedia {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)][string]$CampaignPath,
        [Parameter(Mandatory = $true)][bool]$InstagramPublished,
        [Parameter(Mandatory = $true)][bool]$FinalMediaIdRecorded,
        [Parameter(Mandatory = $true)][bool]$RetentionExpired,
        [switch]$Confirm
    )
    $scope = Assert-HostingScope $Config
    $key = Assert-ObjectKeyBoundary $CampaignPath $scope.hosting_namespace -AllowRoot
    $scopeRoot = Join-Path $scope.staging_repository $scope.hosting_namespace
    $target = Assert-LocalPathBoundary $scopeRoot (Join-Path $scope.staging_repository $key) -AllowRoot
    if (-not $Confirm) { throw 'HOSTING_CLEANUP_REQUIRES_CONFIRM' }
    if (-not ($InstagramPublished -and $FinalMediaIdRecorded -and $RetentionExpired)) { throw '尚未符合發布成功、Media ID 已記錄及緩衝期結束三項 cleanup 條件。' }
    if (Test-Path -LiteralPath $target -PathType Container) {
        foreach ($entry in Get-ChildItem -LiteralPath $target -Recurse -Force) {
            $null = Assert-LocalPathBoundary $scopeRoot $entry.FullName
        }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
