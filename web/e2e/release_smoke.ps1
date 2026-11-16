param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$Out)
# Smoke of the RELEASE binary (no debug port, no automation hooks): launch, capture the window, inspect sockets, close.
$win = Join-Path $PSScriptRoot 'win.ps1'
$root = Join-Path $env:TEMP ('pv-smoke-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force $root | Out-Null
$env:LOCALAPPDATA = $root
$env:WEBVIEW2_USER_DATA_FOLDER = Join-Path $root 'wv'
$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $Exe -PassThru
$deadline = (Get-Date).AddSeconds(30); $title = ''
while ((Get-Date) -lt $deadline -and $title -ne 'Personal Vault') { Start-Sleep -Milliseconds 250; $p.Refresh(); $title = $p.MainWindowTitle }
$startupMs = $sw.ElapsedMilliseconds
Start-Sleep -Seconds 3
$shot = & powershell -NoProfile -ExecutionPolicy Bypass -File $win -Action shot -Arg1 'Personal Vault' -Arg2 (Join-Path $Out '00_release_welcome.png')
$tree = & powershell -NoProfile -ExecutionPolicy Bypass -File $win -Action tree -Arg1 $p.Id | ConvertFrom-Json
$pids = ($tree | ForEach-Object { $_.pid }) -join ','
$tcp = & powershell -NoProfile -ExecutionPolicy Bypass -File $win -Action tcp -Arg1 $pids
$hk = & powershell -NoProfile -ExecutionPolicy Bypass -File $win -Action hotkeycheck
$sidecars = @($tree | Where-Object { $_.name -eq 'pvault-sidecar.exe' }).Count
$ws = [math]::Round(($tree | Measure-Object wsMB -Sum).Sum, 1)
[void]$p.CloseMainWindow()
for ($i = 0; $i -lt 20 -and -not $p.HasExited; $i++) { Start-Sleep -Milliseconds 500 }
$closed = $p.HasExited
if (-not $closed) { Stop-Process -Id $p.Id -Force }
Start-Sleep -Seconds 1
$orphans = @(Get-Process pvault-sidecar -ErrorAction SilentlyContinue).Count
[pscustomobject]@{
  windowTitle = $title; windowUpMs = $startupMs; screenshot = $shot; processes = @($tree).Count; sidecarProcesses = $sidecars
  workingSetMB = $ws; tcpEndpoints = $(if ($tcp) { $tcp | ConvertFrom-Json } else { @() }); hotkey = $hk
  closedViaWmClose = $closed; orphanSidecars = $orphans
} | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $Out 'release_smoke.json') -Encoding UTF8
Get-Content (Join-Path $Out 'release_smoke.json')
Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
