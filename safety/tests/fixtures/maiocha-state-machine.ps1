param([Parameter(Mandatory = $true)][string]$CampaignFolder)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$folder = (Resolve-Path -LiteralPath $CampaignFolder).Path
$statusPath = Join-Path $folder 'campaign_status.json'
$template = Get-Content -Raw -LiteralPath $statusPath | ConvertFrom-Json
$order = @('feed_carousel','reel','story_01','story_02','story_03')

function Copy-State($State) {
    return ($State | ConvertTo-Json -Depth 12 | ConvertFrom-Json)
}

function Get-ResumeAction($State) {
    foreach ($key in $order) {
        $entry = $State.media.$key
        if ($entry.publish_status -eq 'success') { continue }
        if ($entry.publish_status -eq 'uncertain' -or $entry.container_status -eq 'uncertain') { return "resolve:$key" }
        return $key
    }
    return 'complete'
}

function Set-PublishStatus($State, [string]$Key, [string]$Value) {
    $State.media.$Key.publish_status = $Value
    if ($Value -eq 'success') { $State.media.$Key.container_status = 'published' }
}

$results = [ordered]@{}

$state = Copy-State $template
$results.fresh_campaign_starts_at_feed = ((Get-ResumeAction $state) -eq 'feed_carousel')

$state = Copy-State $template
Set-PublishStatus $state 'feed_carousel' 'failed'
$results.feed_failure_stops_downstream = ((Get-ResumeAction $state) -eq 'feed_carousel')

$state = Copy-State $template
Set-PublishStatus $state 'feed_carousel' 'success'
Set-PublishStatus $state 'reel' 'failed'
$results.feed_success_reel_failure_resumes_reel = ((Get-ResumeAction $state) -eq 'reel')

$state = Copy-State $template
Set-PublishStatus $state 'feed_carousel' 'success'
Set-PublishStatus $state 'reel' 'success'
Set-PublishStatus $state 'story_01' 'success'
Set-PublishStatus $state 'story_02' 'failed'
$results.story_02_failure_skips_story_01 = ((Get-ResumeAction $state) -eq 'story_02')

$state = Copy-State $template
Set-PublishStatus $state 'feed_carousel' 'success'
Set-PublishStatus $state 'reel' 'success'
Set-PublishStatus $state 'story_01' 'success'
Set-PublishStatus $state 'story_02' 'success'
Set-PublishStatus $state 'story_03' 'failed'
$results.story_03_failure_skips_first_two = ((Get-ResumeAction $state) -eq 'story_03')

$state = Copy-State $template
$state.media.feed_carousel.publish_status = 'uncertain'
$results.uncertain_publish_requires_resolution = ((Get-ResumeAction $state) -eq 'resolve:feed_carousel')

$state = Copy-State $template
$state.media.feed_carousel.children[0].container_status = 'finished'
$state.media.feed_carousel.children[0].creation_id = 'test-child-01'
$nextChild = @($state.media.feed_carousel.children | Where-Object { $_.container_status -ne 'finished' })[0]
$results.finished_carousel_child_is_not_recreated = ($nextChild.key -eq 'feed_child_02')

$state = Copy-State $template
foreach ($key in $order) { Set-PublishStatus $state $key 'success' }
$results.all_success_is_complete = ((Get-ResumeAction $state) -eq 'complete')

$allPassed = -not (@($results.Values | Where-Object { $_ -ne $true }).Count -gt 0)
$report = [ordered]@{
    checked_at = (Get-Date).ToString('o')
    campaign_id = [string]$template.campaign_id
    results = $results
    all_passed = $allPassed
}
$output = Join-Path $folder 'V2狀態機測試.json'
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding utf8
[pscustomobject]@{ all_passed=$allPassed; output=$output } | ConvertTo-Json
if (-not $allPassed) { exit 1 }
