param([Parameter(Mandatory=$true)][string]$BundleFolder)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'GitHubPagesMediaHosting.ps1')
$scope = Get-ScopedCampaignConfig -BundleFolder $BundleFolder
if ($scope.campaign_path -cne 'media/maiocha-restart-firstpost-mortgage-ltv-2026-09-19') { throw 'HOSTING_FINALIZER_CONTEXT_MISMATCH' }
function Set-P($o,[string]$n,$v){$p=$o.PSObject.Properties[$n];if($null-eq$p){$o|Add-Member -NotePropertyName $n -NotePropertyValue $v}else{$p.Value=$v}}
$base='https://edisonraywu.github.io/maiocha-media-host';$campaign='media/maiocha-restart-firstpost-mortgage-ltv-2026-09-19'
$bundle=(Resolve-Path -LiteralPath $BundleFolder).Path;$mp=Join-Path $bundle 'manifest.json';$m=Get-Content -Raw -LiteralPath $mp|ConvertFrom-Json
if([string]$m.source_selection_mode-cne'exact_paths_only'-or[bool]$m.wildcards_allowed){throw 'Manifest selection invalid'}
$targets=@();for($i=0;$i-lt 6;$i++){$targets+=[pscustomobject]@{asset=$m.media.feed_carousel.children[$i];key=("$campaign/feed/{0:d2}.jpg"-f($i+1));type='image/jpeg';range=$false}}
$targets+=[pscustomobject]@{asset=$m.media.reel;key="$campaign/reel/reel-24s-7-scenes.mp4";type='video/mp4';range=$true}
$targets+=[pscustomobject]@{asset=$m.media.story_01;key="$campaign/story/01.jpg";type='image/jpeg';range=$false}
$targets+=[pscustomobject]@{asset=$m.media.story_02;key="$campaign/story/02.jpg";type='image/jpeg';range=$false}
$targets+=[pscustomobject]@{asset=$m.media.story_03;key="$campaign/story/03.jpg";type='image/jpeg';range=$false}
if($targets.Count-ne10){throw 'Expected exactly 10 assets'}
$verified=(Get-Date).ToString('o');$items=[Collections.Generic.List[object]]::new()
foreach($t in $targets){
  $a=$t.asset;$local=[IO.Path]::GetFullPath([string]$a.exact_path);if(-not$local.StartsWith($bundle,[StringComparison]::OrdinalIgnoreCase)){throw "outside bundle $($a.key)"}
  $expectedHash=(Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash;$expectedSize=(Get-Item -LiteralPath $local).Length;if($expectedHash-cne[string]$a.sha256){throw "local manifest hash mismatch $($a.key)"}
  $url="$base/$($t.key)";$tmp=Join-Path ([IO.Path]::GetTempPath()) ('maiocha-'+[guid]::NewGuid().ToString('N'))
  try{
    $meta=& curl.exe -sS -L --fail --max-time 180 -o $tmp -w '%{http_code}|%{content_type}|%{url_effective}' $url
    if($LASTEXITCODE-ne0){throw "curl failed $($a.key)"};$parts=([string]$meta).Split('|');if($parts.Count-lt3){throw "bad curl metadata $($a.key)"}
    $status=[int]$parts[0];$ct=[string]$parts[1];$final=[string]$parts[2];if($status-ne200){throw "HTTP $status"};if($ct-cne$t.type){throw "Content-Type $ct"};if($final-match'(login|signin)'){throw 'redirected to login'}
    $size=(Get-Item -LiteralPath $tmp).Length;$hash=(Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash;if($size-ne$expectedSize-or$hash-cne$expectedHash){throw "download mismatch $($a.key)"}
    $rangeStatus=$null;if($t.range){$rangeTmp=$tmp+'.range';try{$rangeStatus=[int](& curl.exe -sS -L --fail --max-time 60 -r 0-1023 -o $rangeTmp -w '%{http_code}' $url);if($LASTEXITCODE-ne0-or$rangeStatus-ne206-or(Get-Item -LiteralPath $rangeTmp).Length-ne1024){throw "range failed $rangeStatus"}}finally{if(Test-Path -LiteralPath $rangeTmp){Remove-Item -LiteralPath $rangeTmp -Force}}}
    Set-P $a hosting_provider 'github_pages';Set-P $a hosted_object_key $t.key;Set-P $a hosted_url $url;Set-P $a public_url $url;Set-P $a upload_status 'uploaded';Set-P $a accessibility_status 'verified';Set-P $a content_type $t.type;Set-P $a uploaded_at $verified;Set-P $a verified_at $verified
    $items.Add([pscustomobject]@{key=[string]$a.key;https=$true;http_status=$status;content_type=$ct;file_size=$size;sha256=$hash;range_status=$rangeStatus;anonymous=$true;passed=$true})
  }finally{if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force}}
}
$m|ConvertTo-Json -Depth 30|Set-Content -LiteralPath $mp -Encoding utf8;$m|ConvertTo-Json -Depth 30|Set-Content -LiteralPath (Join-Path $bundle 'Manifest\campaign_manifest.json') -Encoding utf8
$hf=Join-Path $bundle 'Hosting';$rf=Join-Path $bundle 'Reports'
[pscustomobject]@{provider='github_pages';owner_repo='edisonraywu/maiocha-media-host';pages_base_url=$base;campaign_path=$campaign;free_plan=$true;credit_card_required=$false;paid_features_enabled=$false;retention='keep_until_publish_success_plus_buffer'}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $hf 'hosting_config.json') -Encoding utf8
[pscustomobject]@{provider='github_pages';campaign_id=[string]$m.campaign_id;status='verified';uploaded_count=10;public_url_verified_count=10;verified_at=$verified;items=$items}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $hf 'hosting_status.json') -Encoding utf8
$lines=@('# 10/10 Media Accessibility Report','',"Verified at: $verified",'','| Key | HTTPS | HTTP | Content-Type | Size/hash | Range | Result |','|---|---:|---:|---|---|---:|---|')
foreach($i in $items){$rs=if($null-eq$i.range_status){'n/a'}else{[string]$i.range_status};$lines+="| $($i.key) | yes | 200 | $($i.content_type) | match | $rs | pass |"};$lines+='';$lines+='Anonymous HTTPS; no login, cookie, token, localhost, Windows host, or tunnel dependency.';$lines|Set-Content -LiteralPath (Join-Path $rf 'MediaAccessibility報告.md') -Encoding utf8
@('# Hosting Report','','- Provider: GitHub Pages public repository','- Free plan; no credit card; no paid feature','- Uploaded: 10/10','- Anonymous HTTPS: 10/10','- Content-Type and SHA-256: 10/10','- MP4 Range Request: 206','- Cleanup: disabled before publishing','- /media_publish calls: 0')|Set-Content -LiteralPath (Join-Path $rf 'Hosting報告.md') -Encoding utf8
[pscustomobject]@{uploaded=10;verified=10;all_passed=$true;api_post_requests_sent=0}|ConvertTo-Json
