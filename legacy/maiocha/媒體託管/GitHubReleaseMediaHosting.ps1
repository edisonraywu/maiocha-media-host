Set-StrictMode -Version Latest

function Get-GitHubHostingConfig {
    param([Parameter(Mandatory = $true)][string]$ConfigPath)
    $config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace([string]$config.owner_repo)) { throw 'Hosting config 缺少 owner_repo。' }
    if ([string]::IsNullOrWhiteSpace([string]$config.release_tag)) { throw 'Hosting config 缺少 release_tag。' }
    return $config
}

function Get-GitHubHostingToken {
    $token = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'Process')
    if ([string]::IsNullOrWhiteSpace($token)) { $token = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'User') }
    if ([string]::IsNullOrWhiteSpace($token)) { throw '找不到 GITHUB_TOKEN；請在本機安全 credential store 或 GitHub Actions Secrets 提供。' }
    return $token
}

function Get-GitHubHeaders {
    $token = Get-GitHubHostingToken
    return @{
        Authorization = "Bearer $token"
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
        'User-Agent' = 'maiocha-lab-instagram-media-adapter'
    }
}

function Get-GitHubRelease {
    param([Parameter(Mandatory = $true)]$Config)
    $headers = Get-GitHubHeaders
    $uri = "https://api.github.com/repos/$($Config.owner_repo)/releases/tags/$($Config.release_tag)"
    return Invoke-RestMethod -Method Get -Uri $uri -Headers $headers
}

function New-GitHubRelease {
    param([Parameter(Mandatory = $true)]$Config)
    throw 'UNSCOPED_RELEASE_HOSTING_DISABLED_USE_GITHUB_PAGES'
}

function Get-GitHubAssetName {
    param([Parameter(Mandatory = $true)][string]$CampaignId, [Parameter(Mandatory = $true)][string]$MediaKey, [Parameter(Mandatory = $true)][string]$Filename)
    $safeCampaign = $CampaignId -replace '[^A-Za-z0-9._-]', '_'
    $safeKey = $MediaKey -replace '[^A-Za-z0-9._-]', '_'
    $safeFilename = [IO.Path]::GetFileName($Filename) -replace '[^A-Za-z0-9._-]', '_'
    return "${safeCampaign}__${safeKey}__${safeFilename}"
}

function Get-GitHubContentType([string]$Path) {
    switch ([IO.Path]::GetExtension($Path).ToLowerInvariant()) {
        '.jpg' { return 'image/jpeg' }
        '.jpeg' { return 'image/jpeg' }
        '.mp4' { return 'video/mp4' }
        default { throw "不允許上傳的媒體格式：$Path" }
    }
}

function Upload-Media {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)][string]$CampaignId,
        [Parameter(Mandatory = $true)][string]$MediaKey,
        [Parameter(Mandatory = $true)][string]$LocalPath,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    throw 'UNSCOPED_RELEASE_HOSTING_DISABLED_USE_GITHUB_PAGES'
}

function Verify-PublicUrl {
    param([Parameter(Mandatory = $true)][string]$Url, [Parameter(Mandatory = $true)][string]$ExpectedContentType, [Parameter(Mandatory = $true)][string]$LocalPath)
    if ($Url -notmatch '^https://') { return $false }
    $client = [Net.Http.HttpClient]::new()
    try {
        $client.Timeout = [TimeSpan]::FromSeconds(30)
        $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, $Url)
        $response = $client.SendAsync($request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        try {
            if ([int]$response.StatusCode -ne 200) { return $false }
            if ($response.Content.Headers.ContentType.MediaType -ne $ExpectedContentType) { return $false }
            $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            try {
                $prefix = New-Object byte[] 32
                if ($stream.Read($prefix, 0, 32) -ne 32) { return $false }
            } finally { $stream.Dispose() }
            return $true
        } finally { $response.Dispose(); $request.Dispose() }
    } finally { $client.Dispose() }
}

function Remove-Media {
    param([Parameter(Mandatory = $true)]$Config, [Parameter(Mandatory = $true)][string]$AssetId)
    throw 'UNSCOPED_RELEASE_HOSTING_DISABLED_USE_GITHUB_PAGES'
}

function Cleanup-CampaignMedia {
    param([Parameter(Mandatory = $true)]$Config, [Parameter(Mandatory = $true)][string]$CampaignId, [switch]$Confirm)
    throw 'UNSCOPED_RELEASE_HOSTING_DISABLED_USE_GITHUB_PAGES'
}
