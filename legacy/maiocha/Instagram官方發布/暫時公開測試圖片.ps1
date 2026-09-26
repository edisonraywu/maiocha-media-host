$safetyRepo = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) 'maiocha-media-host-staging'
. (Join-Path $safetyRepo 'safety/HostingSafety.ps1')
function Start-TemporaryInstagramMediaHost {
    param(
        [Parameter(Mandatory = $true)][string]$MediaPath,
        [Parameter(Mandatory = $true)][string]$ToolFolder
    )

    $brandRoot = Get-LocalBrandRoot -Brand maiocha
    $MediaPath = Assert-LocalPathBoundary $brandRoot $MediaPath
    $ToolFolder = Assert-LocalPathBoundary $brandRoot $ToolFolder
    if ([IO.Path]::GetFullPath($ToolFolder) -cne [IO.Path]::GetFullPath($PSScriptRoot)) { throw 'HOSTING_LEGACY_TOOL_CONTEXT_MISMATCH' }
    $tunnel = $null
    $cloudflared = Join-Path $env:LOCALAPPDATA 'CodexBrowserBridge\cloudflared.exe'
    $serverScript = Join-Path $ToolFolder '本機媒體伺服器.ps1'
    $pwsh = (Get-Process -Id $PID).Path
    if (-not (Test-Path -LiteralPath $cloudflared -PathType Leaf)) { throw '找不到已驗證的 cloudflared。' }
    if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf)) { throw '找不到本機媒體伺服器。' }

    $extension = [System.IO.Path]::GetExtension($MediaPath).ToLowerInvariant()
    switch ($extension) {
        '.jpg'  { $publicPath = '/media.jpg'; $contentType = 'image/jpeg' }
        '.jpeg' { $publicPath = '/media.jpg'; $contentType = 'image/jpeg' }
        '.mp4'  { $publicPath = '/media.mp4'; $contentType = 'video/mp4' }
        default { throw "不支援的媒體格式：$extension" }
    }

    $port = Get-Random -Minimum 18000 -Maximum 28000
    $logPath = Join-Path $env:TEMP ("maiocha-cloudflared-{0}.log" -f [guid]::NewGuid().ToString('N'))
    $server = Start-Process -FilePath $pwsh -ArgumentList @(
        '-NoProfile', '-File', ('"{0}"' -f $serverScript),
        '-FilePath', ('"{0}"' -f $MediaPath), '-Port', $port,
        '-PublicPath', $publicPath, '-ContentType', $contentType
    ) -WindowStyle Hidden -PassThru

    try {
        $localReady = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 250
            try {
                $check = Invoke-WebRequest -Method Head -Uri ("http://127.0.0.1:$port$publicPath") -TimeoutSec 2
                if ($check.StatusCode -eq 200) { $localReady = $true; break }
            } catch {}
        }
        if (-not $localReady) { throw '本機測試圖片伺服器未啟動。' }

        $tunnel = Start-Process -FilePath $cloudflared -ArgumentList @(
            'tunnel', '--url', "http://127.0.0.1:$port", '--no-autoupdate',
            '--logfile', ('"{0}"' -f $logPath), '--loglevel', 'info'
        ) -WindowStyle Hidden -PassThru

        $origin = $null
        for ($i = 0; $i -lt 80; $i++) {
            Start-Sleep -Milliseconds 500
            if (Test-Path -LiteralPath $logPath) {
                $fileStream = [System.IO.FileStream]::new(
                    $logPath,
                    [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::Read,
                    [System.IO.FileShare]::ReadWrite
                )
                try {
                    $reader = [System.IO.StreamReader]::new($fileStream)
                    try { $logText = $reader.ReadToEnd() } finally { $reader.Dispose() }
                } finally {
                    $fileStream.Dispose()
                }
                $match = [regex]::Match($logText, 'https://[a-z0-9-]+\.trycloudflare\.com')
                if ($match.Success) { $origin = $match.Value; break }
            }
            if ($tunnel.HasExited) { break }
        }
        if ([string]::IsNullOrWhiteSpace($origin)) { throw '無法建立 Cloudflare 臨時 HTTPS 通道。' }

        $publicUrl = $origin.TrimEnd('/') + $publicPath
        $publicReady = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $publicCheck = Invoke-WebRequest -Method Head -Uri $publicUrl -TimeoutSec 5
                if ($publicCheck.StatusCode -eq 200 -and $publicCheck.Headers.'Content-Type' -like "$contentType*") {
                    $publicReady = $true
                    break
                }
            } catch {}
        }
        if (-not $publicReady) { throw "臨時 HTTPS 網址無法讀取媒體：$contentType" }

        return [pscustomobject]@{
            Brand = 'maiocha'
            Url = $publicUrl
            ServerProcess = $server
            TunnelProcess = $tunnel
            LogPath = $logPath
            ContentType = $contentType
            PublicPath = $publicPath
        }
    } catch {
        if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
        if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $logPath) { Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue }
        throw
    }
}

function Stop-TemporaryInstagramMediaHost {
    param([Parameter(Mandatory = $true)]$HostInfo)
    if ($null -eq $HostInfo.PSObject.Properties['Brand'] -or $HostInfo.Brand -cne 'maiocha') { throw 'HOSTING_TEMP_BRAND_MISMATCH' }
    $safeLog = Assert-LocalPathBoundary ([IO.Path]::GetTempPath()) $HostInfo.LogPath
    if ([IO.Path]::GetDirectoryName($safeLog).TrimEnd([IO.Path]::DirectorySeparatorChar) -cne [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar) -or
        [IO.Path]::GetFileName($safeLog) -cnotmatch '^maiocha-cloudflared-[0-9a-f]{32}\.log$') { throw 'HOSTING_TEMP_LOG_SCOPE_MISMATCH' }
    foreach ($process in @($HostInfo.TunnelProcess, $HostInfo.ServerProcess)) {
        if ($process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if ($HostInfo.LogPath -and (Test-Path -LiteralPath $HostInfo.LogPath)) {
        Remove-Item -LiteralPath $HostInfo.LogPath -Force -ErrorAction SilentlyContinue
    }
}
