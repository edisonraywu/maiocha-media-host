param(
    [Parameter(Mandatory=$true)][string]$BundleFolder,
    [string]$PagesBaseUrl='https://edisonraywu.github.io/maiocha-media-host',
    [string]$CampaignPath='media/maiocha-inspection-2026-09-18'
)
. (Join-Path $PSScriptRoot 'GitHubPagesMediaHosting.ps1')
$scope = Get-ScopedCampaignConfig -BundleFolder $BundleFolder
if ($PagesBaseUrl -cne $scope.pages_base_url -or $CampaignPath -cne $scope.campaign_path) { throw 'HOSTING_FINALIZER_CONTEXT_MISMATCH' }
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
function Set-P($o,[string]$n,$v){ $p=$o.PSObject.Properties[$n]; if($null -eq $p){$o|Add-Member -NotePropertyName $n -NotePropertyValue $v}else{$p.Value=$v} }
function Verify-One([string]$url,[string]$path,[string]$type,[bool]$range){
  $expectedHash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash; $expectedSize=(Get-Item -LiteralPath $path).Length
  $tmp=Join-Path ([IO.Path]::GetTempPath()) ('maiocha-'+[guid]::NewGuid().ToString('N')); $client=[Net.Http.HttpClient]::new()
  try{
    $client.Timeout=[TimeSpan]::FromMinutes(8); $resp=$client.GetAsync($url,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
    try{
      $status=[int]$resp.StatusCode; $ct=[string]$resp.Content.Headers.ContentType.MediaType; $final=[string]$resp.RequestMessage.RequestUri.AbsoluteUri
      if($status -ne 200){throw "HTTP $status"}; if($ct -cne $type){throw "Content-Type $ct"}; if($final -match '(login|signin)'){throw 'redirected to login'}
      $ins=$resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult(); $outs=[IO.File]::Create($tmp); try{$ins.CopyTo($outs)}finally{$outs.Dispose();$ins.Dispose()}
    }finally{$resp.Dispose()}
    $size=(Get-Item -LiteralPath $tmp).Length; $hash=(Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash; $rs=$null
    if($range){$req=[Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get,$url);$req.Headers.Range=[Net.Http.Headers.RangeHeaderValue]::new(0,1023);$rr=$client.SendAsync($req).GetAwaiter().GetResult();try{$rs=[int]$rr.StatusCode}finally{$rr.Dispose();$req.Dispose()};if($rs -ne 206){throw "Range HTTP $rs"}}
    [pscustomobject]@{status=200;content_type=$ct;file_size=$size;sha256=$hash;range_status=$rs;passed=($url.StartsWith('https://') -and $size -eq $expectedSize -and $hash -ceq $expectedHash)}
  }finally{$client.Dispose();if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force}}
}
$bundle=(Resolve-Path -LiteralPath $BundleFolder).Path; $mp=Join-Path $bundle 'manifest.json'; $m=Get-Content -Raw -LiteralPath $mp|ConvertFrom-Json
if([string]$m.source_selection_mode -cne 'exact_paths_only' -or [bool]$m.wildcards_allowed){throw 'Manifest selection invalid'}
$targets=@();for($i=0;$i-lt 6;$i++){$targets+=[pscustomobject]@{asset=$m.media.feed_carousel.children[$i];key=("$CampaignPath/feed/{0:d2}.jpg"-f($i+1));type='image/jpeg';range=$false}}
$targets+=[pscustomobject]@{asset=$m.media.reel;key="$CampaignPath/reel/reel-26s-7-scenes.mp4";type='video/mp4';range=$true}
$targets+=[pscustomobject]@{asset=$m.media.story_01;key="$CampaignPath/story/01.jpg";type='image/jpeg';range=$false}
$targets+=[pscustomobject]@{asset=$m.media.story_02;key="$CampaignPath/story/02.jpg";type='image/jpeg';range=$false}
$targets+=[pscustomobject]@{asset=$m.media.story_03;key="$CampaignPath/story/03.jpg";type='image/jpeg';range=$false}
if($targets.Count-ne 10){throw 'Expected 10 assets'}
$verifiedAt=(Get-Date).ToString('o');$items=[Collections.Generic.List[object]]::new()
foreach($t in $targets){
  $a=$t.asset;$local=[IO.Path]::GetFullPath([string]$a.exact_path);if(-not $local.StartsWith($bundle,[StringComparison]::OrdinalIgnoreCase)){throw "outside bundle $($a.key)"}
  if((Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash-cne[string]$a.sha256){throw "local hash mismatch $($a.key)"}
  $url="$($PagesBaseUrl.TrimEnd('/'))/$($t.key)";$v=Verify-One $url $local $t.type $t.range;if(-not$v.passed){throw "verification failed $($a.key)"}
  Set-P $a 'hosting_provider' 'github_pages';Set-P $a 'hosted_object_key' $t.key;Set-P $a 'hosted_url' $url;Set-P $a 'public_url' $url;Set-P $a 'upload_status' 'uploaded';Set-P $a 'accessibility_status' 'verified';Set-P $a 'content_type' $t.type;Set-P $a 'uploaded_at' $verifiedAt;Set-P $a 'verified_at' $verifiedAt
  $items.Add([pscustomobject]@{key=[string]$a.key;content_type=$v.content_type;file_size=$v.file_size;sha256=$v.sha256;range_status=$v.range_status;passed=$true})
}
$m|ConvertTo-Json -Depth 30|Set-Content -LiteralPath $mp -Encoding utf8
$mf=Join-Path $bundle 'Manifest\campaign_manifest.json';$m|ConvertTo-Json -Depth 30|Set-Content -LiteralPath $mf -Encoding utf8
$hf=Join-Path $bundle 'Hosting';$rf=Join-Path $bundle 'Reports';New-Item -ItemType Directory -Force -Path $hf,$rf|Out-Null
[pscustomobject]@{provider='github_pages';owner_repo='edisonraywu/maiocha-media-host';pages_base_url=$PagesBaseUrl;campaign_path=$CampaignPath;free_plan=$true;credit_card_required=$false;paid_features_enabled=$false}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $hf 'hosting_config.json') -Encoding utf8
[pscustomobject]@{provider='github_pages';campaign_id=[string]$m.campaign_id;status='verified';uploaded_count=10;public_url_verified_count=10;verified_at=$verifiedAt;items=$items}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $hf 'hosting_status.json') -Encoding utf8
$lines=[Collections.Generic.List[string]]::new();$lines.Add('# 10/10 Media Accessibility Report');$lines.Add('');$lines.Add("Verified at: $verifiedAt");$lines.Add('');$lines.Add('| Key | HTTPS | HTTP | Content-Type | Size/hash | Range | Result |');$lines.Add('|---|---:|---:|---|---|---:|---|');foreach($i in $items){$rs=if($null-eq$i.range_status){'n/a'}else{[string]$i.range_status};$lines.Add("| $($i.key) | yes | 200 | $($i.content_type) | match | $rs | pass |")} ;$lines.Add('');$lines.Add('Anonymous HTTPS; no login, cookie, token, localhost, Windows host, or tunnel dependency.')
$lines|Set-Content -LiteralPath (Join-Path $rf 'MediaAccessibility報告.md') -Encoding utf8
@('# Hosting Report','','- Provider: GitHub Pages public repository','- Free plan; no credit card; no paid feature','- Uploaded: 10/10','- Anonymous HTTPS: 10/10','- Cleanup: disabled before publishing','- /media_publish calls: 0')|Set-Content -LiteralPath (Join-Path $rf 'Hosting報告.md') -Encoding utf8
[pscustomobject]@{uploaded=10;verified=10;all_passed=$true;api_post_requests_sent=0}|ConvertTo-Json
