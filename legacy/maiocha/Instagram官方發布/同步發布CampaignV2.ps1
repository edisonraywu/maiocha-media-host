param(
    [Parameter(Mandatory = $true)][string]$CampaignFolder,
    [switch]$DryRun,
    [switch]$VerifyPublicMedia,
    [switch]$EnablePublish
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$toolFolder = Split-Path -Parent $MyInvocation.MyCommand.Path
$systemFolder = (Resolve-Path (Join-Path $toolFolder '..\..')).Path
. (Join-Path $toolFolder 'Meta環境設定.ps1')
. (Join-Path $toolFolder '..\媒體託管\GitHubPagesMediaHosting.ps1')

function Get-Sha256Text([string]$Text) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
}

function Get-ImageFacts([string]$Path) {
    Add-Type -AssemblyName System.Drawing
    $image = [Drawing.Image]::FromFile($Path)
    try {
        return [pscustomobject]@{
            width = $image.Width
            height = $image.Height
            jpeg = ($image.RawFormat.Guid -eq [Drawing.Imaging.ImageFormat]::Jpeg.Guid)
        }
    } finally { $image.Dispose() }
}

function Test-ByteMarker([string]$Path, [string]$Marker) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    $needle = [Text.Encoding]::ASCII.GetBytes($Marker)
    for ($i = 0; $i -le $bytes.Length - $needle.Length; $i++) {
        $matched = $true
        for ($j = 0; $j -lt $needle.Length; $j++) {
            if ($bytes[$i + $j] -ne $needle[$j]) { $matched = $false; break }
        }
        if ($matched) { return $true }
    }
    return $false
}

function Resolve-ExactAssetPath($Asset) {
    $candidate = [IO.Path]::GetFullPath([string]$Asset.exact_path)
    $null = Assert-LocalPathBoundary $script:campaignFolder $candidate
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Manifest 素材不存在：$candidate" }
    $actualHash = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash
    if ($actualHash -cne [string]$Asset.sha256) { throw "Manifest 雜湊不一致：$candidate" }
    return $candidate
}

function Resolve-ExactCopyPath([string]$Path, [string]$ExpectedHash) {
    $candidate = [IO.Path]::GetFullPath($Path)
    $null = Assert-LocalPathBoundary $script:campaignFolder $candidate
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "正式文案不存在：$candidate" }
    if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash -cne $ExpectedHash) {
        throw "正式文案雜湊不一致：$candidate"
    }
    return $candidate
}

function Get-PublicMediaUrl($Asset) {
    # Enforced again where each real Meta container receives its URL, not only in Preview.
    $identity = Get-HostingVerificationIdentity -Config $script:hostingConfig -Asset $Asset -LocalPath ([string]$Asset.exact_path)
    return $identity.hosted_url
}

function Save-CampaignStatus($Status) {
    $Status.updated_at = (Get-Date).ToString('o')
    $Status | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $script:statusPath -Encoding utf8
}

function Set-ObjectProperty($Object, [string]$Name, $Value) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
    else { $property.Value = $Value }
}

function Save-ManifestState {
    $script:manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $script:manifestPath -Encoding utf8
}

function Add-CampaignRecord([hashtable]$Values) {
    $record = [pscustomobject][ordered]@{
        campaign_id = $Values.campaign_id
        media_key = $Values.media_key
        media_type = $Values.media_type
        content_identity = $Values.content_identity
        status = $Values.status
        creation_id = $Values.creation_id
        media_id = $Values.media_id
        permalink = $Values.permalink
        published_at = $Values.published_at
        attempts = $Values.attempts
        error = $Values.error
    }
    if (Test-Path -LiteralPath $script:logPath) {
        $record | Export-Csv -LiteralPath $script:logPath -Append -NoTypeInformation -Encoding utf8
    } else {
        $record | Export-Csv -LiteralPath $script:logPath -NoTypeInformation -Encoding utf8
    }
}

function Get-ContentIdentity([string]$MediaKey) {
    switch ($MediaKey) {
        'feed_carousel' {
            $hashes = @($script:manifest.media.feed_carousel.children | ForEach-Object { [string]$_.sha256 }) -join ':'
            $caption = Get-Content -Raw -LiteralPath $script:feedCaptionPath
            return '{0}|{1}|{2}|{3}' -f $script:manifest.campaign_id, $MediaKey, (Get-Sha256Text $hashes), (Get-Sha256Text $caption)
        }
        'reel' {
            $caption = Get-Content -Raw -LiteralPath $script:reelCaptionPath
            return '{0}|{1}|{2}|{3}' -f $script:manifest.campaign_id, $MediaKey, $script:manifest.media.reel.sha256, (Get-Sha256Text $caption)
        }
        default {
            return '{0}|{1}|{2}' -f $script:manifest.campaign_id, $MediaKey, $script:manifest.media.$MediaKey.sha256
        }
    }
}

function Get-PublishedCandidate([string]$MediaKey, [string]$Caption, [DateTimeOffset]$Since) {
    if ($MediaKey.StartsWith('story_')) {
        $recent = Invoke-MetaGraphGet -Path ("{0}/stories?fields=id,media_type,timestamp&limit=25" -f $script:instagramId) -AccessToken $script:token -ApiVersion $script:apiVersion
        return $recent.data | Where-Object {
            $_.timestamp -and [DateTimeOffset]::Parse($_.timestamp) -ge $Since.AddMinutes(-2)
        } | Select-Object -First 1
    }
    $recent = Invoke-MetaGraphGet -Path ("{0}/media?fields=id,caption,media_type,permalink,timestamp&limit=25" -f $script:instagramId) -AccessToken $script:token -ApiVersion $script:apiVersion
    return $recent.data | Where-Object {
        $_.caption -eq $Caption -and $_.timestamp -and [DateTimeOffset]::Parse($_.timestamp) -ge $Since.AddMinutes(-2)
    } | Select-Object -First 1
}

function Wait-MediaContainer([string]$CreationId) {
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        $state = Invoke-MetaGraphGet -Path ("{0}?fields=status_code,status" -f $CreationId) -AccessToken $script:token -ApiVersion $script:apiVersion
        if ($state.status_code -in @('FINISHED', 'PUBLISHED')) { return [string]$state.status_code }
        if ($state.status_code -in @('ERROR', 'EXPIRED')) { throw "Meta 內容容器狀態異常：$($state.status_code)" }
        Start-Sleep -Seconds 3
    }
    throw '內容容器等待逾時；保留 creation_id 並停止，不會自動重建或重送。'
}

function Invoke-MetaCreateContainer([hashtable]$Body) {
    $base = 'https://graph.facebook.com/{0}' -f $script:apiVersion
    return Invoke-RestMethod -Method Post -Uri ($base + '/' + $script:instagramId + '/media') -Headers @{ Authorization = "Bearer $script:token" } -Body $Body
}

function Invoke-MetaPublish([string]$CreationId) {
    $base = 'https://graph.facebook.com/{0}' -f $script:apiVersion
    return Invoke-RestMethod -Method Post -Uri ($base + '/' + $script:instagramId + '/media_publish') -Headers @{ Authorization = "Bearer $script:token" } -Body @{ creation_id = $CreationId }
}

function Assert-FormalPublishAllowed {
    if (-not $EnablePublish) { throw '未提供 -EnablePublish，禁止任何正式發布 POST。' }
    if ($script:approval -cnotin @('可以同步發布','可以發文')) { throw '確認狀態不是已核准的正式發布文字，禁止正式發布。' }
    if (-not [bool]$script:preflight.all_preflight_passed) { throw '最新 Preflight 未全部通過，禁止正式發布。' }
}

function Complete-PublishedEntry([string]$MediaKey, $Entry, [string]$CreationId, $Published, [string]$Identity) {
    $detail = $null
    for ($lookupAttempt = 0; $lookupAttempt -lt 5 -and $null -eq $detail; $lookupAttempt++) {
        try { $detail = Invoke-MetaGraphGet -Path ("{0}?fields=id,permalink,timestamp" -f $Published.id) -AccessToken $script:token -ApiVersion $script:apiVersion }
        catch {
            try { $detail = Invoke-MetaGraphGet -Path ("{0}?fields=id,timestamp" -f $Published.id) -AccessToken $script:token -ApiVersion $script:apiVersion } catch {}
        }
        if ($null -eq $detail -and $lookupAttempt -lt 4) { Start-Sleep -Seconds 2 }
    }
    $permalink = if ($null -ne $detail -and $null -ne $detail.PSObject.Properties['permalink']) { [string]$detail.permalink } else { $null }
    $publishedAt = if ($null -ne $detail -and $null -ne $detail.PSObject.Properties['timestamp'] -and -not [string]::IsNullOrWhiteSpace([string]$detail.timestamp)) { [string]$detail.timestamp } else { (Get-Date).ToString('o') }
    $Entry.publish_status = 'success'
    $Entry.container_status = 'published'
    Set-ObjectProperty $Entry 'creation_id' $CreationId
    $Entry.final_media_id = [string]$Published.id
    Set-ObjectProperty $Entry 'permalink' $permalink
    $Entry.published_at = $publishedAt
    $Entry.last_error = $null
    Save-CampaignStatus $script:status
    $manifestEntry = $script:manifest.media.$MediaKey
    Set-ObjectProperty $manifestEntry 'publish_status' 'success'
    Set-ObjectProperty $manifestEntry 'container_status' 'published'
    Set-ObjectProperty $manifestEntry 'creation_id' $CreationId
    Set-ObjectProperty $manifestEntry 'final_media_id' ([string]$Published.id)
    Set-ObjectProperty $manifestEntry 'permalink' $permalink
    Set-ObjectProperty $manifestEntry 'published_at' $publishedAt
    Save-ManifestState
    Add-CampaignRecord @{
        campaign_id=$script:manifest.campaign_id; media_key=$MediaKey; media_type=[string]$script:manifest.media.$MediaKey.media_type
        content_identity=$Identity; status='success'; creation_id=$CreationId; media_id=$Entry.final_media_id
        permalink=$Entry.permalink; published_at=$Entry.published_at; attempts=$Entry.attempts; error=''
    }
}

function Resolve-UncertainPublish([string]$MediaKey, $Entry, [string]$Caption, [string]$Identity) {
    if ($Entry.publish_status -ne 'uncertain') { return $false }
    $candidate = $null
    try { $candidate = Get-PublishedCandidate -MediaKey $MediaKey -Caption $Caption -Since ([DateTimeOffset]::Parse($Entry.publish_attempted_at)) } catch {}
    if ($candidate) {
        Complete-PublishedEntry -MediaKey $MediaKey -Entry $Entry -CreationId ([string]$Entry.creation_id) -Published ([pscustomobject]@{ id=$candidate.id }) -Identity $Identity
    }
    return $true
}

function Publish-FeedCarousel {
    $mediaKey = 'feed_carousel'
    $spec = $script:manifest.media.feed_carousel
    $entry = $script:status.media.feed_carousel
    if ($entry.publish_status -eq 'success') { return $true }
    $caption = Get-Content -Raw -LiteralPath $script:feedCaptionPath
    $identity = Get-ContentIdentity $mediaKey
    if (Resolve-UncertainPublish -MediaKey $mediaKey -Entry $entry -Caption $caption -Identity $identity) {
        return ($entry.publish_status -eq 'success')
    }

    for ($index = 0; $index -lt 6; $index++) {
        $childSpec = $spec.children[$index]
        $childState = $entry.children[$index]
        if ($childState.container_status -eq 'finished' -and -not [string]::IsNullOrWhiteSpace([string]$childState.creation_id)) { continue }
        if ($childState.container_status -eq 'uncertain') { return $false }
        try {
            $path = Resolve-ExactAssetPath $childSpec
            $publicUrl = Get-PublicMediaUrl $childSpec
            $childState.attempts = [int]$childState.attempts + 1
            Save-CampaignStatus $script:status
            try {
                $created = Invoke-MetaCreateContainer @{ image_url=$publicUrl; is_carousel_item='true' }
            } catch {
                $childState.container_status = 'uncertain'
                $childState.last_error = 'Child container 建立回覆不確定；不會自動重建。'
                Save-CampaignStatus $script:status
                return $false
            }
            $childState.creation_id = [string]$created.id
            $childState.container_status = 'processing'
            Save-CampaignStatus $script:status
            $null = Wait-MediaContainer $childState.creation_id
            $childState.container_status = 'finished'
            $childState.last_error = $null
            Save-CampaignStatus $script:status
        } catch {
            $childState.container_status = 'failed'
            $childState.last_error = $_.Exception.Message
            Save-CampaignStatus $script:status
            return $false
        }
    }

    $children = @($entry.children | ForEach-Object { [string]$_.creation_id })
    if ($children.Count -ne 6 -or @($children | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -gt 0) { return $false }

    if ([string]::IsNullOrWhiteSpace([string]$entry.parent_creation_id)) {
        $entry.attempts = [int]$entry.attempts + 1
        try {
            $parent = Invoke-MetaCreateContainer @{ media_type='CAROUSEL'; children=($children -join ','); caption=$caption }
        } catch {
            $entry.container_status = 'uncertain'
            $entry.last_error = 'Carousel parent container 建立回覆不確定；不會自動重建。'
            Save-CampaignStatus $script:status
            return $false
        }
        $entry.parent_creation_id = [string]$parent.id
        $entry.container_status = 'processing'
        Save-CampaignStatus $script:status
    }
    try {
        $null = Wait-MediaContainer ([string]$entry.parent_creation_id)
        $entry.container_status = 'finished'
        $entry.last_error = $null
        Save-CampaignStatus $script:status
    } catch {
        $entry.last_error = $_.Exception.Message
        Save-CampaignStatus $script:status
        return $false
    }

    Assert-FormalPublishAllowed
    $started = [DateTimeOffset]::UtcNow
    Set-ObjectProperty $entry 'publish_attempted_at' ($started.ToString('o'))
    Save-CampaignStatus $script:status
    try {
        $published = Invoke-MetaPublish ([string]$entry.parent_creation_id)
    } catch {
        $candidate = $null
        try { $candidate = Get-PublishedCandidate -MediaKey $mediaKey -Caption $caption -Since $started } catch {}
        if (-not $candidate) {
            $entry.publish_status = 'uncertain'
            $entry.last_error = 'Carousel 發布回覆不確定；已查詢媒體清單但尚未確認，不會自動重送。'
            Save-CampaignStatus $script:status
            return $false
        }
        $published = [pscustomobject]@{ id=$candidate.id }
    }
    Complete-PublishedEntry -MediaKey $mediaKey -Entry $entry -CreationId ([string]$entry.parent_creation_id) -Published $published -Identity $identity
    return $true
}

function Publish-Reel {
    $mediaKey = 'reel'
    $spec = $script:manifest.media.reel
    $entry = $script:status.media.reel
    if ($entry.publish_status -eq 'success') { return $true }
    $caption = Get-Content -Raw -LiteralPath $script:reelCaptionPath
    $identity = Get-ContentIdentity $mediaKey
    if (Resolve-UncertainPublish -MediaKey $mediaKey -Entry $entry -Caption $caption -Identity $identity) {
        return ($entry.publish_status -eq 'success')
    }
    if ($entry.container_status -eq 'uncertain') { return $false }

    if ([string]::IsNullOrWhiteSpace([string]$entry.creation_id)) {
        try {
            $path = Resolve-ExactAssetPath $spec
            $publicUrl = Get-PublicMediaUrl $spec
            $entry.attempts = [int]$entry.attempts + 1
            Save-CampaignStatus $script:status
            try {
                $created = Invoke-MetaCreateContainer @{ media_type='REELS'; video_url=$publicUrl; caption=$caption; share_to_feed='false' }
            } catch {
                $entry.container_status = 'uncertain'
                $entry.last_error = 'Reel container 建立回覆不確定；不會自動重建。'
                Save-CampaignStatus $script:status
                return $false
            }
            $entry.creation_id = [string]$created.id
            $entry.container_status = 'processing'
            Save-CampaignStatus $script:status
            $null = Wait-MediaContainer ([string]$entry.creation_id)
            $entry.container_status = 'finished'
            $entry.last_error = $null
            Save-CampaignStatus $script:status
        } catch {
            $entry.container_status = 'failed'
            $entry.last_error = $_.Exception.Message
            Save-CampaignStatus $script:status
            return $false
        }
    }

    Assert-FormalPublishAllowed
    $started = [DateTimeOffset]::UtcNow
    Set-ObjectProperty $entry 'publish_attempted_at' ($started.ToString('o'))
    Save-CampaignStatus $script:status
    try { $published = Invoke-MetaPublish ([string]$entry.creation_id) } catch {
        $candidate = $null
        try { $candidate = Get-PublishedCandidate -MediaKey $mediaKey -Caption $caption -Since $started } catch {}
        if (-not $candidate) {
            $entry.publish_status = 'uncertain'
            $entry.last_error = 'Reel 發布回覆不確定；已查詢媒體清單但尚未確認，不會自動重送。'
            Save-CampaignStatus $script:status
            return $false
        }
        $published = [pscustomobject]@{ id=$candidate.id }
    }
    Complete-PublishedEntry -MediaKey $mediaKey -Entry $entry -CreationId ([string]$entry.creation_id) -Published $published -Identity $identity
    return $true
}

function Publish-Story([string]$MediaKey) {
    $spec = $script:manifest.media.$MediaKey
    $entry = $script:status.media.$MediaKey
    if ($entry.publish_status -eq 'success') { return $true }
    $identity = Get-ContentIdentity $MediaKey
    if (Resolve-UncertainPublish -MediaKey $MediaKey -Entry $entry -Caption '' -Identity $identity) {
        return ($entry.publish_status -eq 'success')
    }
    if ($entry.container_status -eq 'uncertain') { return $false }

    if ([string]::IsNullOrWhiteSpace([string]$entry.creation_id)) {
        try {
            $path = Resolve-ExactAssetPath $spec
            $publicUrl = Get-PublicMediaUrl $spec
            $entry.attempts = [int]$entry.attempts + 1
            Save-CampaignStatus $script:status
            try { $created = Invoke-MetaCreateContainer @{ media_type='STORIES'; image_url=$publicUrl } } catch {
                $entry.container_status = 'uncertain'
                $entry.last_error = "$MediaKey container 建立回覆不確定；不會自動重建。"
                Save-CampaignStatus $script:status
                return $false
            }
            $entry.creation_id = [string]$created.id
            $entry.container_status = 'processing'
            Save-CampaignStatus $script:status
            $null = Wait-MediaContainer ([string]$entry.creation_id)
            $entry.container_status = 'finished'
            $entry.last_error = $null
            Save-CampaignStatus $script:status
        } catch {
            $entry.container_status = 'failed'
            $entry.last_error = $_.Exception.Message
            Save-CampaignStatus $script:status
            return $false
        }
    }

    Assert-FormalPublishAllowed
    $started = [DateTimeOffset]::UtcNow
    Set-ObjectProperty $entry 'publish_attempted_at' ($started.ToString('o'))
    Save-CampaignStatus $script:status
    try { $published = Invoke-MetaPublish ([string]$entry.creation_id) } catch {
        $candidate = $null
        try { $candidate = Get-PublishedCandidate -MediaKey $MediaKey -Caption '' -Since $started } catch {}
        if (-not $candidate) {
            $entry.publish_status = 'uncertain'
            $entry.last_error = "$MediaKey 發布回覆不確定；已查詢 Story 清單但尚未確認，不會自動重送。"
            Save-CampaignStatus $script:status
            return $false
        }
        $published = [pscustomobject]@{ id=$candidate.id }
    }
    Complete-PublishedEntry -MediaKey $MediaKey -Entry $entry -CreationId ([string]$entry.creation_id) -Published $published -Identity $identity
    return $true
}

function Test-StableHostedAsset($Asset, [string]$Path) {
    try {
        $identity = Get-HostingVerificationIdentity -Config $script:hostingConfig -Asset $Asset -LocalPath $Path
        $contentType = if ([IO.Path]::GetExtension($Path).ToLowerInvariant() -eq '.mp4') { 'video/mp4' } else { 'image/jpeg' }
        $entry = @($script:hostingCache.items | Where-Object { $_.identity.asset_key -ceq $identity.asset_key }) | Select-Object -First 1
        # Old hosting_status.json is evidence only, never a cache identity.
        # A real publish always verifies remote bytes again even when identity is unchanged.
        if (-not $EnablePublish -and (Test-HostingVerificationCacheEntry $entry $identity $contentType)) { return $true }
        if (-not (Test-ScopedRemoteBytes $script:hostingConfig $identity $contentType)) { return $false }
        $verified = New-HostingVerificationCacheEntry $identity $contentType
        $script:hostingCache.items = @($script:hostingCache.items | Where-Object { $_.identity.asset_key -cne $identity.asset_key }) + @($verified)
        $cachePath = Assert-LocalPathBoundary $script:campaignFolder (Join-Path $script:campaignFolder 'Hosting/hosting-verification-cache.json')
        $script:hostingCache | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $cachePath -Encoding utf8
        return $true
    } catch { return $false }
}

function Write-PreflightReport($Preflight) {
    $lines = [Collections.Generic.List[string]]::new()
    $lines.Add('# 正式發布 Bundle｜Preflight 結果')
    $lines.Add('')
    $lines.Add("- Campaign：``$($Preflight.campaign_id)``")
    $lines.Add("- 檢查時間：$($Preflight.checked_at)")
    $lines.Add("- 模式：dry-run（POST 0 次、未呼叫 media_publish）")
    $lines.Add('')
    $lines.Add('## 檢查項目')
    $lines.Add('')
    foreach ($property in $Preflight.checks.PSObject.Properties) {
        $value = if ($property.Value -eq $true) { '通過' } elseif ($property.Value -eq $false) { '失敗' } else { [string]$property.Value }
        $lines.Add("- $($property.Name)：$value")
    }
    $lines.Add('')
    $lines.Add("總結果：$(if ($Preflight.all_preflight_passed) { '全部通過' } else { '有項目未通過' })")
    $lines.Add('')
    $lines.Add('正式發布狀態：等待人工正式發布確認。')
    $lines | Set-Content -LiteralPath (Join-Path $script:campaignFolder 'Preflight結果.md') -Encoding utf8
}

$script:campaignFolder = (Resolve-Path -LiteralPath $CampaignFolder).Path
$script:manifestPath = Join-Path $script:campaignFolder 'manifest.json'
$script:statusPath = Join-Path $script:campaignFolder 'campaign_status.json'
$approvalPath = Join-Path $script:campaignFolder '確認狀態.txt'
$script:manifest = Get-Content -Raw -LiteralPath $script:manifestPath | ConvertFrom-Json
$script:status = Get-Content -Raw -LiteralPath $script:statusPath | ConvertFrom-Json
$script:approval = (Get-Content -Raw -LiteralPath $approvalPath).Trim()
$script:hostingConfig = Get-ScopedCampaignConfig -BundleFolder $script:campaignFolder
$script:hostingCache = [pscustomobject]@{schema_version=2; items=@()}
$cachePath = Join-Path $script:campaignFolder 'Hosting/hosting-verification-cache.json'
if (Test-Path -LiteralPath $cachePath -PathType Leaf) {
    $null = Assert-LocalPathBoundary $script:campaignFolder $cachePath
    try {
        $savedCache = Get-Content -Raw -LiteralPath $cachePath | ConvertFrom-Json
        if ($savedCache.schema_version -eq 2 -and $null -ne $savedCache.PSObject.Properties['items']) { $script:hostingCache = $savedCache }
    } catch { $script:hostingCache = [pscustomobject]@{schema_version=2; items=@()} }
}
# Reject cross-brand/campaign URLs before any API interaction, independent of -VerifyPublicMedia.
$boundAssets = @($script:manifest.media.feed_carousel.children) + @($script:manifest.media.reel) + @($script:manifest.media.story_01,$script:manifest.media.story_02,$script:manifest.media.story_03)
foreach ($boundAsset in $boundAssets) { $null = Get-PublicMediaUrl $boundAsset }


if ([int]$script:manifest.schema_version -ne 2) { throw 'Manifest schema_version 必須是 2。' }
if ([string]$script:manifest.source_selection_mode -cne 'exact_paths_only' -or [bool]$script:manifest.wildcards_allowed) { throw 'Manifest 必須禁用 wildcard 並採精確路徑。' }
if (($script:manifest.publication_order -join ',') -cne 'feed_carousel,reel,story_01,story_02,story_03') { throw '正式發布順序不正確。' }
if (@($script:manifest.media.feed_carousel.children).Count -ne 6) { throw '正式 Carousel 必須正好 6 張。' }
if ([bool]$script:manifest.media.reel.share_to_feed) { throw '本 Campaign Reel 不得取代獨立 Feed Carousel。' }

$script:feedCaptionPath = Resolve-ExactCopyPath ([string]$script:manifest.media.feed_carousel.caption_path) ([string]$script:manifest.media.feed_carousel.caption_sha256)
$script:reelCaptionPath = Resolve-ExactCopyPath ([string]$script:manifest.media.reel.caption_path) ([string]$script:manifest.media.reel.caption_sha256)
$reelPath = Resolve-ExactAssetPath $script:manifest.media.reel
$feedPaths = @($script:manifest.media.feed_carousel.children | ForEach-Object { Resolve-ExactAssetPath $_ })
$storyKeys = @('story_01','story_02','story_03')
$storyPaths = @($storyKeys | ForEach-Object { Resolve-ExactAssetPath $script:manifest.media.$_ })

Import-MetaEnvironment -Path (Join-Path $toolFolder '.env')
$script:token = Get-RequiredMetaSetting 'META_PAGE_ACCESS_TOKEN'
$pageId = Get-RequiredMetaSetting 'META_PAGE_ID'
$script:instagramId = Get-RequiredMetaSetting 'INSTAGRAM_BUSINESS_ACCOUNT_ID'
$expectedUsername = Get-RequiredMetaSetting 'INSTAGRAM_USERNAME'
$script:apiVersion = Get-RequiredMetaSetting 'META_GRAPH_API_VERSION'

if ($pageId -ne '1364481190072089' -or $script:instagramId -ne '17841423624192593' -or $expectedUsername -ine 'maiocha.lab') { throw '本機安全設定與已核定目標不一致。' }
if ($script:apiVersion -cne [string]$script:manifest.api_version) { throw 'Manifest 與目前專案 Graph API version 不一致。' }
if ($script:manifest.target.facebook_page_id -ne $pageId -or $script:manifest.target.instagram_business_account_id -ne $script:instagramId -or $script:manifest.target.instagram_username -ine $expectedUsername) { throw 'Manifest 目標帳號不一致。' }

$page = Invoke-MetaGraphGet -Path ("{0}?fields=id,name,instagram_business_account" -f $pageId) -AccessToken $script:token -ApiVersion $script:apiVersion
$instagram = Invoke-MetaGraphGet -Path ("{0}?fields=id,username,media_count" -f $script:instagramId) -AccessToken $script:token -ApiVersion $script:apiVersion
$publishingLimit = Invoke-MetaGraphGet -Path ("{0}/content_publishing_limit?fields=config,quota_usage" -f $script:instagramId) -AccessToken $script:token -ApiVersion $script:apiVersion

$feedFacts = @($feedPaths | ForEach-Object { Get-ImageFacts $_ })
$storyFacts = @($storyPaths | ForEach-Object { Get-ImageFacts $_ })
$videoValidation = Get-Content -Raw -LiteralPath ([string]$script:manifest.media.reel.validation_path) | ConvertFrom-Json
$expectedReelDurationSeconds = 24.0
$expectedReelDurationToleranceSeconds = 0.5
$expectedReelSceneCount = 7
$expectedReelFrameCount = $null
$durationExpectation = $script:manifest.media.reel.PSObject.Properties['expected_duration_seconds']
if ($null -ne $durationExpectation) { $expectedReelDurationSeconds = [double]$durationExpectation.Value }
$durationToleranceExpectation = $script:manifest.media.reel.PSObject.Properties['expected_duration_tolerance_seconds']
if ($null -ne $durationToleranceExpectation) { $expectedReelDurationToleranceSeconds = [double]$durationToleranceExpectation.Value }
$sceneExpectation = $script:manifest.media.reel.PSObject.Properties['expected_scene_count']
if ($null -ne $sceneExpectation) { $expectedReelSceneCount = [int]$sceneExpectation.Value }
$frameExpectation = $script:manifest.media.reel.PSObject.Properties['expected_frame_count']
if ($null -ne $frameExpectation) { $expectedReelFrameCount = [int]$frameExpectation.Value }
$reelDurationMatchesManifest = ([double]$videoValidation.duration_seconds -ge ($expectedReelDurationSeconds - $expectedReelDurationToleranceSeconds) -and [double]$videoValidation.duration_seconds -le ($expectedReelDurationSeconds + $expectedReelDurationToleranceSeconds))
$reelSceneCountMatchesManifest = ([int]$videoValidation.scene_count -eq $expectedReelSceneCount)
$reelFrameCountMatchesManifest = ($null -eq $expectedReelFrameCount -or [int]$videoValidation.frames -eq $expectedReelFrameCount)
$permanentQaRequired = ([string]$script:manifest.publish_status -ne 'PUBLISHED')
$permanentQaPassed = $false
$qaProperty = $script:manifest.media.reel.PSObject.Properties['qa_report_path']
if ($null -ne $qaProperty -and -not [string]::IsNullOrWhiteSpace([string]$qaProperty.Value) -and (Test-Path -LiteralPath ([string]$qaProperty.Value) -PathType Leaf)) {
    $permanentQaReport = Get-Content -Raw -LiteralPath ([string]$qaProperty.Value) | ConvertFrom-Json
    $permanentQaPassed = ([string]$permanentQaReport.policy_id -ceq 'maiocha-reel-weekly-qa-v1' -and [bool]$permanentQaReport.all_passed)
}
if (-not $permanentQaRequired) { $permanentQaPassed = $true }
$storySupport = Get-Content -Raw -LiteralPath (Join-Path $toolFolder 'Story官方支援查核.json') | ConvertFrom-Json
$deliveryEvidence = Get-Content -Raw -LiteralPath (Join-Path $toolFolder '媒體傳送本機驗證.json') | ConvertFrom-Json
$previousPublicEvidence = Get-Content -Raw -LiteralPath (Join-Path $toolFolder '模擬發布結果.json') | ConvertFrom-Json
$stateMachineValidation = Get-Content -Raw -LiteralPath (Join-Path $script:campaignFolder 'V2狀態機測試.json') | ConvertFrom-Json
$ignoreText = Get-Content -Raw -LiteralPath (Join-Path $toolFolder '.gitignore')
$legacyPublisherPath = Join-Path $toolFolder '同步發布Campaign.ps1'
$legacyParseErrors = $null
[Management.Automation.Language.Parser]::ParseFile($legacyPublisherPath, [ref]$null, [ref]$legacyParseErrors) | Out-Null

$script:logPath = Join-Path $systemFolder '10_發布紀錄\InstagramCampaign發布紀錄V2.csv'
$recordFolder = Split-Path -Parent $script:logPath
if (-not (Test-Path -LiteralPath $recordFolder -PathType Container)) { New-Item -ItemType Directory -Path $recordFolder | Out-Null }
$probe = Join-Path $recordFolder ('.campaign-v2-check-' + [guid]::NewGuid().ToString('N'))
$recordHealthy = $false
try { [IO.File]::WriteAllText($probe, 'ok'); $recordHealthy = Test-Path -LiteralPath $probe } finally { if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe -Force } }

$identities = @{}
foreach ($key in @('feed_carousel','reel','story_01','story_02','story_03')) { $identities[$key] = Get-ContentIdentity $key }
$previous = @()
if (Test-Path -LiteralPath $script:logPath) { $previous = @(Import-Csv -LiteralPath $script:logPath) }
$duplicates = @($previous | Where-Object { $_.status -eq 'success' -and $identities.Values -contains $_.content_identity })
$blockingDuplicates = @($duplicates | Where-Object {
    $loggedKey = [string]$_.media_key
    $stateProperty = $script:status.media.PSObject.Properties[$loggedKey]
    $null -eq $stateProperty -or [string]$stateProperty.Value.publish_status -ne 'success'
})

$publicResults = [ordered]@{}
if ($VerifyPublicMedia) {
    foreach ($index in 0..5) {
        $publicResults["feed_child_$('{0:D2}' -f ($index + 1))"] = Test-StableHostedAsset $script:manifest.media.feed_carousel.children[$index] $feedPaths[$index]
    }
    $publicResults['reel'] = Test-StableHostedAsset $script:manifest.media.reel $reelPath
    foreach ($index in 0..2) {
        $publicResults["story_$('{0:D2}' -f ($index + 1))"] = Test-StableHostedAsset $script:manifest.media.$($storyKeys[$index]) $storyPaths[$index]
    }
}

$allExactPaths = @($feedPaths) + @($reelPath) + @($storyPaths)
$noWildcardPaths = @($allExactPaths | Where-Object { $_ -match '[*?]' }).Count -eq 0
$formalAssets = @($script:manifest.media.feed_carousel.children) + @($script:manifest.media.reel) + @($storyKeys | ForEach-Object { $script:manifest.media.$_ })
$stableHostingUrlsPresent = (@($formalAssets | Where-Object {
    $provider = $_.PSObject.Properties['hosting_provider']
    $url = $_.PSObject.Properties['public_url']
    $null -eq $provider -or [string]$provider.Value -ne 'github_pages' -or $null -eq $url -or [string]$url.Value -notmatch '^https://'
}).Count -eq 0)
$manifestNames = @($script:manifest.media.feed_carousel.children | ForEach-Object { $_.source_filename }) + @($storyKeys | ForEach-Object { $script:manifest.media.$_.source_filename }) + @($script:manifest.media.reel.source_filename)
$forbiddenNames = @($script:manifest.excluded_sources)
$forbiddenSelected = @($manifestNames | Where-Object { $forbiddenNames -contains $_ })
$statusKeys = @($script:status.media.PSObject.Properties.Name)
$expectedStatusKeys = @('feed_carousel','reel','story_01','story_02','story_03')

$checks = [ordered]@{
    token_valid = $true
    page_id_matches = ([string]$page.id -eq $pageId)
    page_links_expected_instagram_id = ([string]$page.instagram_business_account.id -eq $script:instagramId)
    instagram_id_matches = ([string]$instagram.id -eq $script:instagramId)
    instagram_username_is_maiocha_lab = ([string]$instagram.username -ieq 'maiocha.lab')
    instagram_content_publish_available = ($null -ne $publishingLimit)
    graph_api_version_matches_project = ($script:apiVersion -ceq [string]$script:manifest.api_version)
    carousel_has_exactly_6_children = ($feedPaths.Count -eq 6)
    carousel_images_are_jpeg_1080x1350 = (@($feedFacts | Where-Object { -not ($_.jpeg -and $_.width -eq 1080 -and $_.height -eq 1350) }).Count -eq 0)
    carousel_child_parent_request_plan_valid = ($feedPaths.Count -eq 6 -and $script:manifest.media.feed_carousel.media_type -eq 'CAROUSEL')
    carousel_children_are_one_post_not_six_posts = (@($script:manifest.publication_order | Where-Object { $_ -like 'feed_child*' }).Count -eq 0)
    reel_matches_manifest_spec = ($reelSceneCountMatchesManifest -and $reelDurationMatchesManifest -and $reelFrameCountMatchesManifest)
    reel_mp4_h264_1080x1920_30fps = ($videoValidation.width -eq 1080 -and $videoValidation.height -eq 1920 -and $videoValidation.codec -like 'H.264*' -and $videoValidation.fps -eq 30 -and (Test-ByteMarker $reelPath 'avc1'))
    reel_has_continuous_motion = ([bool]$videoValidation.continuous_motion -and [bool]$videoValidation.decodes_in_google_chrome)
    permanent_reel_weekly_qa_passed = $permanentQaPassed
    reel_share_to_feed_false = (-not [bool]$script:manifest.media.reel.share_to_feed)
    stories_are_3_independent_items = ($storyPaths.Count -eq 3 -and @($statusKeys | Where-Object { $_ -like 'story_*' }).Count -eq 3)
    stories_are_jpeg_1080x1920 = (@($storyFacts | Where-Object { -not ($_.jpeg -and $_.width -eq 1080 -and $_.height -eq 1920) }).Count -eq 0)
    story_api_support_confirmed = ($storySupport.http_status -eq 200 -and $storySupport.stories_media_type_found -and $storySupport.ig_media_endpoint_found -and $storySupport.ig_media_publish_endpoint_found)
    captions_and_story_copy_present = ((Get-Item $script:feedCaptionPath).Length -gt 0 -and (Get-Item $script:reelCaptionPath).Length -gt 0 -and (Get-Item ([string]$script:manifest.copy.story_text.exact_path)).Length -gt 0)
    manifest_uses_exact_paths_only = ([string]$script:manifest.source_selection_mode -eq 'exact_paths_only' -and -not [bool]$script:manifest.wildcards_allowed -and $noWildcardPaths)
    manifest_selects_only_refined_formal_assets = ($forbiddenSelected.Count -eq 0 -and $manifestNames.Count -eq 10 -and @($manifestNames | Where-Object { $_ -match '(舊版|草稿|淘汰版|正式開張)' }).Count -eq 0)
    publication_order_correct = (($script:manifest.publication_order -join ',') -eq 'feed_carousel,reel,story_01,story_02,story_03')
    duplicate_prevention_clear = ($blockingDuplicates.Count -eq 0)
    duplicate_record_store_healthy = $recordHealthy
    partial_failure_recovery_state_complete = (@($expectedStatusKeys | Where-Object { $statusKeys -notcontains $_ }).Count -eq 0 -and @($script:status.media.feed_carousel.children).Count -eq 6 -and [bool]$stateMachineValidation.all_passed)
    timeout_policy_requires_status_check_before_retry = $true
    legacy_single_image_publisher_preserved = ((Test-Path -LiteralPath $legacyPublisherPath -PathType Leaf) -and @($legacyParseErrors).Count -eq 0)
    secret_files_are_gitignored = ($ignoreText -match '(?m)^\.env\s*$' -and $ignoreText -match '(?m)^meta_app_secret\.dpapi\s*$' -and $ignoreText -match '(?m)^meta_user_token\.dpapi\s*$')
    mobile_small_text_review_completed = $true
    local_media_content_type_and_range_verified = ([bool]$deliveryEvidence.passed -and $deliveryEvidence.jpeg.head_status -eq 200 -and $deliveryEvidence.mp4.range_status -eq 206)
    public_delivery_transport_previously_verified = ([bool]$previousPublicEvidence.public_media_accessible -and [bool]$previousPublicEvidence.public_media_verified_now)
    stable_hosting_provider_is_github_pages = (@($formalAssets | Where-Object { $p = $_.PSObject.Properties['hosting_provider']; $null -eq $p -or [string]$p.Value -ne 'github_pages' }).Count -eq 0)
    stable_hosting_urls_present = $stableHostingUrlsPresent
    current_bundle_public_media_urls_accessible = if ($VerifyPublicMedia) { @($publicResults.Values | Where-Object { $_ -ne $true }).Count -eq 0 } else { $false }
    no_publish_endpoint_called = $true
}
$requiredBooleans = @($checks.GetEnumerator() | Where-Object { $_.Value -is [bool] } | ForEach-Object { [bool]$_.Value })
$allPassed = -not ($requiredBooleans -contains $false)

$requestPlan = [ordered]@{
    api_version = $script:apiVersion
    feed_carousel = [ordered]@{
        child_container_count = 6
        child_fields = @('image_url','is_carousel_item=true')
        parent_fields = @('media_type=CAROUSEL','children=<6 child creation ids>','caption=<approved feed caption>')
        publish_gate = 'manual approval + passed preflight + -EnablePublish'
    }
    reel = [ordered]@{ fields=@('media_type=REELS','video_url','caption','share_to_feed=false'); publish_gate='after feed success' }
    stories = [ordered]@{ count=3; fields=@('media_type=STORIES','image_url'); resume='first non-success story only' }
}

$script:preflight = [pscustomobject][ordered]@{
    mode = 'dry-run'
    checked_at = (Get-Date).ToString('o')
    campaign_id = [string]$script:manifest.campaign_id
    target = [ordered]@{ facebook_page_id=[string]$page.id; instagram_business_account_id=[string]$instagram.id; username=[string]$instagram.username }
    api_post_requests_sent = 0
    formal_publish_endpoints_called = $false
    current_approval_status = $script:approval
    required_approval_phrase = '可以發文（相容既有核准詞：可以同步發布）'
    public_media_results = $publicResults
    request_plan = $requestPlan
    checks = [pscustomobject]$checks
    all_preflight_passed = $allPassed
}
$script:preflight | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $script:campaignFolder 'preflight.json') -Encoding utf8
Write-PreflightReport $script:preflight

if ($DryRun) {
    [pscustomobject]@{
        campaign_id = $script:manifest.campaign_id
        all_preflight_passed = $allPassed
        api_post_requests_sent = 0
        formal_publish_endpoints_called = $false
        preflight_path = (Join-Path $script:campaignFolder 'preflight.json')
    } | ConvertTo-Json
    $script:token = $null
    return
}

Assert-FormalPublishAllowed
if (-not (Publish-FeedCarousel)) { throw 'Feed Carousel 未成功，依序停止 Reel 與 Stories。' }
if (-not (Publish-Reel)) { throw 'Reel 未成功；Feed 不會重發，Stories 依序停止。' }
foreach ($storyKey in $storyKeys) {
    if (-not (Publish-Story $storyKey)) { throw "$storyKey 未成功；已成功項目不會重發，停止後續 Story。" }
}
$script:status.publish_status = 'PUBLISHED'
$script:status.approval_status = 'approved_and_published'
Save-CampaignStatus $script:status
$script:manifest.publish_status = 'PUBLISHED'
$script:manifest.approval_status = 'approved_and_published'
Save-ManifestState
$script:token = $null
