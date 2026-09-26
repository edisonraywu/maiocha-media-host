param(
    [string]$PreviewFolder,
    [switch]$DryRun,
    [switch]$VerifyPublicMedia
)

$ErrorActionPreference = 'Stop'
$toolFolder = Split-Path -Parent $MyInvocation.MyCommand.Path
$systemFolder = (Resolve-Path (Join-Path $toolFolder '..\..')).Path
$config = Get-Content -Raw -LiteralPath (Join-Path $toolFolder 'instagram_config.json') | ConvertFrom-Json
. (Join-Path $toolFolder 'Meta環境設定.ps1')
. (Join-Path $toolFolder '暫時公開測試圖片.ps1')
# The active legacy single test uses a temporary host bound to its own local image.
# Arbitrary configured URLs bypassed the hash/namespace model and are no longer accepted.
if (-not [string]::IsNullOrWhiteSpace([string]$config.test_media_url)) { throw 'UNSCOPED_TEST_MEDIA_URL_FORBIDDEN' }

Import-MetaEnvironment -Path (Join-Path $toolFolder '.env')
$token = Get-RequiredMetaSetting 'META_PAGE_ACCESS_TOKEN'
$pageId = Get-RequiredMetaSetting 'META_PAGE_ID'
$instagramId = Get-RequiredMetaSetting 'INSTAGRAM_BUSINESS_ACCOUNT_ID'
$expectedUsername = Get-RequiredMetaSetting 'INSTAGRAM_USERNAME'
$apiVersion = Get-RequiredMetaSetting 'META_GRAPH_API_VERSION'
if ($pageId -cne [string]$config.page_id -or $instagramId -cne [string]$config.instagram_user_id -or $expectedUsername -ine [string]$config.instagram_username) { throw 'LEGACY_TEST_ACCOUNT_CONFIG_MISMATCH' }

if ([string]::IsNullOrWhiteSpace($PreviewFolder)) {
    $PreviewFolder = Join-Path $toolFolder $config.test_preview_folder
}
$PreviewFolder = (Resolve-Path -LiteralPath $PreviewFolder).Path
$statusPath = Join-Path $PreviewFolder '確認狀態.txt'
$mediaPath = (Resolve-Path -LiteralPath (Join-Path $toolFolder $config.test_media_file)).Path
$captionPath = (Resolve-Path -LiteralPath (Join-Path $toolFolder $config.test_caption_file)).Path
$brandRoot = Get-LocalBrandRoot -Brand maiocha
$null = Assert-LocalPathBoundary $brandRoot $PreviewFolder
$null = Assert-LocalPathBoundary $brandRoot $mediaPath
$null = Assert-LocalPathBoundary $brandRoot $captionPath

if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) { throw '找不到人工確認狀態檔。' }
if (-not (Test-Path -LiteralPath $mediaPath -PathType Leaf)) { throw '找不到測試圖片。' }
if (-not (Test-Path -LiteralPath $captionPath -PathType Leaf)) { throw '找不到測試文案。' }

$approval = (Get-Content -Raw -LiteralPath $statusPath).Trim()
$caption = Get-Content -Raw -LiteralPath $captionPath
$expectedCaption = "買房喵查局｜系統測試 🐱`n`n自動發布功能測試中。"
if ($caption.TrimEnd() -cne $expectedCaption) { throw '測試文案與已核定文案不一致。' }

Add-Type -AssemblyName System.Drawing
$image = [System.Drawing.Image]::FromFile($mediaPath)
try {
    $isJpeg = ($image.RawFormat.Guid -eq [System.Drawing.Imaging.ImageFormat]::Jpeg.Guid)
    $imageWidth = $image.Width
    $imageHeight = $image.Height
} finally {
    $image.Dispose()
}
if (-not $isJpeg) { throw 'Instagram 單張測試圖片不是 JPEG。' }

$mediaHash = (Get-FileHash -LiteralPath $mediaPath -Algorithm SHA256).Hash
$captionBytes = [System.Text.Encoding]::UTF8.GetBytes($caption)
$captionHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($captionBytes))
$identity = 'TEST|' + $mediaHash + '|' + $captionHash
$logPath = Join-Path $systemFolder '10_發布紀錄\Instagram發布紀錄.csv'
$alreadyPublished = $false
$cloudflaredPath = Join-Path $env:LOCALAPPDATA 'CodexBrowserBridge\cloudflared.exe'
$temporaryHost = $null
if (Test-Path -LiteralPath $logPath) {
    $alreadyPublished = [bool](Import-Csv -LiteralPath $logPath | Where-Object {
        $_.'內容識別碼' -eq $identity -and $_.'結果' -eq '成功'
    })
}

try {
    $page = Invoke-MetaGraphGet -Path ("{0}?fields=id,name,instagram_business_account" -f $pageId) -AccessToken $token -ApiVersion $apiVersion
    $instagram = Invoke-MetaGraphGet -Path ("{0}?fields=id,username" -f $instagramId) -AccessToken $token -ApiVersion $apiVersion
    $publishingLimit = Invoke-MetaGraphGet -Path ("{0}/content_publishing_limit?fields=config,quota_usage" -f $instagramId) -AccessToken $token -ApiVersion $apiVersion

    if ([string]$page.id -ne $pageId -or
        [string]$page.instagram_business_account.id -ne $instagramId -or
        [string]$instagram.id -ne $instagramId -or
        [string]$instagram.username -ine $expectedUsername) {
        throw '粉專或 Instagram 帳號身分驗證失敗。'
    }

    if ($DryRun) {
        $publicMediaAccessible = $false
        $deliveryMode = 'missing'
        if (-not [string]::IsNullOrWhiteSpace($config.test_media_url)) {
            $deliveryMode = 'configured-https-url'
            if ($VerifyPublicMedia) {
                $head = Invoke-WebRequest -Method Head -Uri $config.test_media_url -TimeoutSec 15
                $publicMediaAccessible = ($head.StatusCode -eq 200)
            }
        } elseif (Test-Path -LiteralPath $cloudflaredPath -PathType Leaf) {
            $deliveryMode = 'temporary-cloudflare-tunnel-after-approval'
            if ($VerifyPublicMedia) {
                $temporaryHost = Start-TemporaryInstagramMediaHost -MediaPath $mediaPath -ToolFolder $toolFolder
                $httpClient = [System.Net.Http.HttpClient]::new()
                try {
                    $publicBytes = $httpClient.GetByteArrayAsync($temporaryHost.Url).GetAwaiter().GetResult()
                    $publicHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($publicBytes))
                    $publicMediaAccessible = ($publicHash -eq $mediaHash)
                } finally {
                    $httpClient.Dispose()
                }
            }
        }

        $recordFolder = Split-Path -Parent $logPath
        $recordProbe = Join-Path $recordFolder ('.instagram-record-check-' + [guid]::NewGuid().ToString('N'))
        $recordSystemHealthy = $false
        try {
            if (-not (Test-Path -LiteralPath $recordFolder -PathType Container)) { throw '發布紀錄資料夾不存在。' }
            if (Test-Path -LiteralPath $logPath) { $null = Import-Csv -LiteralPath $logPath }
            [System.IO.File]::WriteAllText($recordProbe, 'ok')
            $recordSystemHealthy = Test-Path -LiteralPath $recordProbe
        } finally {
            if (Test-Path -LiteralPath $recordProbe) { Remove-Item -LiteralPath $recordProbe -Force }
        }

        $result = [ordered]@{
            mode = 'dry-run'
            checked_at = (Get-Date).ToString('o')
            api_post_requests_sent = 0
            token_valid = $true
            page_id_matches = $true
            instagram_id_matches = $true
            instagram_username = [string]$instagram.username
            publishing_permission_readable = ($null -ne $publishingLimit)
            instagram_content_publish_available = ($null -ne $publishingLimit)
            local_media_exists = $true
            image_format = 'JPEG'
            image_width = $imageWidth
            image_height = $imageHeight
            caption_exists = $true
            preview_exists = $true
            current_approval_status = $approval
            real_publish_requires_exact_approval = '可以發布'
            already_published = $alreadyPublished
            publishing_record_system_healthy = $recordSystemHealthy
            public_media_delivery_ready = (
                -not [string]::IsNullOrWhiteSpace($config.test_media_url) -or
                (Test-Path -LiteralPath $cloudflaredPath -PathType Leaf)
            )
            public_media_delivery_mode = $deliveryMode
            public_media_verified_now = [bool]$VerifyPublicMedia
            public_media_accessible = $publicMediaAccessible
            all_preflight_passed = (
                -not $alreadyPublished -and
                $recordSystemHealthy -and
                ($null -ne $publishingLimit) -and
                (-not $VerifyPublicMedia -or $publicMediaAccessible)
            )
            safe_to_proceed_to_final_confirmation = (-not $alreadyPublished -and $recordSystemHealthy)
        }
        $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $toolFolder '模擬發布結果.json') -Encoding utf8
        $result | ConvertTo-Json -Depth 5
        return
    }

    if ($approval -cne '可以發布') { throw '這一批內容尚未取得「可以發布」確認，停止發布。' }
    if ($alreadyPublished) { throw '這篇測試內容已成功發布過，停止重複發布。' }
    $mediaUrl = [string]$config.test_media_url
    if ([string]::IsNullOrWhiteSpace($mediaUrl)) {
        $temporaryHost = Start-TemporaryInstagramMediaHost -MediaPath $mediaPath -ToolFolder $toolFolder
        $mediaUrl = $temporaryHost.Url
    }

    $base = '{0}/{1}' -f $config.graph_base_url.TrimEnd('/'), $apiVersion
    $container = Invoke-RestMethod -Method Post -Uri ($base + '/' + $instagramId + '/media') -Body @{
        image_url = $mediaUrl
        caption = $caption
        access_token = $token
    }
    if ([string]::IsNullOrWhiteSpace($container.id)) { throw 'Meta 沒有回傳內容容器編號。' }

    $containerReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $containerState = Invoke-MetaGraphGet -Path ("{0}?fields=status_code,status" -f $container.id) -AccessToken $token -ApiVersion $apiVersion
        if ($containerState.status_code -in @('FINISHED', 'PUBLISHED')) { $containerReady = $true; break }
        if ($containerState.status_code -in @('ERROR', 'EXPIRED')) { throw ('Meta 內容容器狀態異常：' + $containerState.status_code) }
        Start-Sleep -Seconds 2
    }
    if (-not $containerReady) { throw 'Meta 內容容器在時限內未準備完成，已停止，不會自動重試發布。' }

    $publishStartedAt = [DateTimeOffset]::UtcNow
    try {
        $published = Invoke-RestMethod -Method Post -Uri ($base + '/' + $instagramId + '/media_publish') -Body @{
            creation_id = $container.id
            access_token = $token
        }
    } catch {
        $published = $null
        try {
            $recent = Invoke-MetaGraphGet -Path ("{0}/media?fields=id,caption,permalink,timestamp&limit=25" -f $instagramId) -AccessToken $token -ApiVersion $apiVersion
            $possible = $recent.data | Where-Object {
                $_.caption -eq $caption -and [DateTimeOffset]::Parse($_.timestamp) -ge $publishStartedAt.AddMinutes(-2)
            } | Select-Object -First 1
            if ($possible) { $published = [pscustomobject]@{ id = $possible.id } }
        } catch {}
        if (-not $published) { throw '發布請求結果不確定，查詢媒體清單後仍無法確認成功。系統已停止，不會自動重試。' }
    }
    $detail = Invoke-MetaGraphGet -Path ("{0}?fields=id,permalink,timestamp" -f $published.id) -AccessToken $token -ApiVersion $apiVersion

    $record = [pscustomobject]@{
        '發布時間' = (Get-Date).ToString('o')
        '平台' = 'Instagram'
        '內容識別碼' = $identity
        '媒體編號' = $published.id
        '連結' = $detail.permalink
        '結果' = '成功'
    }
    if (Test-Path -LiteralPath $logPath) {
        $record | Export-Csv -LiteralPath $logPath -Append -NoTypeInformation -Encoding utf8
    } else {
        $record | Export-Csv -LiteralPath $logPath -NoTypeInformation -Encoding utf8
    }
    Set-Content -LiteralPath $statusPath -Value '已發布' -Encoding utf8
    Write-Host ('測試發布成功：{0}' -f $detail.permalink) -ForegroundColor Green
} finally {
    if ($temporaryHost) { Stop-TemporaryInstagramMediaHost -HostInfo $temporaryHost }
    $token = $null
}
