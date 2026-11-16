# Personal Vault - harness for the host-scoped network trace (QA, SYNTHETIC vault only). Revision R4 = v3 + the 6 findings of the Manager's source audit.
# Runs next to tools\net_trace_host_scoped.ps1 (which the Owner runs elevated). This script never elevates, never touches ETW/firewall/policy, never stops a process it
# did not start, and writes ONLY inside its own protocol folder (-Out). NOTE: on a host with UAC disabled every process of the account is already an administrator
# process; the trust boundary then only protects against OTHER accounts, and nothing here relies on being "non-elevated".
#
# Five independent windows, each >= 180 s, each with a fresh launch, a throw-away profile and its OWN child environment (nothing is set on this process):
#   W1-locked, W2-unlocked, W3-transition (locked -> unlock -> idle -> lock), W4-control-C1 (independent WebView2 host, app flags), W5-control-C2 (runtime defaults)
# Protocol with the elevated script (files in -Out): <label>.start -> wait until its capture sessions exist -> window -> <label>.end -> wait until they are gone;
# finally markers.jsonl and scenario_done.flag. A window is only recorded as verified when its state (UI Automation), its browser profile (--user-data-dir of the
# browser process is the window's own profile, no other window's) and its effective browser flags (app flags present for W1-W4, absent for W5) were checked.
# Usage:  powershell.exe -NoProfile -File net_trace_harness.ps1 -Candidate <dir with PersonalVault.exe, pvault-sidecar.exe, SHA256SUMS.txt> -Control <control_webview2_host.exe> -Out <new folder>
#   -Preflight : checks only (hashes, paths, reparse points, ACL, leftovers, marker self-test); creates -Out with a locked ACL
#   -Rehearse  : the five windows with short durations and no trace; flags and markers go to -Out\rehearsal
#   -Windows   : subset (for the single extra DNS window), e.g. -Windows W2-unlocked
param(
  [Parameter(Mandatory)][string]$Candidate,
  [Parameter(Mandatory)][string]$Control,
  [Parameter(Mandatory)][string]$Out,
  [ValidateSet('W1-locked', 'W2-unlocked', 'W3-transition', 'W4-control-C1', 'W5-control-C2')][string[]]$Windows = @('W1-locked', 'W2-unlocked', 'W3-transition', 'W4-control-C1', 'W5-control-C2'),
  [string]$ExpectedExeSha256 = '11BF75A6842A879BA952F72B35E4FC37D768F0106D3DD72EF315637EDDABE745',       # PV-20261113-76AC0251-closure3
  [string]$ExpectedSidecarSha256 = '81360E27D7C483E44A2D20A7A5B9BA983E0EFF1559346E0D141F716E373CA842',
  [string]$ExpectedControlSha256 = 'AD7AC6D64479D4DD14DEF092D609766BE9EC4637542364A02168AF96D338FB0E',   # control_webview2_host R4: C2 = real runtime defaults, static CRT (starts on a clean Windows)
  [int]$WindowSeconds = 185, [int]$MinSeconds = 180,
  [switch]$Preflight, [switch]$Rehearse
)
$ErrorActionPreference = 'Stop'
$AppFlags = '--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection,StorageServiceOutOfProcess --disable-background-networking --disable-component-update --disable-domain-reliability --disable-sync --no-pings --disable-breakpad --disable-gpu --renderer-process-limit=1 --enable-features=NetworkServiceInProcess2 --no-proxy-server'
$AppOnlySwitches = @('disable-background-networking', 'disable-component-update', 'disable-domain-reliability', 'disable-sync', 'no-pings', 'disable-breakpad', 'disable-gpu', 'renderer-process-limit', 'no-proxy-server', 'disable-features', 'enable-features', 'autoplay-policy')   # a runtime-default host (C2) must not carry these: neither ours nor the ones wry would inject
$PW = 'Synthetic-Trace-Passphrase-1!'
$AllLabels = 'W1-locked', 'W2-unlocked', 'W3-transition', 'W4-control-C1', 'W5-control-C2'
$MarkerKeys = @('label', 'startUtc', 'endUtc', 'stateVerified', 'profileVerified', 'flagsVerified', 'note')
if ($Rehearse) { $WindowSeconds = [Math]::Min($WindowSeconds, 25); $MinSeconds = [Math]::Min($MinSeconds, 20) }
$SysDir = [Environment]::SystemDirectory; $Logman = Join-Path $SysDir 'logman.exe'
$logLines = New-Object System.Collections.Generic.List[string]
function Say($m) { $l = "$([DateTime]::UtcNow.ToString('o')) $m"; $logLines.Add($l); Write-Host $l }
function Iso([DateTime]$d) { $d.ToUniversalTime().ToString('o') }
function Sha([string]$p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash }
$envBefore = @{}; foreach ($k in 'LOCALAPPDATA', 'WEBVIEW2_USER_DATA_FOLDER', 'CONTROL_ARGS', 'CONTROL_PROFILE') { $envBefore[$k] = [Environment]::GetEnvironmentVariable($k, 'Process') }
function Assert-EnvUnchanged { foreach ($k in $envBefore.Keys) { if ([Environment]::GetEnvironmentVariable($k, 'Process') -ne $envBefore[$k]) { throw "harness process environment variable $k was modified (children must get their own environment)" } } }

# ---------------------------------------------------------------- path / ACL / reparse checks
function Test-NotReparse([string]$path) {
  $p = [IO.Path]::GetFullPath($path)
  while ($p) {
    if (Test-Path -LiteralPath $p) { if ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false } }
    $parent = Split-Path $p -Parent
    if (-not $parent -or $parent -eq $p) { break }
    $p = $parent
  }
  return $true
}
function Test-NoBroadWrite([string]$path) {   # nobody but me / Administrators / SYSTEM may have write-type access to the protocol folder
  $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $ok = @($me, 'S-1-5-32-544', 'S-1-5-18')
  foreach ($r in (Get-Acl -LiteralPath $path).Access) {
    if ($r.AccessControlType -ne 'Allow') { continue }
    $sid = $r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($sid -in $ok) { continue }
    if (([int]$r.FileSystemRights -band (0x10000000 -bor 0x40000000 -bor 0x80000 -bor 0x40000 -bor 0x10000 -bor 0x40 -bor 0x4 -bor 0x2)) -ne 0) { return $false }
  }
  return $true
}

# ---------------------------------------------------------------- marker schema (identical rules to the elevated reader)
function Get-TimeText($v) { if ($v -is [DateTime]) { return $v.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ') } else { return "$v" } }
function Test-Markers([object[]]$rows, [string[]]$labels, [int]$minSeconds) {
  $errs = @()
  if ($rows.Count -ne $labels.Count) { $errs += "expected $($labels.Count) windows, found $($rows.Count)" }
  $prevEnd = $null
  for ($i = 0; $i -lt $rows.Count -and $i -lt $labels.Count; $i++) {
    $r = $rows[$i]; $keys = @($r.PSObject.Properties.Name)
    foreach ($k in $keys) { if ($k -notin $MarkerKeys) { $errs += "window $i has unknown key '$k'" } }
    foreach ($k in $MarkerKeys) { if ($k -notin $keys) { $errs += "window $i misses '$k'" } }
    if ($errs.Count) { continue }
    if ($r.label -ne $labels[$i]) { $errs += "window $i should be $($labels[$i])" }
    foreach ($k in 'stateVerified', 'profileVerified', 'flagsVerified') { if ($r.$k -isnot [bool] -or -not $r.$k) { $errs += "$($r.label).$k must be true" } }
    foreach ($k in 'startUtc', 'endUtc') { if ((Get-TimeText $r.$k) -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?Z$') { $errs += "$($r.label).$k not ISO-8601 UTC ('$($r.$k)')" } }
    if ($errs.Count) { continue }
    $s = [DateTime]::Parse((Get-TimeText $r.startUtc), $null, [Globalization.DateTimeStyles]::AdjustToUniversal); $e = [DateTime]::Parse((Get-TimeText $r.endUtc), $null, [Globalization.DateTimeStyles]::AdjustToUniversal)
    if (($e - $s).TotalSeconds -lt $minSeconds) { $errs += "$($r.label) lasted $([int]($e - $s).TotalSeconds) s < $minSeconds s" }
    if ($prevEnd -and $s -lt $prevEnd) { $errs += "$($r.label) overlaps the previous window" }
    $prevEnd = $e
  }
  return $errs
}

# ---------------------------------------------------------------- pre-flight
$Candidate = (Resolve-Path -LiteralPath $Candidate).Path; $Control = (Resolve-Path -LiteralPath $Control).Path
$exe = Join-Path $Candidate 'PersonalVault.exe'; $sidecar = Join-Path $Candidate 'pvault-sidecar.exe'
foreach ($p in $exe, $sidecar, $Control, $Candidate) { if (-not (Test-NotReparse $p)) { throw "reparse point (junction/symlink) in the path of $p" } }
$sums = @{}; foreach ($l in (Get-Content -LiteralPath (Join-Path $Candidate 'SHA256SUMS.txt'))) { if ($l -match '^([0-9A-Fa-f]{64})\s+\*?(.+)$') { $sums[$Matches[2].Trim()] = $Matches[1].ToUpper() } }
$hashes = [ordered]@{
  shell   = [ordered]@{ actual = (Sha $exe); expectedParam = $ExpectedExeSha256.ToUpper(); expectedSums = $sums['PersonalVault.exe'] }
  sidecar = [ordered]@{ actual = (Sha $sidecar); expectedParam = $ExpectedSidecarSha256.ToUpper(); expectedSums = $sums['pvault-sidecar.exe'] }
  control = [ordered]@{ actual = (Sha $Control); expectedParam = $ExpectedControlSha256.ToUpper(); expectedSums = $null }
}
foreach ($k in $hashes.Keys) {
  $h = $hashes[$k]
  if ($h.actual -ne $h.expectedParam) { throw "$k hash mismatch: $($h.actual) != $($h.expectedParam)" }
  if ($h.expectedSums -and $h.actual -ne $h.expectedSums) { throw "$k hash differs from the candidate's SHA256SUMS.txt" }
  Say "hash OK  $k  $($h.actual)"
}
$busy = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in 'PersonalVault', 'PersonalVault-e2e', 'pvault-sidecar', 'control_webview2_host' }
if ($busy) { throw "leftover processes of the app/control are running (pids $($busy.Id -join ',')): refusing to start" }
if (Test-Path -LiteralPath $Out) { if (-not (Test-Path -LiteralPath $Out -PathType Container)) { throw '-Out is a file' }; if (@(Get-ChildItem -LiteralPath $Out -Force | Where-Object { $_.Name -ne 'harness_preflight_log.txt' }).Count) { throw '-Out must be new or empty (only the preflight log of an earlier -Preflight run is allowed)' } }
else {
  New-Item -ItemType Directory -Path $Out | Out-Null
  $meSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value   # folders under %LOCALAPPDATA%\Temp inherit Modify for other local groups: cut inheritance, keep me + Administrators + SYSTEM
  & (Join-Path $SysDir 'icacls.exe') $Out /inheritance:r /grant:r "*${meSid}:(OI)(CI)F" '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "icacls failed on -Out (exit $LASTEXITCODE)" }
}
$Out = (Resolve-Path -LiteralPath $Out).Path
if (-not (Test-NotReparse $Out)) { throw '-Out (or a parent) is a junction/symlink' }
if (-not (Test-NoBroadWrite $Out)) { throw '-Out ACL gives write access to someone other than me/Administrators/SYSTEM' }
Say "protocol folder OK (real folder, no reparse point, no broad write ACL): $Out"
$t0 = [DateTime]::UtcNow
function Mk($i, $label, $dur) { $s = $t0.AddSeconds($i * 200); [pscustomobject][ordered]@{ label = $label; startUtc = (Iso $s); endUtc = (Iso $s.AddSeconds($dur)); stateVerified = $true; profileVerified = $true; flagsVerified = $true; note = 'x' } }
$good = 0..4 | ForEach-Object { Mk $_ $AllLabels[$_] 185 }
if ((Test-Markers $good $AllLabels 180).Count) { throw 'marker self-test: good set rejected' }
if (-not (Test-Markers @($good[0..3]) $AllLabels 180).Count) { throw 'marker self-test: 4 windows accepted' }
$x = Mk 2 $AllLabels[2] 5; if (-not (Test-Markers @($good[0], $good[1], $x, $good[3], $good[4]) $AllLabels 180).Count) { throw 'marker self-test: short window accepted' }
$x = Mk 0 $AllLabels[1] 185; if (-not (Test-Markers @($good[0], $x, $good[2], $good[3], $good[4]) $AllLabels 180).Count) { throw 'marker self-test: overlap accepted' }
$x = Mk 2 $AllLabels[2] 185; $x.profileVerified = $false; if (-not (Test-Markers @($good[0], $good[1], $x, $good[3], $good[4]) $AllLabels 180).Count) { throw 'marker self-test: unverified profile accepted' }
$x = Mk 0 $AllLabels[0] 185; $x.startUtc = '2026-11-14 10:00:00'; if (-not (Test-Markers @($x, $good[1], $good[2], $good[3], $good[4]) $AllLabels 180).Count) { throw 'marker self-test: non-ISO time accepted' }
Say 'marker schema self-test OK (good accepted; 4 windows / short / overlap / unverified profile / non-ISO rejected)'
if ($Preflight) { $logLines | Set-Content -LiteralPath (Join-Path $Out 'harness_preflight_log.txt') -Encoding UTF8; Say 'preflight OK'; return }

# ---------------------------------------------------------------- child processes: their OWN environment, nothing set on this process (F3)
function New-ChildStartInfo([string]$file, [hashtable]$set, [string[]]$remove) {
  $psi = [System.Diagnostics.ProcessStartInfo]::new($file)
  $psi.UseShellExecute = $false
  foreach ($k in @($psi.Environment.Keys)) { if ($k -match '^(WEBVIEW2_|PVAULT_|CONTROL_)') { [void]$psi.Environment.Remove($k) } }   # nothing that steers WebView2 or the app is inherited, only what is set below
  foreach ($k in $set.Keys) { $psi.Environment[$k] = [string]$set[$k] }
  foreach ($k in $remove) { [void]$psi.Environment.Remove($k) }
  return $psi
}
$procs = New-Object System.Collections.Generic.List[System.Diagnostics.Process]
$usedProfiles = New-Object System.Collections.Generic.List[string]
function Stop-Own([System.Diagnostics.Process]$p) {   # only the tree of a process THIS script started; never throws (Windows PowerShell 5.1 turns native stderr into a terminating error under 'Stop')
  $ErrorActionPreference = 'Continue'
  try { if ($p -and -not $p.HasExited) { & (Join-Path $SysDir 'taskkill.exe') /PID $p.Id /T /F 2>&1 | Out-Null } } catch { }
}
function New-Profile([bool]$withVault) {
  $root = Join-Path ([IO.Path]::GetTempPath()) ('pv-trace-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $local = Join-Path $root 'local'; New-Item -ItemType Directory -Force $local | Out-Null
  if ($withVault) {   # synthetic vault created by the candidate's own sidecar; the sidecar gets its own environment too
    $psi = New-ChildStartInfo $sidecar @{ LOCALAPPDATA = $local } @('WEBVIEW2_USER_DATA_FOLDER', 'CONTROL_ARGS', 'CONTROL_PROFILE')
    $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.CreateNoWindow = $true
    $sc = [System.Diagnostics.Process]::Start($psi); [void]$sc.StandardOutput.ReadLine()
    $rid = 0
    $rpc = { param($m, $p) $script:rid++; $b = [Text.UTF8Encoding]::new($false).GetBytes((@{ id = $script:rid; method = $m; params = $p } | ConvertTo-Json -Compress -Depth 6) + "`n"); $sc.StandardInput.BaseStream.Write($b, 0, $b.Length); $sc.StandardInput.BaseStream.Flush(); $sc.StandardOutput.ReadLine() | ConvertFrom-Json }   # raw UTF-8 bytes: no BOM on any PowerShell edition
    [void](& $rpc 'startup_state' @{})   # primer: Windows PowerShell 5.1 prefixes the child's stdin with a UTF-8 BOM, so the FIRST line is always garbled (JSONDecodeError); the sidecar is fine
    $r1 = & $rpc 'create' @{ path = (Join-Path $root 'trace.pvault'); password = $PW; demo = $false }
    $r2 = & $rpc 'save_entry' @{ entry_data = @{ account = 'Trace Synthetic'; name = 'trace.user'; password = 'CANARY_TRACE_PW' } }
    [void](& $rpc 'lock' @{})
    try { $sc.StandardInput.Close(); if (-not $sc.WaitForExit(3000)) { Stop-Own $sc } } catch { Stop-Own $sc }   # whole tree (the PyInstaller bootloader has a Python child)
    if ($r1.error -or $r2.error) { throw "synthetic vault creation failed: $($r1.error) $($r2.error)" }
  }
  return $local
}
function Start-App([string]$local) {
  $psi = New-ChildStartInfo $exe @{ LOCALAPPDATA = $local; WEBVIEW2_USER_DATA_FOLDER = (Join-Path $local 'wv') } @('CONTROL_ARGS', 'CONTROL_PROFILE')
  $p = [System.Diagnostics.Process]::Start($psi); $procs.Add($p); return $p
}
function Start-Control([string]$profileRoot, [string]$flags) {
  New-Item -ItemType Directory -Force $profileRoot | Out-Null
  $psi = New-ChildStartInfo $Control @{ LOCALAPPDATA = (Join-Path $profileRoot 'local'); CONTROL_PROFILE = $profileRoot; CONTROL_ARGS = $flags } @('WEBVIEW2_USER_DATA_FOLDER')
  New-Item -ItemType Directory -Force (Join-Path $profileRoot 'local') | Out-Null
  $p = [System.Diagnostics.Process]::Start($psi); $procs.Add($p); return $p
}

# ---------------------------------------------------------------- independent profile + effective flags, read from the browser process of THIS window (F3)
function Get-BrowserCmd([int]$rootPid, [int]$seconds = 40) {
  $end = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $end) {
    $all = @(Get-CimInstance Win32_Process)
    $tr = @{ $rootPid = ($all | Where-Object { $_.ProcessId -eq $rootPid } | Select-Object -First 1) }
    if ($tr[$rootPid]) {
      do { $n = $tr.Count
        foreach ($p in $all) { if (-not $tr.ContainsKey([int]$p.ProcessId) -and $tr.ContainsKey([int]$p.ParentProcessId) -and $p.CreationDate -ge $tr[[int]$p.ParentProcessId].CreationDate) { $tr[[int]$p.ProcessId] = $p } }
      } while ($tr.Count -ne $n)
      foreach ($p in $tr.Values) { if ($p.Name -eq 'msedgewebview2.exe' -and $p.CommandLine -and $p.CommandLine -notmatch '--type=') { return $p.CommandLine } }
    }
    Start-Sleep -Milliseconds 700
  }
  return $null
}
function Get-Switches([string]$cmd) {
  $d = @{}
  foreach ($m in [regex]::Matches($cmd, '--([^\s=]+)(?:=(?:"([^"]*)"|(\S*)))?')) { $d[$m.Groups[1].Value] = if ($m.Groups[2].Success) { $m.Groups[2].Value } else { $m.Groups[3].Value } }
  return $d
}
function Test-Isolation([int]$rootPid, [string]$profileRoot, [string]$hostExeName, [bool]$expectAppFlags) {
  $r = [ordered]@{ profileOk = $false; flagsOk = $false; detail = '' }
  $cmd = Get-BrowserCmd $rootPid
  if (-not $cmd) { $r.detail = 'no WebView2 browser process found for this window'; return [pscustomobject]$r }
  $sw = Get-Switches $cmd
  $udd = $sw['user-data-dir']
  $mine = ($udd -and (([IO.Path]::GetFullPath($udd).TrimEnd('\') + '\').StartsWith(([IO.Path]::GetFullPath($profileRoot).TrimEnd('\') + '\'), 'OrdinalIgnoreCase')))
  $others = @($usedProfiles | Where-Object { $_ -ne $profileRoot -and $cmd.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
  $r.profileOk = ($mine -and -not $others.Count -and ($sw['webview-exe-name'] -ieq $hostExeName))
  $missing = @()
  foreach ($tok in $AppFlags.Split(' ')) {
    $m = [regex]::Match($tok, '^--([^=]+)(?:=(.*))?$'); $name = $m.Groups[1].Value; $val = $m.Groups[2].Value
    if ($expectAppFlags) { if (-not $sw.ContainsKey($name) -or ($m.Groups[2].Success -and $sw[$name] -cne $val)) { $missing += $name } }
  }
  $leaked = @(); if (-not $expectAppFlags) { foreach ($n in $AppOnlySwitches) { if ($sw.ContainsKey($n)) { $leaked += $n } } }
  $r.flagsOk = ($expectAppFlags -and -not $missing.Count) -or (-not $expectAppFlags -and -not $leaked.Count)
  $r.detail = "profile $(if ($r.profileOk) { 'own' } else { "NOT own (mine=$mine others=$($others.Count) host=$($sw['webview-exe-name']))" }); flags $(if ($r.flagsOk) { if ($expectAppFlags) { 'app flags all present' } else { 'no app-only flag' } } else { "missing=[$($missing -join ',')] leaked=[$($leaked -join ',')]" })"
  return [pscustomobject]$r
}

# ---------------------------------------------------------------- UI Automation (no keystrokes); Chromium builds the page tree only after a UIA client asks the render widget
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Text; using System.Collections.Generic;
public class HW {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  public static List<IntPtr> Kids(IntPtr parent, string cls) { var r = new List<IntPtr>(); EnumChildWindows(parent, (h, l) => { var sb = new StringBuilder(256); GetClassName(h, sb, 256); if (sb.ToString() == cls) r.Add(h); return true; }, IntPtr.Zero); return r; }
}
"@
function Get-ContentRoot($win) {
  $h = [IntPtr]$win.Current.NativeWindowHandle
  foreach ($x in [HW]::Kids($h, 'Chrome_RenderWidgetHostHWND')) { return [System.Windows.Automation.AutomationElement]::FromHandle($x) }
  return $null
}
function Find-El($win, [string]$name, [string]$type, [int]$seconds = 25) {   # name compared case-insensitively (the page renders 'MASTER PASSWORD')
  $end = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $end) {
    $root = Get-ContentRoot $win
    if ($root) {
      $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::$type)
      foreach ($el in $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)) { if ($el.Current.Name -ieq $name) { return $el } }
    }
    Start-Sleep -Milliseconds 700
  }
  return $null
}
function Get-MainWindow([int]$procId) {
  $end = (Get-Date).AddSeconds(40)
  while ((Get-Date) -lt $end) {
    $c = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $procId)
    $w = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $c)
    if ($w) { return $w }
    Start-Sleep -Milliseconds 400
  }
  return $null
}
function Invoke-UiUnlock($win) {
  $edit = Find-El $win 'Master Password' 'Edit'; if (-not $edit) { return $false }   # NOT named $pw: PowerShell variables are case-insensitive and $PW is the password
  ($edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)).SetValue($PW)
  $b = Find-El $win 'Mở khóa' 'Button' 10; if (-not $b) { return $false }
  ($b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)).Invoke()
  return [bool](Find-El $win 'Câu hỏi' 'Edit' 25)
}
function Invoke-UiLock($win) {
  $b = Find-El $win 'Khóa két sắt' 'Button' 10; if (-not $b) { return $false }
  ($b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)).Invoke()
  return [bool](Find-El $win 'Master Password' 'Edit' 25)
}

# ---------------------------------------------------------------- protocol + window runner
$flagDir = if ($Rehearse) { $d = Join-Path $Out 'rehearsal'; New-Item -ItemType Directory -Force $d | Out-Null; $d } else { $Out }
function Wait-Sessions([int]$n, [bool]$present, [int]$seconds) {   # listing ETW sessions needs no elevation
  $until = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $until) {
    $q = (& $Logman query -ets 2>&1 | Out-String)
    $has = ($q -match "pvtr[0-9a-f]{8}-w$n-tcpip") -and ($q -match "pvtr[0-9a-f]{8}-w$n-kernnet")
    $none = -not ($q -match "pvtr[0-9a-f]{8}-w$n-")
    if (($present -and $has) -or (-not $present -and $none)) { return }
    Start-Sleep -Seconds 1
  }
  throw "capture sessions of window $n did not $(if ($present) { 'appear' } else { 'disappear' }) within $seconds s"
}
function Invoke-Window([int]$n, [string]$label, [scriptblock]$body) {
  Say "=== $label : request capture"
  New-Item -ItemType File -Path (Join-Path $flagDir "$label.start") | Out-Null
  $cur = $null; $res = [ordered]@{ state = $false; profile = $false; flags = $false; note = '' }; $startU = $null; $endU = $null; $procBefore = $procs.Count
  try {
    if (-not $Rehearse) { Wait-Sessions $n $true 300; Start-Sleep -Seconds 2 }   # the script converts the previous window before it starts this one (can take minutes); 2 s grace after the sessions exist
    $startU = [DateTime]::UtcNow
    Say "=== $label : start"
    $r = & $body; $cur = $r.proc; $res.state = [bool]$r.state; $res.profile = [bool]$r.profile; $res.flags = [bool]$r.flags; $res.note = [string]$r.note
    $left = $WindowSeconds - ([DateTime]::UtcNow - $startU).TotalSeconds
    if ($left -gt 0) { Start-Sleep -Milliseconds ([int]($left * 1000)) }
    $endU = [DateTime]::UtcNow
    Assert-EnvUnchanged
  } catch { $res.state = $false; $res.note = "$_"; if (-not $endU) { $endU = [DateTime]::UtcNow }; if (-not $startU) { $startU = $endU.AddSeconds(-1) } }
  finally {
    for ($pi = $procBefore; $pi -lt $procs.Count; $pi++) { Stop-Own $procs[$pi] }   # whatever THIS window started, also when its body threw
    Stop-Own $cur
    try { New-Item -ItemType File -Path (Join-Path $flagDir "$label.end") -Force | Out-Null } catch { $res.state = $false; $res.note += " | could not write .end: $_" }
    if (-not $Rehearse) { try { Wait-Sessions $n $false 180 } catch { $res.state = $false; $res.note += " | $_" } }
  }
  Say "=== $label : end ($([int]($endU - $startU).TotalSeconds) s) state=$($res.state) profile=$($res.profile) flags=$($res.flags) $($res.note)"
  $note = $res.note; if ($note.Length -gt 200) { $note = $note.Substring(0, 200) }
  return [pscustomobject][ordered]@{ label = $label; startUtc = (Iso $startU); endUtc = (Iso $endU); stateVerified = $res.state; profileVerified = $res.profile; flagsVerified = $res.flags; note = $note }
}

$results = @()
try {
  $n = 0
  foreach ($label in $Windows) {
    $n++
    switch ($label) {
      'W1-locked' { $results += Invoke-Window $n $label {
          $local = New-Profile $true; $usedProfiles.Add($local); $p = Start-App $local
          $w = Get-MainWindow $p.Id; if (-not $w) { throw 'no window' }
          $state = [bool](Find-El $w 'Master Password' 'Edit'); $iso = Test-Isolation $p.Id $local 'PersonalVault.exe' $true
          [pscustomobject]@{ proc = $p; state = $state; profile = $iso.profileOk; flags = $iso.flagsOk; note = "unlock screen $(if ($state) { 'shown' } else { 'NOT reached' }); $($iso.detail)" } } }
      'W2-unlocked' { $results += Invoke-Window $n $label {
          $local = New-Profile $true; $usedProfiles.Add($local); $p = Start-App $local
          $w = Get-MainWindow $p.Id; if (-not $w) { throw 'no window' }
          $state = Invoke-UiUnlock $w; $iso = Test-Isolation $p.Id $local 'PersonalVault.exe' $true
          [pscustomobject]@{ proc = $p; state = $state; profile = $iso.profileOk; flags = $iso.flagsOk; note = "unlocked via UI Automation, then idle; $($iso.detail)" } } }
      'W3-transition' { $results += Invoke-Window $n $label {
          $local = New-Profile $true; $usedProfiles.Add($local); $p = Start-App $local
          $w = Get-MainWindow $p.Id; if (-not $w) { throw 'no window' }
          $s1 = [bool](Find-El $w 'Master Password' 'Edit'); $iso = Test-Isolation $p.Id $local 'PersonalVault.exe' $true
          $third = [Math]::Max(5, [int](($WindowSeconds - 20) / 3))
          Start-Sleep -Seconds $third; $s2 = Invoke-UiUnlock $w
          Start-Sleep -Seconds $third; $s3 = Invoke-UiLock $w
          [pscustomobject]@{ proc = $p; state = ($s1 -and $s2 -and $s3); profile = $iso.profileOk; flags = $iso.flagsOk; note = "locked $third s -> unlocked $third s -> locked rest; $($iso.detail)" } } }
      'W4-control-C1' { $results += Invoke-Window $n $label {
          $prof = Join-Path ([IO.Path]::GetTempPath()) ('pv-ctl-' + [guid]::NewGuid().ToString('N').Substring(0, 8)); $usedProfiles.Add($prof)
          $p = Start-Control $prof $AppFlags; Start-Sleep -Seconds 8
          $kids = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $p.Id }).Count; $iso = Test-Isolation $p.Id $prof 'control_webview2_host.exe' $true
          [pscustomobject]@{ proc = $p; state = ($kids -ge 1); profile = $iso.profileOk; flags = $iso.flagsOk; note = "control tree: $kids direct children; $($iso.detail)" } } }
      'W5-control-C2' { $results += Invoke-Window $n $label {
          $prof = Join-Path ([IO.Path]::GetTempPath()) ('pv-ctl-' + [guid]::NewGuid().ToString('N').Substring(0, 8)); $usedProfiles.Add($prof)
          $p = Start-Control $prof ''; Start-Sleep -Seconds 8
          $kids = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $p.Id }).Count; $iso = Test-Isolation $p.Id $prof 'control_webview2_host.exe' $false
          [pscustomobject]@{ proc = $p; state = ($kids -ge 1); profile = $iso.profileOk; flags = $iso.flagsOk; note = "control tree: $kids direct children; $($iso.detail)" } } }
    }
    Start-Sleep -Seconds 3
  }
}
finally {
  foreach ($p in $procs) { Stop-Own $p }
}
$errs = @(Test-Markers $results $Windows $MinSeconds)
if (@($usedProfiles | Select-Object -Unique).Count -ne $usedProfiles.Count) { $errs += 'two windows shared a profile' }
$results | ForEach-Object { $_ | ConvertTo-Json -Compress } | Set-Content -LiteralPath (Join-Path $flagDir 'markers.jsonl') -Encoding UTF8
$logLines | Set-Content -LiteralPath (Join-Path $flagDir 'harness_log.txt') -Encoding UTF8
if ($errs.Count) { Say "NOT COMPLETE: $($errs -join ' | ')"; if (-not $Rehearse) { New-Item -ItemType File -Path (Join-Path $Out 'abort.flag') | Out-Null }; exit 2 }
if (-not $Rehearse) { New-Item -ItemType File -Path (Join-Path $Out 'scenario_done.flag') | Out-Null }
Say "all $($results.Count) windows complete and verified (state, own profile, effective flags)$(if ($Rehearse) { ' - rehearsal: no flag written' })"
