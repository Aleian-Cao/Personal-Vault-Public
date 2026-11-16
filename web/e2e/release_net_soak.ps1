param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$Out, [int]$Seconds = 240, [string]$Label = 'release')
# Long-enough network observation of the RELEASE binary (no debug port, nothing driving it). Non-loopback TCP of the whole process tree,
# with owning process role/start/command line. Observation only. SYNTHETIC (throw-away profile, no vault).
$win = Join-Path $PSScriptRoot 'win.ps1'
$root = Join-Path $env:TEMP ('pv-rnet-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force $root | Out-Null
$env:LOCALAPPDATA = $root; $env:WEBVIEW2_USER_DATA_FOLDER = Join-Path $root 'wv'
$p = Start-Process -FilePath $Exe -PassThru
function J($lines) { if (-not $lines) { return @() }; ($lines -join "`n") | ConvertFrom-Json | ForEach-Object { $_ } }
$t0 = Get-Date; $seen = @{}; $info = @{}; $n = 0
while (((Get-Date) - $t0).TotalSeconds -lt $Seconds) {
  $tree = @(J (& powershell -NoProfile -ExecutionPolicy Bypass -File $win -Action memtree -Arg1 $p.Id))
  if ($tree.Count -gt 0) {
    $pids = ($tree | ForEach-Object { $_.pid }) -join ','
    $roles = @{}; $tree | ForEach-Object { $roles[[int]$_.pid] = "$($_.name)($($_.role))" }
    $net = @(J (& powershell -NoProfile -ExecutionPolicy Bypass -File $win -Action tcp -Arg1 $pids))
    foreach ($c in $net) {
      if ($c.remote -match '^(127\.|\[?::1|0\.0\.0\.0)') { continue }
      $k = "$($c.pid)|$($c.local)|$($c.remote)|$($c.state)"
      if (-not $seen.ContainsKey($k)) {
        if (-not $info.ContainsKey($c.pid)) { $info[$c.pid] = (J (& powershell -NoProfile -ExecutionPolicy Bypass -File $win -Action procinfo -Arg1 $c.pid)) }
        $seen[$k] = [pscustomobject]@{ atSec = [int]((Get-Date) - $t0).TotalSeconds; pid = $c.pid; role = $roles[[int]$c.pid]; remote = $c.remote; state = $c.state; procInfo = $info[$c.pid] }
      }
    }
  }
  $n++
  Start-Sleep -Seconds 2
}
[void]$p.CloseMainWindow(); Start-Sleep 3; if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
$rep = [pscustomobject]@{ label = $Label; exe = $Exe; seconds = $Seconds; samples = $n; foreignSockets = @($seen.Values) }
$rep | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $Out "release_net_$Label.json") -Encoding UTF8
"release net soak ${Label}: $n samples, $($seen.Count) distinct non-loopback sockets"
$seen.Values | ForEach-Object { "  at $($_.atSec)s $($_.role) $($_.remote) $($_.state)" }
Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
