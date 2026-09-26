param([string]$OutputRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $OutputRoot) { $OutputRoot = Join-Path $repo ('.local/isolation-tests-' + [guid]::NewGuid().ToString('N')) }
$fixture = Join-Path $OutputRoot 'workspace'
$fixtureRepo = Join-Path $fixture 'maiocha-media-host-staging'
New-Item -ItemType Directory -Force -Path (Join-Path $fixtureRepo 'safety'),(Join-Path $fixtureRepo 'config') | Out-Null
Copy-Item -LiteralPath (Join-Path $repo 'safety/HostingSafety.ps1') -Destination (Join-Path $fixtureRepo 'safety/HostingSafety.ps1')
Copy-Item -LiteralPath (Join-Path $repo 'config/hosting-scopes.json') -Destination (Join-Path $fixtureRepo 'config/hosting-scopes.json')
$deploy = Get-Content -Raw -LiteralPath (Join-Path $repo 'legacy/install-manifest.json') | ConvertFrom-Json
foreach ($file in $deploy.files) {
    $dest = Join-Path $fixture $file.destination
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo $file.source) -Destination $dest
}
$legacyTools = Join-Path $fixture '買房喵查局內容系統/11_系統工具'
. (Join-Path $legacyTools '媒體託管/GitHubPagesMediaHosting.ps1')
$cases = [Collections.Generic.List[object]]::new()
function Assert-True([bool]$Value, [string]$Message = 'ASSERTION_FAILED') { if (-not $Value) { throw $Message } }
function Assert-Reject([scriptblock]$Action, [string]$Code = 'HOSTING_') {
    $rejected = $false
    try { & $Action | Out-Null } catch { if ($_.Exception.Message -notmatch $Code) { throw }; $rejected = $true }
    Assert-True $rejected 'EXPECTED_REJECTION_BUT_ACCEPTED'
}
function Case([string]$Name, [scriptblock]$Body) {
    try { & $Body; $cases.Add([pscustomobject]@{name=$Name;result='PASS'}) }
    catch { $cases.Add([pscustomobject]@{name=$Name;result='FAIL';error=$_.Exception.Message}); Write-Host "FAIL $Name : $($_.Exception.Message)" }
}
$maiocha = New-HostingScope -Brand maiocha -CampaignId 'maiocha-first-post-needs-three-2026-09-21' -Workspace $fixture
$baobao = New-HostingScope -Brand baobao -CampaignId 'baobao-fixture-BB001' -Workspace $fixture
foreach ($scope in @($maiocha,$baobao)) {
    New-Item -ItemType Directory -Force -Path $scope.source_root,(Join-Path $scope.source_root 'Hosting'),(Join-Path $scope.staging_repository $scope.hosting_namespace) | Out-Null
    [IO.File]::WriteAllText((Join-Path $scope.source_root 'fixture.jpg'), 'TEST FIXTURE ONLY ' + $scope.brand)
}
function Fixture-Asset($Scope, [string]$Name='01.jpg') {
    $path = Join-Path $Scope.source_root 'fixture.jpg'
    $key = $Scope.hosting_namespace + '/feed/' + $Name
    return [pscustomobject]@{key='feed_child_01';exact_path=$path;sha256=(Get-FileHash -LiteralPath $path).Hash;hosted_object_key=$key;public_url=(Get-ScopedHostedUrl $Scope $key);accessibility_status='verified'}
}
$asset = Fixture-Asset $maiocha
$identity = Get-HostingVerificationIdentity $maiocha $asset $asset.exact_path
$entry = New-HostingVerificationCacheEntry $identity 'image/jpeg'

Case 'cache: unchanged complete identity hits' { Assert-True (Test-HostingVerificationCacheEntry $entry $identity 'image/jpeg') }
Case 'cache: old hash-only evidence misses' {
    Assert-True (-not (Test-HostingVerificationCacheEntry ([pscustomobject]@{passed=$true;sha256=$asset.sha256;content_type='image/jpeg'}) $identity 'image/jpeg'))
}
foreach ($field in @('brand','campaign_id','local_source_path','local_source_root','local_asset_sha256','hosted_url','normalized_url','remote_object_key','remote_object_key_original','hosting_namespace','asset_key')) {
    Case "cache: changed $field invalidates" {
        $changed = $identity | ConvertTo-Json | ConvertFrom-Json
        $changed.$field = 'different-identity'
        Assert-True (-not (Test-HostingVerificationCacheEntry $entry $changed 'image/jpeg'))
    }
}
Case 'cache: maiocha source/hash with baobao hosted URL fails' {
    $wrong = $asset | ConvertTo-Json | ConvertFrom-Json
    $wrong.public_url = Get-ScopedHostedUrl $baobao ($baobao.hosting_namespace + '/feed/01.jpg')
    Assert-Reject { Get-HostingVerificationIdentity $maiocha $wrong $wrong.exact_path }
}
Case 'cache: matching URL from another Campaign is rejected' {
    $other = New-HostingScope -Brand maiocha -CampaignId '看屋別只看裝潢_2026-09-18' -Workspace $fixture
    $wrong = $asset | ConvertTo-Json | ConvertFrom-Json
    $wrong.hosted_object_key = $other.hosting_namespace + '/feed/01.jpg'
    $wrong.public_url = Get-ScopedHostedUrl $other $wrong.hosted_object_key
    Assert-Reject { Get-HostingVerificationIdentity $maiocha $wrong $wrong.exact_path }
}

# Import only the real publisher functions; never execute its publishing script body.
$publisher = Join-Path $legacyTools 'Instagram官方發布/同步發布CampaignV2.ps1'
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($publisher,[ref]$null,[ref]$errors)
Assert-True (@($errors).Count -eq 0)
foreach ($name in @('Get-PublicMediaUrl','Test-StableHostedAsset')) {
    $definition = $ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$false)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:remoteReadCount = 0
$script:remoteMatches = $true
function Test-ScopedRemoteBytes { param($Config,$Identity,$ContentType) $script:remoteReadCount++; return $script:remoteMatches }
$script:campaignFolder = $maiocha.source_root
$script:hostingConfig = $maiocha
$script:hostingCache = [pscustomobject]@{schema_version=2;items=@()}
$EnablePublish = $false
Case 'publisher: cache miss downloads before trusting image' {
    Assert-True (Test-StableHostedAsset $asset $asset.exact_path)
    Assert-True ($script:remoteReadCount -eq 1)
    Assert-True (Test-StableHostedAsset $asset $asset.exact_path)
    Assert-True ($script:remoteReadCount -eq 1)
}
Case 'publisher: same hash and different allowed URL revalidates' {
    $second = Fixture-Asset $maiocha '02.jpg'
    Assert-True (Test-StableHostedAsset $second $second.exact_path)
    Assert-True ($script:remoteReadCount -eq 2)
}
Case 'publisher: substituted baobao URL fails before network/cache' {
    $wrong = $asset | ConvertTo-Json | ConvertFrom-Json
    $wrong.public_url = Get-ScopedHostedUrl $baobao ($baobao.hosting_namespace + '/feed/01.jpg')
    Assert-True (-not (Test-StableHostedAsset $wrong $wrong.exact_path))
    Assert-Reject { Get-PublicMediaUrl $wrong }
    Assert-True ($script:remoteReadCount -eq 2)
}
Case 'publisher: formal publication cannot reuse cached bytes' {
    $EnablePublish = $true
    $before = $script:remoteReadCount
    $script:remoteMatches = $false
    Assert-True (-not (Test-StableHostedAsset $asset $asset.exact_path))
    Assert-True ($script:remoteReadCount -eq ($before + 1))
    $script:remoteMatches = $true
}
Case 'publisher: every container URL is guarded' {
    $source = Get-Content -Raw -LiteralPath $publisher
    Assert-True ($source -match '\$publicUrl = Get-PublicMediaUrl \$childSpec')
    Assert-True (@([regex]::Matches($source,'\$publicUrl = Get-PublicMediaUrl \$spec')).Count -eq 2)
    Assert-True ($source.IndexOf('foreach ($boundAsset in $boundAssets)') -lt $source.IndexOf('Import-MetaEnvironment -Path'))
}

foreach ($pair in @(@($maiocha,$baobao),@($baobao,$maiocha))) {
    $from = $pair[0];$to = $pair[1];$label=$from.brand+' to '+$to.brand
    $foreign = $to.hosting_namespace + '/sentinel.jpg'
    $sentinel = Join-Path $to.staging_repository $foreign
    [IO.File]::WriteAllText($sentinel,'FOREIGN BRAND SENTINEL')
    $source = Join-Path $from.source_root 'fixture.jpg'
    $hash = (Get-FileHash -LiteralPath $source).Hash
    Case "hosting: $label upload/overwrite rejected" {
        Assert-Reject { Upload-Media $from $foreign $source $hash }
        Assert-True ([IO.File]::ReadAllText($sentinel) -ceq 'FOREIGN BRAND SENTINEL')
    }
    Case "hosting: $label delete rejected" {
        Assert-Reject { Remove-Media $from $foreign -Confirm }
        Assert-True (Test-Path -LiteralPath $sentinel)
    }
    Case "hosting: $label cleanup rejected" {
        Assert-Reject { Cleanup-CampaignMedia $from $to.hosting_namespace $true $true $true -Confirm }
        Assert-True (Test-Path -LiteralPath $sentinel)
    }
    Case "hosting: $label local source rejected" {
        $otherSource = Join-Path $to.source_root 'fixture.jpg'
        Assert-Reject { Upload-Media $from ($from.hosting_namespace+'/foreign.jpg') $otherSource (Get-FileHash -LiteralPath $otherSource).Hash }
    }
}
foreach ($key in @(
    'media/baobao-malicious/baobao-fixture-BB001/x.jpg',
    'media/baobao/baobao-fixture-BB001-other/x.jpg',
    'media/baobao/baobao-fixture-BB001/../../maiocha-other/x.jpg',
    'media/baobao/baobao-fixture-BB001/%2e%2e/%2e%2e/maiocha-other/x.jpg',
    'media/baobao/baobao-fixture-BB001/%252e%252e/%252e%252e/maiocha-other/x.jpg',
    'media\baobao\baobao-fixture-BB001\..\..\maiocha-other\x.jpg',
    'media/baobao/baobao-fixture-BB001./x.jpg',
    'media/baobao/baobao-fixture-BB001/x.jpg:stream'
)) {
    Case "boundary: reject $key" { Assert-Reject { Assert-ObjectKeyBoundary $key $baobao.hosting_namespace } }
}
Case 'boundary: redundant separators and dots normalize within scope' {
    Assert-True ((Assert-ObjectKeyBoundary 'media//baobao/./baobao-fixture-BB001/feed/../01.jpg' $baobao.hosting_namespace) -ceq ($baobao.hosting_namespace+'/01.jpg'))
}
Case 'boundary: local sibling prefix is not a child' {
    Assert-Reject { Assert-LocalPathBoundary $maiocha.source_root ($maiocha.source_root+'-other/file.jpg') }
}
Case 'boundary: reparse/junction cannot redirect upload or cleanup' {
    $scopeRoot = Join-Path $baobao.staging_repository $baobao.hosting_namespace
    $link = Join-Path $scopeRoot 'jump'
    $foreignRoot = Join-Path $maiocha.staging_repository $maiocha.hosting_namespace
    $type = if ($IsWindows) {'Junction'}else{'SymbolicLink'}
    New-Item -ItemType $type -Path $link -Target $foreignRoot | Out-Null
    try {
        Assert-Reject { Upload-Media $baobao ($baobao.hosting_namespace+'/jump/x.jpg') (Join-Path $baobao.source_root 'fixture.jpg') (Get-FileHash -LiteralPath (Join-Path $baobao.source_root 'fixture.jpg')).Hash }
        Assert-Reject { Cleanup-CampaignMedia $baobao $baobao.hosting_namespace $true $true $true -Confirm }
    } finally { Remove-Item -LiteralPath $link -Force }
}
foreach ($scope in @($maiocha,$baobao)) {
    Case ('hosting: valid '+$scope.brand+' upload/delete/cleanup stays scoped') {
        $source = Join-Path $scope.source_root 'fixture.jpg';$key=$scope.hosting_namespace+'/owned/ok.jpg'
        $null = Upload-Media $scope $key $source (Get-FileHash -LiteralPath $source).Hash
        Assert-True (Test-Path -LiteralPath (Join-Path $scope.staging_repository $key))
        Remove-Media $scope $key -Confirm
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $scope.staging_repository $key)))
        Cleanup-CampaignMedia $scope ($scope.hosting_namespace+'/owned') $true $true $true -Confirm
        Assert-True (Test-Path -LiteralPath (Join-Path $scope.staging_repository ($scope.hosting_namespace+'/sentinel.jpg')))
    }
}

$engine = (Get-Process -Id $PID).Path
$launcher = Join-Path $legacyTools 'Instagram官方發布/同步發布品牌.ps1'
Case 'launcher: missing explicit brand rejects without prompting' {
    & $engine -NoProfile -NonInteractive -File $launcher -DescribeContext 2>$null | Out-Null
    Assert-True ($LASTEXITCODE -ne 0)
}
foreach ($brand in @('maiocha','baobao','MAIOCHA')) {
    Case "launcher: explicit $brand creates only matching context" {
        $result = & $engine -NoProfile -NonInteractive -File $launcher -Brand $brand -DescribeContext | ConvertFrom-Json
        Assert-True ($LASTEXITCODE -eq 0 -and $result.brand -ceq $brand.ToLowerInvariant() -and -not $result.publication_requested)
        Assert-True ([IO.Path]::GetFileName($result.entry) -ceq $(if($brand -ieq 'maiocha'){'同步發布CampaignV2.ps1'}else{'baobao.ps1'}))
    }
}
Case 'launcher: invalid brand rejects' {
    & $engine -NoProfile -NonInteractive -File $launcher -Brand other -DescribeContext 2>$null | Out-Null
    Assert-True ($LASTEXITCODE -ne 0)
}
Case 'retired Release backend cannot write/delete anything' {
    & {
        . (Join-Path $legacyTools '媒體託管/GitHubReleaseMediaHosting.ps1')
        function Get-GitHubHeaders { throw 'NETWORK_MUST_NOT_BE_REACHED' }
        Assert-Reject { New-GitHubRelease ([pscustomobject]@{}) } 'UNSCOPED_RELEASE_HOSTING_DISABLED'
        Assert-Reject { Upload-Media ([pscustomobject]@{}) 'other' 'image' 'missing' 'hash' } 'UNSCOPED_RELEASE_HOSTING_DISABLED'
        Assert-Reject { Remove-Media ([pscustomobject]@{}) '123' } 'UNSCOPED_RELEASE_HOSTING_DISABLED'
        Assert-Reject { Cleanup-CampaignMedia ([pscustomobject]@{}) 'other' -Confirm } 'UNSCOPED_RELEASE_HOSTING_DISABLED'
    }
}

Case 'policy: foreign namespace cannot be registered under maiocha' {
    $policyPath = Join-Path $fixtureRepo 'config/hosting-scopes.json'
    $original = [IO.File]::ReadAllBytes($policyPath)
    try {
        $policy = Get-Content -Raw -LiteralPath $policyPath | ConvertFrom-Json
        @($policy.brands.maiocha.campaigns.PSObject.Properties)[0].Value.namespace = $baobao.hosting_namespace
        $policy | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $policyPath -Encoding utf8
        Assert-Reject { New-HostingScope -Brand maiocha -CampaignId $maiocha.campaign_id -Workspace $fixture }
    } finally { [IO.File]::WriteAllBytes($policyPath,$original) }
}
Case 'legacy temporary host: foreign media cannot start a server' {
    & {
        . (Join-Path $legacyTools 'Instagram官方發布/暫時公開測試圖片.ps1')
        function Start-Process { throw 'PROCESS_MUST_NOT_START' }
        Assert-Reject { Start-TemporaryInstagramMediaHost -MediaPath (Join-Path $baobao.source_root 'fixture.jpg') -ToolFolder (Join-Path $legacyTools 'Instagram官方發布') }
    }
}
Case 'legacy temporary cleanup: foreign log path cannot be deleted' {
    & {
        . (Join-Path $legacyTools 'Instagram官方發布/暫時公開測試圖片.ps1')
        $victim = Join-Path $baobao.source_root 'fixture.jpg'
        Assert-Reject { Stop-TemporaryInstagramMediaHost ([pscustomobject]@{Brand='maiocha';LogPath=$victim;ServerProcess=$null;TunnelProcess=$null}) }
        Assert-True (Test-Path -LiteralPath $victim)
    }
}
Case 'legacy single test: arbitrary public URL fails before credentials/API' {
    $testTool = Join-Path $legacyTools 'Instagram官方發布'
    @{test_media_url='https://edisonraywu.github.io/maiocha-media-host/media/baobao/foreign.jpg'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $testTool 'instagram_config.json') -Encoding utf8
    [IO.File]::WriteAllText((Join-Path $testTool 'Meta環境設定.ps1'),"function Import-MetaEnvironment { throw 'CREDENTIALS_MUST_NOT_BE_LOADED' }")
    $output = & $engine -NoProfile -NonInteractive -File (Join-Path $testTool '發布單張測試.ps1') -DryRun 2>&1 | Out-String
    Assert-True ($LASTEXITCODE -ne 0 -and $output -match 'UNSCOPED_TEST_MEDIA_URL_FORBIDDEN')
}
Case 'legacy Campaign: canonical bundle boundary replaces prefix matching' {
    $path = Join-Path $legacyTools 'Instagram官方發布/同步發布Campaign.ps1'
    $tree = [Management.Automation.Language.Parser]::ParseFile($path,[ref]$null,[ref]$null)
    $definition = $tree.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Resolve-BundlePath'},$false)
    . ([scriptblock]::Create($definition.Extent.Text))
    $CampaignFolder = $maiocha.source_root
    Assert-True ((Resolve-BundlePath 'fixture.jpg') -ceq (Join-Path $maiocha.source_root 'fixture.jpg'))
    $relative = [IO.Path]::GetRelativePath($CampaignFolder,(Join-Path $baobao.source_root 'fixture.jpg'))
    Assert-Reject { Resolve-BundlePath $relative }
}

$stateFolder = Join-Path $OutputRoot 'maiocha-regression'
New-Item -ItemType Directory -Force -Path $stateFolder | Out-Null
$media = [ordered]@{}
foreach ($key in @('feed_carousel','reel','story_01','story_02','story_03')) {
    $media[$key] = @{publish_status='pending';container_status='pending'}
}
$media.feed_carousel.children = @(1..6 | ForEach-Object { @{key=('feed_child_{0:D2}' -f $_);container_status='pending';creation_id=$null} })
@{campaign_id='maiocha-fixture';media=$media} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stateFolder 'campaign_status.json') -Encoding utf8
Case 'maiocha: all eight original state machine cases pass' {
    & $engine -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'fixtures/maiocha-state-machine.ps1') -CampaignFolder $stateFolder | Out-Null
    $legacy = Get-Content -Raw -LiteralPath (Join-Path $stateFolder 'V2狀態機測試.json') | ConvertFrom-Json
    Assert-True ($LASTEXITCODE -eq 0 -and $legacy.all_passed -and @($legacy.results.PSObject.Properties).Count -eq 8)
}
$failed = @($cases | Where-Object { $_.result -ne 'PASS' })
$report = [pscustomobject]@{result=if($failed.Count){'FAIL'}else{'PASS'};security_cases=$cases.Count;failed=$failed.Count;maiocha_original_cases=8;instagram_post_requests=0;fixtures_only=$true;cases=$cases}
$report | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $OutputRoot 'isolation-tests.json') -Encoding utf8
[pscustomobject]@{result=$report.result;security_cases=$cases.Count;failed=$failed.Count;report=(Join-Path $OutputRoot 'isolation-tests.json');instagram_post_requests=0} | ConvertTo-Json
if ($failed.Count) { exit 1 }
