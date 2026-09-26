param(
    [Parameter(Mandatory = $true)][string]$BundleFolder,
    [string]$PagesBaseUrl = 'https://edisonraywu.github.io/maiocha-media-host',
    [string]$OwnerRepo = 'edisonraywu/maiocha-media-host',
    [string]$StagingRepository = 'C:\Users\onepi\Documents\ChatGPT\New project\maiocha-media-host-staging'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'GitHubPagesMediaHosting.ps1')
$scope = Get-ScopedCampaignConfig -BundleFolder $BundleFolder
if ($PagesBaseUrl -cne $scope.pages_base_url -or $OwnerRepo -cne $scope.owner_repo -or [IO.Path]::GetFullPath($StagingRepository) -cne $scope.staging_repository -or $scope.campaign_path -cne 'media/maiocha-launch-2026-09-16') { throw 'HOSTING_FINALIZER_CONTEXT_MISMATCH' }

function Set-Property($Object, [string]$Name, $Value) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
    else { $property.Value = $Value }
}

function Copy-Exact([string]$Source, [string]$Destination) {
    $null = Assert-LocalPathBoundary $scope.source_root $Source
    $null = Assert-LocalPathBoundary $scope.source_root $Destination
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    if ((Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash -cne (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash) { throw "Bundle 複製 SHA-256 不一致：$Destination" }
}

function Receive-AnonymousAsset([string]$Url, [string]$LocalPath, [string]$ExpectedType, [bool]$RequireRange) {
    $expectedHash = (Get-FileHash -LiteralPath $LocalPath -Algorithm SHA256).Hash
    $expectedSize = (Get-Item -LiteralPath $LocalPath).Length
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("maiocha-pages-" + [guid]::NewGuid().ToString('N'))
    $client = [Net.Http.HttpClient]::new()
    try {
        $client.Timeout = [TimeSpan]::FromMinutes(8)
        $response = $client.GetAsync($Url, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        try {
            $status = [int]$response.StatusCode
            $contentType = [string]$response.Content.Headers.ContentType.MediaType
            $finalUrl = [string]$response.RequestMessage.RequestUri.AbsoluteUri
            if ($status -ne 200) { throw "HTTP $status" }
            if ($contentType -cne $ExpectedType) { throw "Content-Type $contentType" }
            if ($finalUrl -match '(login|signin)') { throw 'URL 導向登入頁。' }
            $input = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $output = [IO.File]::Create($temp)
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        } finally { $response.Dispose() }
        $downloadSize = (Get-Item -LiteralPath $temp).Length
        $downloadHash = (Get-FileHash -LiteralPath $temp -Algorithm SHA256).Hash
        $rangeStatus = $null
        if ($RequireRange) {
            $rangeRequest = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, $Url)
            $rangeRequest.Headers.Range = [Net.Http.Headers.RangeHeaderValue]::new(0, 1023)
            $rangeResponse = $client.SendAsync($rangeRequest).GetAwaiter().GetResult()
            try { $rangeStatus = [int]$rangeResponse.StatusCode } finally { $rangeResponse.Dispose(); $rangeRequest.Dispose() }
            if ($rangeStatus -ne 206) { throw "Range request HTTP $rangeStatus" }
        }
        return [pscustomobject][ordered]@{
            https = $Url.StartsWith('https://')
            http_status = 200
            anonymous = $true
            final_url = $finalUrl
            content_type = $contentType
            file_size = $downloadSize
            sha256 = $downloadHash
            size_matches = ($downloadSize -eq $expectedSize)
            sha256_matches = ($downloadHash -ceq $expectedHash)
            range_status = $rangeStatus
            passed = ($Url.StartsWith('https://') -and $downloadSize -eq $expectedSize -and $downloadHash -ceq $expectedHash)
        }
    } finally {
        $client.Dispose()
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

$bundle = (Resolve-Path -LiteralPath $BundleFolder).Path
$manifestPath = Join-Path $bundle 'manifest.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ([string]$manifest.source_selection_mode -cne 'exact_paths_only' -or [bool]$manifest.wildcards_allowed) { throw '正式 Manifest 未禁用 wildcard。' }

# 完成唯一正式 Bundle 的固定目錄；只複製已核准檔案，不改設計或內容。
$feedSources = @($manifest.media.feed_carousel.children | ForEach-Object { [string]$_.exact_path })
$feedNames = @('01_輪播01.jpg','02_輪播02.jpg','03_輪播03_精修版.jpg','04_輪播04.jpg','05_輪播05_精修版.jpg','06_輪播06.jpg')
for ($i=0; $i -lt 6; $i++) {
    $destination = Join-Path $bundle ("Feed\\" + $feedNames[$i])
    Copy-Exact $feedSources[$i] $destination
    $manifest.media.feed_carousel.children[$i].exact_path = $destination
    $manifest.media.feed_carousel.children[$i].filename = $feedNames[$i]
}
$textMap = @(
    @{ source=[string]$manifest.copy.feed_caption.exact_path; name='Feed_caption.md'; node=$manifest.copy.feed_caption },
    @{ source=[string]$manifest.copy.reel_caption.exact_path; name='Reel_caption.md'; node=$manifest.copy.reel_caption },
    @{ source=[string]$manifest.copy.story_text.exact_path; name='Story文字紀錄.md'; node=$manifest.copy.story_text }
)
foreach ($entry in $textMap) {
    $destination = Join-Path $bundle ("Text\\" + $entry.name)
    Copy-Exact $entry.source $destination
    $entry.node.exact_path = $destination
    $entry.node.sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
}
$manifest.media.feed_carousel.caption_path = [string]$manifest.copy.feed_caption.exact_path
$manifest.media.feed_carousel.caption_sha256 = [string]$manifest.copy.feed_caption.sha256
$manifest.media.reel.caption_path = [string]$manifest.copy.reel_caption.exact_path
$manifest.media.reel.caption_sha256 = [string]$manifest.copy.reel_caption.sha256

$campaignPath = 'media/maiocha-launch-2026-09-16'
$targets = @(
    @{ asset=$manifest.media.feed_carousel.children[0]; object_key="$campaignPath/feed/01.jpg"; type='image/jpeg'; range=$false },
    @{ asset=$manifest.media.feed_carousel.children[1]; object_key="$campaignPath/feed/02.jpg"; type='image/jpeg'; range=$false },
    @{ asset=$manifest.media.feed_carousel.children[2]; object_key="$campaignPath/feed/03-refined.jpg"; type='image/jpeg'; range=$false },
    @{ asset=$manifest.media.feed_carousel.children[3]; object_key="$campaignPath/feed/04.jpg"; type='image/jpeg'; range=$false },
    @{ asset=$manifest.media.feed_carousel.children[4]; object_key="$campaignPath/feed/05-refined.jpg"; type='image/jpeg'; range=$false },
    @{ asset=$manifest.media.feed_carousel.children[5]; object_key="$campaignPath/feed/06.jpg"; type='image/jpeg'; range=$false },
    @{ asset=$manifest.media.reel; object_key="$campaignPath/reel/reel-24s-7-scenes.mp4"; type='video/mp4'; range=$true },
    @{ asset=$manifest.media.story_01; object_key="$campaignPath/story/01.jpg"; type='image/jpeg'; range=$false },
    @{ asset=$manifest.media.story_02; object_key="$campaignPath/story/02-refined.jpg"; type='image/jpeg'; range=$false },
    @{ asset=$manifest.media.story_03; object_key="$campaignPath/story/03.jpg"; type='image/jpeg'; range=$false }
)
if ($targets.Count -ne 10) { throw '正式素材不是 10 份。' }

$verifiedAt = (Get-Date).ToString('o')
$results = [Collections.Generic.List[object]]::new()
foreach ($target in $targets) {
    $asset = $target.asset
    $localPath = [IO.Path]::GetFullPath([string]$asset.exact_path)
    if (-not $localPath.StartsWith($bundle, [StringComparison]::OrdinalIgnoreCase)) { throw "素材超出正式 Bundle：$($asset.key)" }
    if ((Get-FileHash -LiteralPath $localPath -Algorithm SHA256).Hash -cne [string]$asset.sha256) { throw "本機 SHA-256 不一致：$($asset.key)" }
    $url = "$($PagesBaseUrl.TrimEnd('/'))/$($target.object_key)"
    $verification = Receive-AnonymousAsset -Url $url -LocalPath $localPath -ExpectedType $target.type -RequireRange $target.range
    if (-not [bool]$verification.passed) { throw "公開素材驗證失敗：$($asset.key)" }
    Set-Property $asset 'local_path' $localPath
    Set-Property $asset 'file_size' ([int64](Get-Item -LiteralPath $localPath).Length)
    Set-Property $asset 'hosting_provider' 'github_pages'
    Set-Property $asset 'hosted_object_key' ([string]$target.object_key)
    Set-Property $asset 'hosted_url' $url
    Set-Property $asset 'public_url' $url
    Set-Property $asset 'upload_status' 'uploaded'
    Set-Property $asset 'accessibility_status' 'verified'
    Set-Property $asset 'content_type' ([string]$target.type)
    Set-Property $asset 'uploaded_at' $verifiedAt
    Set-Property $asset 'verified_at' $verifiedAt
    $results.Add([pscustomobject][ordered]@{
        key = [string]$asset.key
        filename = [string]$asset.filename
        sequence = [int]$asset.sequence
        url = $url
        content_type = [string]$verification.content_type
        file_size = [int64]$verification.file_size
        sha256 = [string]$verification.sha256
        range_status = $verification.range_status
        passed = [bool]$verification.passed
    })
}

$manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding utf8

$hostingFolder = Join-Path $bundle 'Hosting'
$reportsFolder = Join-Path $bundle 'Reports'
$manifestFolder = Join-Path $bundle 'Manifest'
New-Item -ItemType Directory -Force -Path $hostingFolder,$reportsFolder,$manifestFolder | Out-Null
$config = [pscustomobject][ordered]@{
    provider = 'github_pages'
    owner_repo = $OwnerRepo
    branch = 'main'
    pages_base_url = $PagesBaseUrl
    campaign_path = $campaignPath
    staging_repository = $StagingRepository
    free_plan = $true
    credit_card_required = $false
    paid_features_enabled = $false
}
$config | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $hostingFolder 'hosting_config.json') -Encoding utf8
$status = [pscustomobject][ordered]@{
    provider = 'github_pages'
    campaign_id = [string]$manifest.campaign_id
    status = 'verified'
    free_plan = $true
    credit_card_required = $false
    cost_risk = 'No paid feature enabled; public repository GitHub Pages is used.'
    uploaded_count = 10
    public_url_verified_count = 10
    verified_at = $verifiedAt
    cleanup_policy = [ordered]@{ enabled=$true; run_before_publish=$false; requires_published=$true; requires_final_media_id=$true; requires_retention_expired=$true }
    items = $results
}
$status | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $hostingFolder 'hosting_status.json') -Encoding utf8

$hostingReport = @(
    '# Hosting report','',
    '- Provider: GitHub Pages (public repository)',
    '- Cost: free; no credit card; no paid feature enabled',
    '- Uploaded: 10/10',
    '- Anonymous HTTPS verified: 10/10',
    '- Windows/localhost/tunnel dependency: none',
    '- Cleanup: disabled before publish; later requires publish success, final Media ID, and retention expiry',
    '- Formal publish API POST count: 0'
)
$hostingReport | Set-Content -LiteralPath (Join-Path $reportsFolder 'Hosting報告.md') -Encoding utf8
$accessLines = [Collections.Generic.List[string]]::new()
$accessLines.Add('# 10/10 Media Accessibility Report'); $accessLines.Add('')
$accessLines.Add("Verified at: $verifiedAt"); $accessLines.Add('')
$accessLines.Add('| Key | HTTPS | HTTP | Content-Type | Bytes/hash | Range | Result |')
$accessLines.Add('|---|---:|---:|---|---|---:|---|')
foreach ($item in $results) {
    $range = if ($null -eq $item.range_status) { 'n/a' } else { [string]$item.range_status }
    $accessLines.Add("| $($item.key) | yes | 200 | $($item.content_type) | match | $range | pass |")
}
$accessLines.Add(''); $accessLines.Add('All URLs are anonymous HTTPS paths with no token, cookie, local path, or tunnel dependency.')
$accessLines | Set-Content -LiteralPath (Join-Path $reportsFolder 'MediaAccessibility報告.md') -Encoding utf8

# 保存目前正式 manifest 快照；publisher 仍只讀 Bundle 根目錄的 canonical manifest。
$manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $manifestFolder 'campaign_manifest.json') -Encoding utf8

[pscustomobject][ordered]@{ provider='github_pages'; uploaded=10; verified=10; all_passed=$true; api_post_requests_sent=0 } | ConvertTo-Json
