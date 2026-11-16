# QA inside Windows Sandbox (disposable VM; admin only here). SYNTHETIC ONLY.
#  B) network: ETW (TCPIP + DNS-Client) + pktmon headers + per-process socket sampling, baseline period WITHOUT the app, then WITH the app,
#     plus a positive control (a deliberate SYN to TEST-NET-1) to prove the sampler/trace can see an outbound attempt.
#  A) session: standalone sidecar EXE: suspend/resume path (wall-clock jump) and a REAL session lock (LockWorkStation, in the sandbox).
param([ValidateSet('full','dry')][string]$Mode = 'full', [ValidateSet('all','session','network')][string]$Phase = 'all', [int]$BaselineSec = 120, [int]$AppSec = 360)
$ErrorActionPreference = 'Continue'
$OUT = if ($Mode -eq 'dry') { Join-Path $env:TEMP 'qa-dry' } else { 'C:\out' }
$CAND = if ($Mode -eq 'dry') { $env:PV_CAND } else { 'C:\cand' }
New-Item -ItemType Directory -Force $OUT | Out-Null
$log = Join-Path $OUT 'qa_log.txt'
function Log($m) { "$(Get-Date -Format 'HH:mm:ss.fff') $m" | Tee-Object -FilePath $log -Append | Out-Null }
$result = [ordered]@{ mode = $Mode; startedUtc = (Get-Date).ToUniversalTime().ToString('o') }

Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class QA { [DllImport("user32.dll")] public static extern IntPtr OpenInputDesktop(int f, bool i, int a); [DllImport("user32.dll")] public static extern bool CloseDesktop(IntPtr d); }
"@
function InputDesktopOpen { $h = [QA]::OpenInputDesktop(0, $false, 1); if ($h -ne [IntPtr]::Zero) { [void][QA]::CloseDesktop($h); $true } else { $false } }

function Start-Sidecar([string]$exe, [string]$local) {
  New-Item -ItemType Directory -Force $local | Out-Null
  $psi = New-Object System.Diagnostics.ProcessStartInfo $exe
  $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $psi.EnvironmentVariables['LOCALAPPDATA'] = $local
  $p = [System.Diagnostics.Process]::Start($psi)
  [void]$p.StandardOutput.ReadLine()  # ready banner
  $p
}
$script:rid = 0
function Rpc($p, [string]$method, $params = @{}) {
  $script:rid++
  $req = (@{ id = $script:rid; method = $method; params = $params } | ConvertTo-Json -Compress -Depth 6)
  $p.StandardInput.WriteLine($req); $p.StandardInput.Flush()
  $p.StandardOutput.ReadLine() | ConvertFrom-Json
}
function State($p) { (Rpc $p 'startup_state').result }

# ------------------------------------------------------------------ environment
$wv = Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction SilentlyContinue
$result.env = [ordered]@{ os = (Get-CimInstance Win32_OperatingSystem).Caption; build = (Get-CimInstance Win32_OperatingSystem).Version; webview2 = $wv.pv
  user = $env:USERNAME; hasM365Account = [bool](Get-ChildItem 'HKCU:\Software\Microsoft\IdentityCRL\StoredIdentities' -ErrorAction SilentlyContinue) }
Log "env: $($result.env | ConvertTo-Json -Compress)"

# ------------------------------------------------------------------ B) network
function Net-Sampler([int]$seconds, [string]$tag, [hashtable]$seen) {
  $end = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $end) {
    $procs = @{}; Get-CimInstance Win32_Process | ForEach-Object { $procs[[int]$_.ProcessId] = $_ }
    $now = Get-Date -Format 'HH:mm:ss'
    foreach ($c in (Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
      if ($c.RemoteAddress -in '0.0.0.0', '::', '127.0.0.1', '::1' -or $c.State -eq 'Listen') { continue }
      $k = "$($c.OwningProcess)|tcp|$($c.LocalAddress):$($c.LocalPort)|$($c.RemoteAddress):$($c.RemotePort)|$($c.State)"
      if (-not $seen.ContainsKey($k)) {
        $pr = $procs[[int]$c.OwningProcess]
        $seen[$k] = [ordered]@{ tag = $tag; at = $now; pid = $c.OwningProcess; proc = $pr.Name; family = $(if ($c.RemoteAddress -like '*:*') { 'IPv6' } else { 'IPv4' })
          remote = "$($c.RemoteAddress):$($c.RemotePort)"; state = "$($c.State)"; procStart = $pr.CreationDate; ppid = $pr.ParentProcessId
          cmd = $(if ($pr.CommandLine) { $pr.CommandLine.Substring(0, [Math]::Min(260, $pr.CommandLine.Length)) } else { '' }) }
      }
    }
    Start-Sleep -Milliseconds 700
  }
}
if ($Mode -eq 'full' -and $Phase -ne 'session') {
  Log 'network: starting ETW + pktmon'
  logman create trace pvtcp -p "Microsoft-Windows-TCPIP" 0xFFFFFFFFFFFFFFFF 5 -o C:\out\tcpip.etl -ets | Out-Null
  logman create trace pvdns -p "Microsoft-Windows-DNS-Client" 0xFFFFFFFFFFFFFFFF 5 -o C:\out\dns.etl -ets | Out-Null
  pktmon filter remove | Out-Null; pktmon start --capture --pkt-size 128 --file-name C:\out\pktmon.etl | Out-Null
  $seenBase = @{}; $seenApp = @{}
  # positive control: a deliberate outbound SYN to TEST-NET-1 (never answers) 20 s into the baseline period
  $ctl = Start-Job { Start-Sleep 20; Test-NetConnection -ComputerName 192.0.2.1 -Port 443 -WarningAction SilentlyContinue | Out-Null }
  Net-Sampler $BaselineSec 'baseline-no-app' $seenBase
  Log "network baseline done: $($seenBase.Count) distinct non-loopback sockets"
  $local = 'C:\pv-local'; New-Item -ItemType Directory -Force $local | Out-Null
  $env:WEBVIEW2_USER_DATA_FOLDER = "$local\wv"; $env:LOCALAPPDATA = $local
  $app = Start-Process "$CAND\PersonalVault.exe" -PassThru
  $appStart = Get-Date
  Start-Sleep 5
  Net-Sampler $AppSec 'app-running' $seenApp
  Log "network app period done: $($seenApp.Count) distinct non-loopback sockets"
  $tree = @(); $all = Get-CimInstance Win32_Process
  $ids = New-Object 'System.Collections.Generic.HashSet[int]'; [void]$ids.Add([int]$app.Id)
  do { $n = $ids.Count; foreach ($p in $all) { if ($ids.Contains([int]$p.ParentProcessId)) { [void]$ids.Add([int]$p.ProcessId) } } } while ($ids.Count -ne $n)
  foreach ($p in ($all | Where-Object { $ids.Contains([int]$_.ProcessId) })) {
    $tree += [ordered]@{ pid = $p.ProcessId; ppid = $p.ParentProcessId; name = $p.Name; start = $p.CreationDate; cmd = $(if ($p.CommandLine) { $p.CommandLine.Substring(0, [Math]::Min(700, $p.CommandLine.Length)) } else { '' }) }
  }
  $result.network = [ordered]@{ baselineSec = $BaselineSec; appSec = $AppSec; appPid = $app.Id; appStartedAt = $appStart.ToString('o')
    appTreePids = @($ids); tree = $tree
    positiveControlSeenInBaseline = [bool]($seenBase.Values | Where-Object { $_.remote -like '192.0.2.1:*' })
    baselineSockets = @($seenBase.Values); appPeriodSockets = @($seenApp.Values) }
  Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
  Get-Process msedgewebview2, pvault-sidecar -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  logman stop pvtcp -ets | Out-Null; logman stop pvdns -ets | Out-Null; pktmon stop | Out-Null
  tracerpt C:\out\tcpip.etl -of CSV -o C:\out\tcpip.csv -y | Out-Null
  tracerpt C:\out\dns.etl -of CSV -o C:\out\dns.csv -y | Out-Null
  pktmon etl2txt C:\out\pktmon.etl -o C:\out\pktmon.txt | Out-Null
  Log 'network: traces converted'
}

# ------------------------------------------------------------------ A) session: standalone sidecar EXE
$sc = Join-Path $CAND 'pvault-sidecar.exe'
$sess = [ordered]@{}
if ($Phase -eq 'network') { $result.finishedUtc = (Get-Date).ToUniversalTime().ToString('o'); $result | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $OUT 'qa_result.json') -Encoding UTF8; 'done' | Set-Content (Join-Path $OUT 'done.txt'); if ($Mode -eq 'full') { Start-Sleep 3; shutdown /s /t 0 }; exit }
$p = Start-Sidecar $sc (Join-Path $env:TEMP 'pv-sess')
$od = Rpc $p 'open_demo'
$sess.openDemoResponse = ($od | ConvertTo-Json -Compress -Depth 4)
$st0 = State $p
if ($st0.state -ne 'unlocked') { Start-Sleep 2; $sess.openDemoRetry = ((Rpc $p 'open_demo') | ConvertTo-Json -Compress -Depth 4); $st0 = State $p }
$sess.preconditionUnlockedAtStart = ($st0.state -eq 'unlocked')
$sess.initial = [ordered]@{ state = $st0.state; generation = $st0.generation; inputDesktopOpen = (InputDesktopOpen) }
Start-Sleep 5
$sess.controlNoEventAfter5s = (State $p).state   # must still be 'unlocked' (no false lock)

# suspend/resume path: the watcher treats a wall-clock jump larger than 15 s between its 1 s ticks as suspend/resume
if ($Mode -eq 'full') {
  $sess.preconditionBeforeClockTests = (State $p).state              # MUST be 'unlocked' or the clock tests below prove nothing
  Set-Date -Adjust ([TimeSpan]::FromSeconds(5)) | Out-Null; Start-Sleep 3
  $sess.smallClockJump5s = (State $p).state                           # must stay 'unlocked'
  Set-Date -Adjust ([TimeSpan]::FromSeconds(60)) | Out-Null           # simulated resume after sleep
  $t0 = Get-Date; $after = $null
  for ($i = 0; $i -lt 15; $i++) { Start-Sleep 1; $after = State $p; if ($after.state -ne 'unlocked') { break } }
  $sess.largeClockJump60s = [ordered]@{ stateAfter = $after.state; secondsUntilLocked = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
  $err = (Rpc $p 'chat_search' @{ query = 'etap' }).error
  $sess.largeClockJump60s.dataCallAfterLock = $err
  Set-Date -Adjust ([TimeSpan]::FromSeconds(-65)) | Out-Null
  [void](Rpc $p 'open_demo'); Start-Sleep 3
  $sess.reopenedForLockTest = (State $p).state
  $sess.preconditionBeforeRealLock = ($sess.reopenedForLockTest -eq 'unlocked')
}
$result.session = $sess
$result | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $OUT 'qa_result_partial.json') -Encoding UTF8

# REAL session lock (inside the sandbox only)
if ($Mode -eq 'full') {
  Log 'locking the SANDBOX session with LockWorkStation'
  $before = InputDesktopOpen
  Start-Process rundll32.exe -ArgumentList 'user32.dll,LockWorkStation'
  $t0 = Get-Date; $stateAfter = $null; $inputDuringLock = $null
  for ($i = 0; $i -lt 30; $i++) { Start-Sleep 1; $inputDuringLock = InputDesktopOpen; $stateAfter = State $p; if ($stateAfter.state -ne 'unlocked') { break } }
  $sess.realLock = [ordered]@{ inputDesktopOpenBefore = $before; inputDesktopOpenWhileLocked = $inputDuringLock; stateAfter = $stateAfter.state
    secondsUntilLocked = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1); dataCallAfterLock = (Rpc $p 'chat_search' @{ query = 'etap' }).error }
  Log "real lock: $($sess.realLock | ConvertTo-Json -Compress)"
}
try { $p.Kill() } catch {}
$result.session = $sess
$result.finishedUtc = (Get-Date).ToUniversalTime().ToString('o')
$result | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $OUT 'qa_result.json') -Encoding UTF8
'done' | Set-Content (Join-Path $OUT 'done.txt')
if ($Mode -eq 'full') { Start-Sleep 3; shutdown /s /t 0 }
