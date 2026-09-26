# Shared, config-driven Hosting boundaries. No account credentials or brand captions.
Set-StrictMode -Version Latest
$script:HostingSafetyRepository = Split-Path -Parent $PSScriptRoot

function Get-HostingScopePolicy {
    $path = Join-Path $script:HostingSafetyRepository 'config/hosting-scopes.json'
    $policy = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
    $baobao = (ConvertTo-CanonicalObjectKey $policy.brands.baobao.namespace).Split('/')
    foreach ($registered in $policy.brands.maiocha.campaigns.PSObject.Properties) {
        $maiocha = (ConvertTo-CanonicalObjectKey $registered.Value.namespace).Split('/')
        $overlap = $true
        for ($i=0; $i -lt [Math]::Min($maiocha.Count,$baobao.Count); $i++) {
            if ($maiocha[$i] -cne $baobao[$i]) { $overlap=$false; break }
        }
        if ($overlap) { throw 'HOSTING_POLICY_CROSS_BRAND_OVERLAP' }
    }
    return $policy
}

function Get-LocalBrandRoot {
    param([Parameter(Mandatory)][ValidateSet('maiocha','baobao')][string]$Brand,
          [string]$Workspace = (Split-Path -Parent $script:HostingSafetyRepository))
    $policy = Get-HostingScopePolicy
    return Assert-LocalPathBoundary $Workspace (Join-Path $Workspace $policy.brands.$Brand.content_root)
}

function ConvertTo-CanonicalObjectKey {
    param([Parameter(Mandatory)][string]$Key)
    if ([string]::IsNullOrWhiteSpace($Key) -or $Key -match '[\x00-\x1f\x7f?#:]') { throw 'HOSTING_INVALID_OBJECT_KEY' }
    $decoded = $Key
    for ($i = 0; $i -lt 5; $i++) {
        if ($decoded -notmatch '%') { break }
        if ($decoded -match '%(?![0-9a-fA-F]{2})') { throw 'HOSTING_INVALID_ENCODING' }
        $next = [Uri]::UnescapeDataString($decoded)
        if ($next -ceq $decoded) { throw 'HOSTING_INVALID_ENCODING' }
        $decoded = $next
    }
    if ($decoded -match '[%\x00-\x1f\x7f?#:]') { throw 'HOSTING_INVALID_OBJECT_KEY' }
    $segments = [Collections.Generic.List[string]]::new()
    foreach ($part in $decoded.Replace('\', '/').Split('/')) {
        if ($part -eq '' -or $part -eq '.') { continue }
        if ($part -eq '..') {
            if ($segments.Count -eq 0) { throw 'HOSTING_PATH_TRAVERSAL' }
            $segments.RemoveAt($segments.Count - 1)
            continue
        }
        # Avoid Windows aliases (ADS, trailing dots/spaces, device names) and wildcard semantics.
        if ($part -match '[<>"|*]' -or $part.TrimEnd(' ', '.') -cne $part -or
            $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { throw 'HOSTING_INVALID_PATH_SEGMENT' }
        $segments.Add($part)
    }
    if ($segments.Count -eq 0) { throw 'HOSTING_EMPTY_OBJECT_KEY' }
    return $segments -join '/'
}

function Assert-ObjectKeyBoundary {
    param([Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][string]$Namespace, [switch]$AllowRoot)
    $canonical = ConvertTo-CanonicalObjectKey $Key
    $allowed = ConvertTo-CanonicalObjectKey $Namespace
    $parts = $canonical.Split('/')
    $scope = $allowed.Split('/')
    if ($parts.Count -lt $scope.Count -or (-not $AllowRoot -and $parts.Count -eq $scope.Count)) { throw 'HOSTING_NAMESPACE_MISMATCH' }
    for ($i = 0; $i -lt $scope.Count; $i++) {
        if ($parts[$i] -cne $scope[$i]) { throw 'HOSTING_NAMESPACE_MISMATCH' }
    }
    return $canonical
}

function Assert-LocalPathBoundary {
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Path, [switch]$AllowRoot)
    $rootPath = [IO.Path]::GetFullPath($Root)
    $fullPath = [IO.Path]::GetFullPath($Path)
    $relative = [IO.Path]::GetRelativePath($rootPath, $fullPath)
    if ([IO.Path]::IsPathRooted($relative) -or @($relative.Replace('\','/').Split('/') | Where-Object { $_ -eq '..' }).Count -gt 0 -or
        (-not $AllowRoot -and $relative -eq '.')) { throw 'HOSTING_LOCAL_PATH_OUTSIDE_SCOPE' }
    # Reject links/junctions along the entire chain, including an otherwise valid root.
    $cursor = $fullPath
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $node = Get-Item -Force -LiteralPath $cursor
            if (($node.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'HOSTING_REPARSE_POINT_FORBIDDEN' }
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $fullPath
}

function New-HostingScope {
    param(
        [Parameter(Mandatory)][ValidateSet('maiocha','baobao')][string]$Brand,
        [Parameter(Mandatory)][string]$CampaignId,
        [string]$Workspace = (Split-Path -Parent $script:HostingSafetyRepository)
    )
    $Brand = $Brand.ToLowerInvariant()
    $policy = Get-HostingScopePolicy
    $workspacePath = [IO.Path]::GetFullPath($Workspace)
    $brandPolicy = $policy.brands.$Brand
    if ($Brand -eq 'maiocha') {
        $registered = $brandPolicy.campaigns.PSObject.Properties[$CampaignId]
        if ($null -eq $registered) { throw 'HOSTING_CAMPAIGN_NOT_REGISTERED' }
        $namespace = [string]$registered.Value.namespace
        $relativeSource = [string]$registered.Value.source_root
    } else {
        if ($CampaignId -cnotmatch [string]$brandPolicy.content_id_pattern) { throw 'HOSTING_CONTENT_ID_BRAND_MISMATCH' }
        $namespace = [string]$brandPolicy.namespace + '/' + $CampaignId
        $relativeSource = [string]$brandPolicy.source_root + '/' + $CampaignId
    }
    $source = Assert-LocalPathBoundary (Join-Path $workspacePath $brandPolicy.content_root) (Join-Path $workspacePath $relativeSource)
    $staging = Assert-LocalPathBoundary $workspacePath (Join-Path $workspacePath 'maiocha-media-host-staging')
    return [pscustomobject][ordered]@{
        brand = $Brand; campaign_id = $CampaignId; campaign_path = (ConvertTo-CanonicalObjectKey $namespace)
        source_root = $source; workspace = $workspacePath; staging_repository = $staging
        owner_repo = [string]$policy.hosting.repository; pages_base_url = [string]$policy.hosting.base_url
        hosting_namespace = (ConvertTo-CanonicalObjectKey $namespace)
    }
}

function Assert-HostingScope {
    param([Parameter(Mandatory)]$Config)
    foreach ($name in @('brand','campaign_id','campaign_path','source_root','workspace','staging_repository','owner_repo','pages_base_url','hosting_namespace')) {
        if ($null -eq $Config.PSObject.Properties[$name] -or [string]::IsNullOrWhiteSpace([string]$Config.$name)) { throw 'HOSTING_EXPLICIT_CONTEXT_REQUIRED' }
    }
    $expected = New-HostingScope -Brand $Config.brand -CampaignId $Config.campaign_id -Workspace $Config.workspace
    foreach ($name in @('campaign_path','source_root','staging_repository','owner_repo','pages_base_url','hosting_namespace')) {
        if ([string]$Config.$name -cne [string]$expected.$name) { throw 'HOSTING_CONTEXT_POLICY_MISMATCH' }
    }
    return $expected
}

function Get-ScopedCampaignConfig {
    param([Parameter(Mandatory)][string]$BundleFolder, [string]$Workspace = (Split-Path -Parent $script:HostingSafetyRepository))
    $bundle = [IO.Path]::GetFullPath($BundleFolder)
    $manifest = Get-Content -Raw -LiteralPath (Join-Path $bundle 'manifest.json') | ConvertFrom-Json
    $scope = New-HostingScope -Brand maiocha -CampaignId $manifest.campaign_id -Workspace $Workspace
    if ($bundle -cne $scope.source_root) { throw 'HOSTING_CAMPAIGN_SOURCE_MISMATCH' }
    $hostingPath = Join-Path $bundle 'Hosting/hosting_config.json'
    $saved = Get-Content -Raw -LiteralPath $hostingPath | ConvertFrom-Json
    if ([string]$saved.campaign_path -cne $scope.campaign_path -or [string]$saved.pages_base_url -cne $scope.pages_base_url -or
        [string]$saved.owner_repo -cne $scope.owner_repo -or [string]$saved.provider -cne 'github_pages') { throw 'HOSTING_CAMPAIGN_CONFIG_MISMATCH' }
    $property = $saved.PSObject.Properties['staging_repository']
    if ($null -ne $property -and [string]$property.Value -and [IO.Path]::GetFullPath([string]$property.Value) -cne $scope.staging_repository) { throw 'HOSTING_STAGING_REPOSITORY_MISMATCH' }
    return $scope
}

function Get-ScopedHostedUrl {
    param([Parameter(Mandatory)]$Config, [Parameter(Mandatory)][string]$ObjectKey, [string]$Url)
    $scope = Assert-HostingScope $Config
    $key = Assert-ObjectKeyBoundary -Key $ObjectKey -Namespace $scope.hosting_namespace
    $escaped = ($key.Split('/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/'
    $expected = $scope.pages_base_url.TrimEnd('/') + '/' + $escaped
    if ($Url) {
        # Parse the original path before System.Uri can discard dot segments.
        if ($Url -notmatch '^https://([^/?#]+)(/[^?#]*)$') { throw 'HOSTING_INVALID_PUBLIC_URL' }
        $authority = $Matches[1]; $rawPath = $Matches[2]
        $baseUri = [Uri]$scope.pages_base_url
        if ($authority -ine $baseUri.Authority -or $authority -match '@') { throw 'HOSTING_PUBLIC_ORIGIN_MISMATCH' }
        $path = ConvertTo-CanonicalObjectKey $rawPath
        $expectedPath = ConvertTo-CanonicalObjectKey ($baseUri.AbsolutePath + '/' + $key)
        if ($path -cne $expectedPath) { throw 'HOSTING_URL_OBJECT_IDENTITY_MISMATCH' }
    }
    return $expected
}

function Get-HostingVerificationIdentity {
    param([Parameter(Mandatory)]$Config, [Parameter(Mandatory)]$Asset, [Parameter(Mandatory)][string]$LocalPath)
    $scope = Assert-HostingScope $Config
    $source = Assert-LocalPathBoundary $scope.source_root $LocalPath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'HOSTING_SOURCE_MISSING' }
    foreach ($name in @('exact_path','sha256','public_url','hosted_object_key','key')) {
        if ($null -eq $Asset.PSObject.Properties[$name] -or [string]::IsNullOrWhiteSpace([string]$Asset.$name)) { throw 'HOSTING_ASSET_IDENTITY_MISSING' }
    }
    if ([IO.Path]::GetFullPath([string]$Asset.exact_path) -cne $source) { throw 'HOSTING_SOURCE_IDENTITY_MISMATCH' }
    $sha = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha -cne ([string]$Asset.sha256).ToLowerInvariant()) { throw 'HOSTING_SOURCE_HASH_MISMATCH' }
    $key = Assert-ObjectKeyBoundary $Asset.hosted_object_key $scope.hosting_namespace
    $normalized = Get-ScopedHostedUrl $scope $key $Asset.public_url
    return [pscustomobject][ordered]@{
        brand = $scope.brand; campaign_id = $scope.campaign_id; asset_key = [string]$Asset.key
        local_source_root = $scope.source_root; local_source_path = $source; local_asset_sha256 = $sha
        hosted_url = [string]$Asset.public_url; normalized_url = $normalized
        remote_object_key = $key; remote_object_key_original = [string]$Asset.hosted_object_key
        hosting_namespace = $scope.hosting_namespace
    }
}

function Test-HostingVerificationCacheEntry {
    param($Entry, [Parameter(Mandatory)]$Identity, [Parameter(Mandatory)][string]$ContentType)
    if ($null -eq $Entry) { return $false }
    foreach ($name in @('schema_version','identity','passed','content_type')) {
        if ($null -eq $Entry.PSObject.Properties[$name]) { return $false }
    }
    if ($Entry.schema_version -ne 2 -or $Entry.passed -ne $true -or $Entry.content_type -cne $ContentType) { return $false }
    if (@($Entry.identity.PSObject.Properties).Count -ne @($Identity.PSObject.Properties).Count) { return $false }
    foreach ($property in $Identity.PSObject.Properties) {
        $cached = $Entry.identity.PSObject.Properties[$property.Name]
        if ($null -eq $cached -or [string]$cached.Value -cne [string]$property.Value) { return $false }
    }
    return $true
}

function New-HostingVerificationCacheEntry {
    param([Parameter(Mandatory)]$Identity, [Parameter(Mandatory)][string]$ContentType)
    return [pscustomobject]@{schema_version=2; identity=$Identity; content_type=$ContentType; passed=$true; verified_at=[DateTimeOffset]::UtcNow.ToString('o')}
}

function Test-ScopedRemoteBytes {
    param([Parameter(Mandatory)]$Config, [Parameter(Mandatory)]$Identity, [Parameter(Mandatory)][string]$ContentType)
    $null = Get-ScopedHostedUrl $Config $Identity.remote_object_key $Identity.hosted_url
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [Net.Http.HttpClient]::new($handler)
    try {
        $client.Timeout = [TimeSpan]::FromSeconds(60)
        $response = $client.GetAsync($Identity.hosted_url, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        try {
            if ([int]$response.StatusCode -ne 200 -or [string]$response.Content.Headers.ContentType.MediaType -cne $ContentType) { return $false }
            $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $hasher = [Security.Cryptography.SHA256]::Create()
            try { $hash = [Convert]::ToHexString($hasher.ComputeHash($stream)).ToLowerInvariant() }
            finally { $stream.Dispose(); $hasher.Dispose() }
            return $hash -ceq $Identity.local_asset_sha256
        } finally { $response.Dispose() }
    } catch { return $false }
    finally { $client.Dispose(); $handler.Dispose() }
}
