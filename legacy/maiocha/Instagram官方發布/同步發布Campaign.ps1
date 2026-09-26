param(
    [Parameter(Mandatory = $true)][string]$CampaignFolder,
    [switch]$DryRun,
    [switch]$VerifyPublicMedia
)

$ErrorActionPreference = 'Stop'
$toolFolder = Split-Path -Parent $MyInvocation.MyCommand.Path
$systemFolder = (Resolve-Path (Join-Path $toolFolder '..\..')).Path
. (Join-Path $toolFolder 'Meta環境設定.ps1')
. (Join-Path $toolFolder '暫時公開測試圖片.ps1')

function Get-Sha256Text([string]$Text) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
}

function Get-OptionalProperty($Object, [string]$Name) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
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

function Save-CampaignStatus($Status, [string]$Path) {
    $Status | Add-Member -NotePropertyName updated_at -NotePropertyValue (Get-Date).ToString('o') -Force
    $Status | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Add-CampaignRecord([hashtable]$Values) {
    $record = [pscustomobject][ordered]@{
        campaign_id = $Values.campaign_id
        media_key = $Values.media_key
        media_type = $Values.media_type
        content_identity = $Values.content_identity
        status = $Values.status
        container_id = $Values.container_id
        media_id = $Values.media_id
        permalink = $Values.permalink
        published_at = $Values.published_at
        error = $Values.error
    }
    if (Test-Path -LiteralPath $script:logPath) {
        $record | Export-Csv -LiteralPath $script:logPath -Append -NoTypeInformation -Encoding utf8
    } else {
        $record | Export-Csv -LiteralPath $script:logPath -NoTypeInformation -Encoding utf8
    }
}

function Get-PublishedCandidate([string]$MediaKey, [string]$Caption, [DateTimeOffset]$Since) {
    if ($MediaKey -eq 'story') {
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

function Publish-CampaignMedia([string]$MediaKey, $Spec, $Status) {
    $entry = $Status.$MediaKey
    if ($entry.status -eq 'success') { return }
    if ($entry.status -eq 'uncertain') {
        $candidate = Get-PublishedCandidate -MediaKey $MediaKey -Caption $entry.caption -Since ([DateTimeOffset]::Parse($entry.publish_attempted_at))
        if ($candidate) {
            $entry.status = 'success'; $entry.media_id = [string]$candidate.id; $entry.error = $null
            $entry | Add-Member -NotePropertyName permalink -NotePropertyValue ([string]$candidate.permalink) -Force
            Save-CampaignStatus $Status $script:statusPath
        }
        return
    }

    $mediaPath = Resolve-BundlePath $Spec.file
    $caption = ''
    $captionFile = Get-OptionalProperty $Spec 'caption_file'
    if ($captionFile) { $caption = Get-Content -Raw -LiteralPath (Resolve-BundlePath $captionFile) }
    $identity = '{0}|{1}|{2}|{3}' -f $script:campaign.campaign_id, $MediaKey, (Get-FileHash -LiteralPath $mediaPath -Algorithm SHA256).Hash, (Get-Sha256Text $caption)
    $hostInfo = $null
    $containerId = $null
    try {
        $hostInfo = Start-TemporaryInstagramMediaHost -MediaPath $mediaPath -ToolFolder $toolFolder
        $body = @{}
        switch ($MediaKey) {
            'feed' { $body.image_url = $hostInfo.Url; $body.caption = $caption }
            'reel' { $body.media_type = 'REELS'; $body.video_url = $hostInfo.Url; $body.caption = $caption; $body.share_to_feed = 'false' }
            'story' { $body.media_type = 'STORIES'; $body.image_url = $hostInfo.Url }
            default { throw "未知媒體項目：$MediaKey" }
        }
        $base = 'https://graph.facebook.com/{0}' -f $script:apiVersion
        $container = Invoke-RestMethod -Method Post -Uri ($base + '/' + $script:instagramId + '/media') -Headers @{ Authorization = "Bearer $script:token" } -Body $body
        $containerId = [string]$container.id
        if ([string]::IsNullOrWhiteSpace($containerId)) { throw 'Meta 沒有回傳內容容器編號。' }

        $ready = $false
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            $state = Invoke-MetaGraphGet -Path ("{0}?fields=status_code,status" -f $containerId) -AccessToken $script:token -ApiVersion $script:apiVersion
            if ($state.status_code -in @('FINISHED', 'PUBLISHED')) { $ready = $true; break }
            if ($state.status_code -in @('ERROR', 'EXPIRED')) { throw ('Meta 內容容器狀態異常：' + $state.status_code) }
            Start-Sleep -Seconds 3
        }
        if (-not $ready) { throw 'Meta 內容容器尚未準備完成。未呼叫發布，也不會自動重送。' }

        $started = [DateTimeOffset]::UtcNow
        $entry | Add-Member -NotePropertyName publish_attempted_at -NotePropertyValue $started.ToString('o') -Force
        $entry | Add-Member -NotePropertyName caption -NotePropertyValue $caption -Force
        Save-CampaignStatus $Status $script:statusPath
        try {
            $published = Invoke-RestMethod -Method Post -Uri ($base + '/' + $script:instagramId + '/media_publish') -Headers @{ Authorization = "Bearer $script:token" } -Body @{ creation_id = $containerId }
        } catch {
            $candidate = $null
            try { $candidate = Get-PublishedCandidate -MediaKey $MediaKey -Caption $caption -Since $started } catch {}
            if (-not $candidate) {
                $entry.status = 'uncertain'; $entry.error = '發布回覆不確定；已查詢媒體清單但尚未確認。系統不會自動重送。'
                $entry | Add-Member -NotePropertyName container_id -NotePropertyValue $containerId -Force
                Save-CampaignStatus $Status $script:statusPath
                Add-CampaignRecord @{ campaign_id=$script:campaign.campaign_id; media_key=$MediaKey; media_type=$Spec.media_type; content_identity=$identity; status='uncertain'; container_id=$containerId; media_id=''; permalink=''; published_at=''; error=$entry.error }
                return
            }
            $published = [pscustomobject]@{ id = $candidate.id }
        }

        $detail = Invoke-MetaGraphGet -Path ("{0}?fields=id,permalink,timestamp" -f $published.id) -AccessToken $script:token -ApiVersion $script:apiVersion
        $entry.status = 'success'; $entry.media_id = [string]$published.id; $entry.error = $null
        $entry | Add-Member -NotePropertyName container_id -NotePropertyValue $containerId -Force
        $entry | Add-Member -NotePropertyName permalink -NotePropertyValue ([string]$detail.permalink) -Force
        $entry | Add-Member -NotePropertyName published_at -NotePropertyValue ([string]$detail.timestamp) -Force
        Save-CampaignStatus $Status $script:statusPath
        Add-CampaignRecord @{ campaign_id=$script:campaign.campaign_id; media_key=$MediaKey; media_type=$Spec.media_type; content_identity=$identity; status='success'; container_id=$containerId; media_id=$entry.media_id; permalink=$entry.permalink; published_at=$entry.published_at; error='' }
    } catch {
        $entry.status = 'failed'; $entry.error = $_.Exception.Message
        $entry | Add-Member -NotePropertyName container_id -NotePropertyValue $containerId -Force
        Save-CampaignStatus $Status $script:statusPath
        Add-CampaignRecord @{ campaign_id=$script:campaign.campaign_id; media_key=$MediaKey; media_type=$Spec.media_type; content_identity=$identity; status='failed'; container_id=$containerId; media_id=''; permalink=''; published_at=''; error=$entry.error }
    } finally {
        if ($hostInfo) { Stop-TemporaryInstagramMediaHost -HostInfo $hostInfo }
    }
}

$CampaignFolder = (Resolve-Path -LiteralPath $CampaignFolder).Path
$null = Assert-LocalPathBoundary (Get-LocalBrandRoot -Brand maiocha) $CampaignFolder
function Resolve-BundlePath([string]$RelativePath) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $CampaignFolder $RelativePath))
    $null = Assert-LocalPathBoundary $CampaignFolder $candidate
    return (Resolve-Path -LiteralPath $candidate).Path
}

$campaignPath = Join-Path $CampaignFolder 'campaign.json'
$script:statusPath = Join-Path $CampaignFolder 'campaign_status.json'
$approvalPath = Join-Path $CampaignFolder '確認狀態.txt'
$script:logPath = Join-Path $systemFolder '10_發布紀錄\InstagramCampaign發布紀錄.csv'
$storySupportPath = Join-Path $toolFolder 'Story官方支援查核.json'
$videoValidationPath = Join-Path (Split-Path -Parent $toolFolder) '正式開張_video_validation.json'
$mediaServerValidationPath = Join-Path $toolFolder '媒體傳送本機驗證.json'
$script:campaign = Get-Content -Raw -LiteralPath $campaignPath | ConvertFrom-Json
$status = Get-Content -Raw -LiteralPath $script:statusPath | ConvertFrom-Json
$approval = (Get-Content -Raw -LiteralPath $approvalPath).Trim()

Import-MetaEnvironment -Path (Join-Path $toolFolder '.env')
$script:token = Get-RequiredMetaSetting 'META_PAGE_ACCESS_TOKEN'
$pageId = Get-RequiredMetaSetting 'META_PAGE_ID'
$script:instagramId = Get-RequiredMetaSetting 'INSTAGRAM_BUSINESS_ACCOUNT_ID'
$expectedUsername = Get-RequiredMetaSetting 'INSTAGRAM_USERNAME'
$script:apiVersion = Get-RequiredMetaSetting 'META_GRAPH_API_VERSION'

if ($pageId -ne '1364481190072089' -or $script:instagramId -ne '17841423624192593' -or $expectedUsername -ine 'maiocha.lab') { throw '本機環境設定與核定目標帳號不一致。' }
if ($script:campaign.target.facebook_page_id -ne $pageId -or $script:campaign.target.instagram_business_account_id -ne $script:instagramId -or $script:campaign.target.instagram_username -ine $expectedUsername) { throw 'Campaign 目標帳號與本機安全設定不一致。' }
if (($script:campaign.publication_order -join ',') -ne 'feed,reel,story') { throw 'Campaign 發布順序必須是 Feed → Reel → Story。' }
if ([bool]$script:campaign.media.reel.share_to_feed) { throw '本 Campaign 的 Reel 不得取代獨立 Feed。' }

$feedPath = Resolve-BundlePath $script:campaign.media.feed.file
$reelPath = Resolve-BundlePath $script:campaign.media.reel.file
$storyPath = Resolve-BundlePath $script:campaign.media.story.file
$feedCaption = Get-Content -Raw -LiteralPath (Resolve-BundlePath $script:campaign.media.feed.caption_file)
$reelCaption = Get-Content -Raw -LiteralPath (Resolve-BundlePath $script:campaign.media.reel.caption_file)
$storyText = Get-Content -Raw -LiteralPath (Resolve-BundlePath $script:campaign.media.story.text_file)
$feedFacts = Get-ImageFacts $feedPath
$storyFacts = Get-ImageFacts $storyPath
$videoFacts = Get-Content -Raw -LiteralPath $videoValidationPath | ConvertFrom-Json
$storySupport = Get-Content -Raw -LiteralPath $storySupportPath | ConvertFrom-Json
$mediaServerValidation = Get-Content -Raw -LiteralPath $mediaServerValidationPath | ConvertFrom-Json

$page = Invoke-MetaGraphGet -Path ("{0}?fields=id,name,instagram_business_account" -f $pageId) -AccessToken $script:token -ApiVersion $script:apiVersion
$instagram = Invoke-MetaGraphGet -Path ("{0}?fields=id,username" -f $script:instagramId) -AccessToken $script:token -ApiVersion $script:apiVersion
$publishingLimit = Invoke-MetaGraphGet -Path ("{0}/content_publishing_limit?fields=config,quota_usage" -f $script:instagramId) -AccessToken $script:token -ApiVersion $script:apiVersion

$identities = @{}
foreach ($key in @('feed','reel','story')) {
    $spec = $script:campaign.media.$key
    $path = Resolve-BundlePath $spec.file
    $captionFile = Get-OptionalProperty $spec 'caption_file'
    $textFile = Get-OptionalProperty $spec 'text_file'
    $text = if ($captionFile) { Get-Content -Raw -LiteralPath (Resolve-BundlePath $captionFile) } elseif ($textFile) { Get-Content -Raw -LiteralPath (Resolve-BundlePath $textFile) } else { '' }
    $identities[$key] = '{0}|{1}|{2}|{3}' -f $script:campaign.campaign_id, $key, (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash, (Get-Sha256Text $text)
}
$previous = @()
if (Test-Path -LiteralPath $script:logPath) { $previous = @(Import-Csv -LiteralPath $script:logPath) }
$duplicates = @($previous | Where-Object { $_.status -eq 'success' -and $identities.Values -contains $_.content_identity })

$recordFolder = Split-Path -Parent $script:logPath
$probe = Join-Path $recordFolder ('.campaign-record-check-' + [guid]::NewGuid().ToString('N'))
$recordHealthy = $false
try { [IO.File]::WriteAllText($probe, 'ok'); $recordHealthy = Test-Path -LiteralPath $probe } finally { if (Test-Path $probe) { Remove-Item -LiteralPath $probe -Force } }
$deliveryToolingReady = (
    (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'CodexBrowserBridge\cloudflared.exe') -PathType Leaf) -and
    (Test-Path -LiteralPath (Join-Path $toolFolder '本機媒體伺服器.ps1') -PathType Leaf) -and
    (Test-Path -LiteralPath (Join-Path $toolFolder '暫時公開測試圖片.ps1') -PathType Leaf)
)

$publicResults = [ordered]@{ feed=$false; reel=$false; story=$false }
if ($VerifyPublicMedia) {
    foreach ($key in @('feed','reel','story')) {
        $path = Resolve-BundlePath $script:campaign.media.$key.file
        $hostInfo = $null
        try {
            $hostInfo = Start-TemporaryInstagramMediaHost -MediaPath $path -ToolFolder $toolFolder
            $client = [Net.Http.HttpClient]::new()
            try {
                $bytes = $client.GetByteArrayAsync($hostInfo.Url).GetAwaiter().GetResult()
                $remoteHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
                $publicResults[$key] = ($remoteHash -eq (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash)
            } finally { $client.Dispose() }
        } finally { if ($hostInfo) { Stop-TemporaryInstagramMediaHost -HostInfo $hostInfo } }
    }
}

$checks = [ordered]@{
    token_valid = $true
    page_id_matches = ([string]$page.id -eq $pageId)
    page_links_expected_instagram_id = ([string]$page.instagram_business_account.id -eq $script:instagramId)
    instagram_id_matches = ([string]$instagram.id -eq $script:instagramId)
    instagram_username_matches = ([string]$instagram.username -ieq 'maiocha.lab')
    instagram_content_publish_available = ($null -ne $publishingLimit)
    feed_jpeg_1080x1350 = ($feedFacts.jpeg -and $feedFacts.width -eq 1080 -and $feedFacts.height -eq 1350)
    reel_mp4_1080x1920 = ($videoFacts.decodes_in_google_chrome -and $videoFacts.width -eq 1080 -and $videoFacts.height -eq 1920 -and (Test-ByteMarker $reelPath 'avc1'))
    reel_is_independent_motion_video = ($videoFacts.duration_seconds -ge 3 -and $videoFacts.previews.Count -ge 3)
    reel_share_to_feed_is_false = (-not [bool]$script:campaign.media.reel.share_to_feed)
    story_jpeg_1080x1920 = ($storyFacts.jpeg -and $storyFacts.width -eq 1080 -and $storyFacts.height -eq 1920)
    story_supported_by_official_facebook_login_api = ($storySupport.http_status -eq 200 -and $storySupport.stories_media_type_found -and $storySupport.ig_media_endpoint_found -and $storySupport.ig_media_publish_endpoint_found -and $storySupport.facebook_login_permissions_found)
    all_copy_present = (-not [string]::IsNullOrWhiteSpace($feedCaption) -and -not [string]::IsNullOrWhiteSpace($reelCaption) -and -not [string]::IsNullOrWhiteSpace($storyText))
    campaign_id_present = (-not [string]::IsNullOrWhiteSpace($script:campaign.campaign_id))
    publication_order_feed_reel_story = (($script:campaign.publication_order -join ',') -eq 'feed,reel,story')
    duplicate_prevention_clear = ($duplicates.Count -eq 0)
    publishing_record_system_healthy = $recordHealthy
    public_media_delivery_tooling_ready_after_approval = $deliveryToolingReady
    local_media_server_jpeg_mp4_and_range_verified = [bool]$mediaServerValidation.passed
    unpublished_assets_not_exposed_during_preflight = (-not [bool]$VerifyPublicMedia)
    public_feed_accessible = if ($VerifyPublicMedia) { [bool]$publicResults.feed } else { $null }
    public_reel_accessible = if ($VerifyPublicMedia) { [bool]$publicResults.reel } else { $null }
    public_story_accessible = if ($VerifyPublicMedia) { [bool]$publicResults.story } else { $null }
}
$required = @($checks.GetEnumerator() | Where-Object { $_.Value -is [bool] } | ForEach-Object { [bool]$_.Value })
$allPassed = -not ($required -contains $false)
$preflight = [ordered]@{
    mode = if ($DryRun) { 'dry-run' } else { 'publish' }
    checked_at = (Get-Date).ToString('o')
    campaign_id = [string]$script:campaign.campaign_id
    target = [ordered]@{ username=[string]$instagram.username; instagram_business_account_id=[string]$instagram.id; facebook_page_id=[string]$page.id }
    api_post_requests_sent = 0
    formal_publish_endpoints_called = $false
    current_approval_status = $approval
    required_approval_phrase = '可以同步發布'
    checks = $checks
    all_preflight_passed = $allPassed
}
$preflightPath = Join-Path $CampaignFolder 'preflight.json'
$preflight | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $preflightPath -Encoding utf8

if ($DryRun) {
    $preflight | ConvertTo-Json -Depth 8
    $script:token = $null
    return
}
if (-not $allPassed) { throw 'Campaign Preflight 未全部通過，停止發布。' }
if ($approval -cne '可以同步發布') { throw '尚未收到精確文字「可以同步發布」，停止發布。' }

foreach ($key in @('feed','reel','story')) {
    Publish-CampaignMedia -MediaKey $key -Spec $script:campaign.media.$key -Status $status
}
$script:token = $null
