param(
    [Parameter(Mandatory = $true)][string]$BundleFolder,
    [Parameter(Mandatory = $true)][string]$StagingRepository
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'GitHubPagesMediaHosting.ps1')

$bundle = (Resolve-Path -LiteralPath $BundleFolder).Path
$staging = (Resolve-Path -LiteralPath $StagingRepository).Path
if (-not (Test-Path -LiteralPath (Join-Path $staging '.git') -PathType Container)) { throw 'StagingRepository 不是 Git repository。' }
$manifest = Get-Content -Raw -LiteralPath (Join-Path $bundle 'manifest.json') | ConvertFrom-Json
if ([string]$manifest.source_selection_mode -cne 'exact_paths_only' -or [bool]$manifest.wildcards_allowed) { throw 'Manifest 必須使用 exact_paths_only 且禁止 wildcard。' }

$scope = Get-ScopedCampaignConfig -BundleFolder $bundle
if ($staging -cne $scope.staging_repository) { throw 'HOSTING_STAGING_REPOSITORY_MISMATCH' }
# This older layout builder only supports its original Campaign. Other campaigns keep their own builders.
if ($scope.campaign_path -cne 'media/maiocha-launch-2026-09-16') { throw 'HOSTING_WRONG_CAMPAIGN_LAYOUT' }
$campaignSlug = $scope.campaign_path.Split('/')[-1]
$campaignRoot = Join-Path $staging "media\$campaignSlug"
$targets = @(
    @{ asset=$manifest.media.feed_carousel.children[0]; relative='feed/01.jpg'; content_type='image/jpeg' },
    @{ asset=$manifest.media.feed_carousel.children[1]; relative='feed/02.jpg'; content_type='image/jpeg' },
    @{ asset=$manifest.media.feed_carousel.children[2]; relative='feed/03-refined.jpg'; content_type='image/jpeg' },
    @{ asset=$manifest.media.feed_carousel.children[3]; relative='feed/04.jpg'; content_type='image/jpeg' },
    @{ asset=$manifest.media.feed_carousel.children[4]; relative='feed/05-refined.jpg'; content_type='image/jpeg' },
    @{ asset=$manifest.media.feed_carousel.children[5]; relative='feed/06.jpg'; content_type='image/jpeg' },
    @{ asset=$manifest.media.reel; relative='reel/reel-24s-7-scenes.mp4'; content_type='video/mp4' },
    @{ asset=$manifest.media.story_01; relative='story/01.jpg'; content_type='image/jpeg' },
    @{ asset=$manifest.media.story_02; relative='story/02-refined.jpg'; content_type='image/jpeg' },
    @{ asset=$manifest.media.story_03; relative='story/03.jpg'; content_type='image/jpeg' }
)
if ($targets.Count -ne 10) { throw '正式素材必須正好 10 份。' }

$inventory = [Collections.Generic.List[object]]::new()
foreach ($target in $targets) {
    $asset = $target.asset
    $source = [IO.Path]::GetFullPath([string]$asset.exact_path)
    $null = Assert-LocalPathBoundary $scope.source_root $source
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "正式素材不存在：$($asset.key)" }
    $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($hash -cne [string]$asset.sha256) { throw "SHA-256 不一致：$($asset.key)" }
    $upload = Upload-Media -Config $scope -ObjectKey ($scope.campaign_path + '/' + $target.relative) -LocalPath $source -ExpectedSha256 $hash
    $destination = Join-Path $staging $upload.hosted_object_key
    $inventory.Add([pscustomobject][ordered]@{
        key = [string]$asset.key
        relative_path = "media/$campaignSlug/$($target.relative)"
        sha256 = $hash
        file_size = (Get-Item -LiteralPath $destination).Length
        content_type = [string]$target.content_type
        approval_status = [string]$asset.approval_status
    })
}

$publicInventory = [pscustomobject][ordered]@{
    campaign_id = [string]$manifest.campaign_id
    source_selection_mode = 'exact_paths_only'
    wildcards_allowed = $false
    asset_count = 10
    assets = $inventory
}
$inventoryKey = Assert-ObjectKeyBoundary ($scope.campaign_path + '/manifest.json') $scope.hosting_namespace
$inventoryPath = Assert-LocalPathBoundary $campaignRoot (Join-Path $staging $inventoryKey)
$publicInventory | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $inventoryPath -Encoding utf8
if (-not (Test-Path -LiteralPath (Join-Path $staging '.nojekyll'))) { throw 'HOSTING_REPOSITORY_PROVISIONING_REQUIRED' }
Write-Output 'GitHub Pages staging prepared: 10 exact assets.'
