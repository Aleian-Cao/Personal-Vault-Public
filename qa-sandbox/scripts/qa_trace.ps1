# QA inside Windows Sandbox (disposable VM, the account is an administrator HERE; nothing touches the host). SYNTHETIC ONLY.
# Purpose: exercise what cannot be tested without admin: the real ETW lifecycle (logman/tracerpt), the real ACL/owner checks and refusals of
# net_trace_host_scoped.ps1, and the full 5-window protocol with the harness (short windows). Evidence goes to C:\out.
$ErrorActionPreference = 'Continue'
$OUT = 'C:\out'; New-Item -ItemType Directory -Force $OUT | Out-Null
$ps51 = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$log = Join-Path $OUT 'qa_trace_log.txt'
function Log($m) { "$(Get-Date -Format 'HH:mm:ss.fff') $m" | Tee-Object -FilePath $log -Append | Out-Null }
$result = [ordered]@{ startedUtc = (Get-Date).ToUniversalTime().ToString('o') }
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$result.env = [ordered]@{ os = (Get-CimInstance Win32_OperatingSystem).Caption; build = (Get-CimInstance Win32_OperatingSystem).Version; user = $env:USERNAME
  sid = $id.User.Value; elevated = ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  enableLUA = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -ErrorAction SilentlyContinue).EnableLUA; webview2 = (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction SilentlyContinue).pv }
Log "env: $($result.env | ConvertTo-Json -Compress)"
function Icacls([string[]]$a) { & (Join-Path $env:SystemRoot 'System32\icacls.exe') @a 2>&1 | Out-String }

# ---- 0. the script's own unit tests and the static regression tests, on the real admin token
$result.selfTest = (& $ps51 -NoProfile -ExecutionPolicy Bypass -File C:\tools\net_trace_host_scoped.ps1 -ExpectedSha256 X -RootExe x -Out x -SelfTest 2>&1 | Out-String)
$result.staticTests = (& $ps51 -NoProfile -ExecutionPolicy Bypass -File C:\tools\net_trace_tests.ps1 -Script C:\tools\net_trace_host_scoped.ps1 -Harness C:\e2e\net_trace_harness.ps1 2>&1 | Out-String)
Log 'selftest + static tests done'

# ---- 1. trusted root + staging, exactly as the Owner's checklist does it
$base = 'C:\ProgramData\PVTrace'
New-Item -ItemType Directory $base | Out-Null
Icacls @($base, '/inheritance:r', '/grant:r', '*S-1-5-32-544:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F') | Out-Null; Icacls @($base, '/setowner', '*S-1-5-32-544') | Out-Null
$stage = Join-Path $base 'staging'; New-Item -ItemType Directory $stage | Out-Null
Icacls @($stage, '/inheritance:r', '/grant:r', '*S-1-5-32-544:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F') | Out-Null; Icacls @($stage, '/setowner', '*S-1-5-32-544') | Out-Null
Copy-Item C:\tools\net_trace_host_scoped.ps1 $stage
$script = Join-Path $stage 'net_trace_host_scoped.ps1'
$hash = (Get-FileHash $script -Algorithm SHA256).Hash
$result.scriptSha256 = $hash
$protocol = Join-Path $env:USERPROFILE 'trace-protocol'
$pre = & $ps51 -NoProfile -ExecutionPolicy Bypass -File C:\e2e\net_trace_harness.ps1 -Candidate C:\cand -Control C:\ctl\control_webview2_host.exe -Out $protocol -Preflight 2>&1 | Out-String
$result.harnessPreflight = ($pre -split "`n" | Select-Object -Last 6) -join "`n"
$result.protocolAcl = Icacls @($protocol)
$exeList = 'C:\cand\PersonalVault.exe,C:\ctl\control_webview2_host.exe'

# ---- 2. refusals on a real admin token (each must exit non-zero BEFORE any capture, with the expected reason)
$neg = @()
function Refuse([string]$name, [string]$rx, [string[]]$a, [string]$runner = $script, [bool]$noProfile = $true) {
  $pre = @(if ($noProfile) { '-NoProfile' })   # @() keeps it an array: a bare string would be splatted character by character
  $o = (& $ps51 @pre -ExecutionPolicy Bypass -File $runner @a 2>&1 | Out-String); $code = $LASTEXITCODE
  $ok = ($code -ne 0) -and ($o -match $rx)
  $script:neg += [ordered]@{ case = $name; refused = ($code -ne 0); reasonMatches = [bool]($o -match $rx); pass = $ok; exit = $code; output = (($o -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 3) -join ' | ') }
  Log "refusal [$name] pass=$ok exit=$code"
}
$common = @('-ExpectedSha256', $hash, '-RootExe', $exeList, '-Out', $protocol)
Refuse 'wrong -ExpectedSha256' 'differs from -ExpectedSha256' @('-ExpectedSha256', 'AAAA', '-RootExe', $exeList, '-Out', $protocol)
Refuse 'no -NoProfile' 'NoProfile' $common $script $false
$bad = Join-Path $base 'stg-inherit'; New-Item -ItemType Directory $bad | Out-Null; Copy-Item C:\tools\net_trace_host_scoped.ps1 $bad
Refuse 'staging folder inherits its DACL (AreAccessRulesProtected = False)' 'not a trusted staging folder' $common (Join-Path $bad 'net_trace_host_scoped.ps1')
$usersw = Join-Path $base 'stg-users'; New-Item -ItemType Directory $usersw | Out-Null; Icacls @($usersw, '/inheritance:r', '/grant:r', '*S-1-5-32-544:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-545:(OI)(CI)M') | Out-Null; Copy-Item C:\tools\net_trace_host_scoped.ps1 $usersw
Refuse 'staging folder writable by Users' 'not a trusted staging folder' $common (Join-Path $usersw 'net_trace_host_scoped.ps1')
$badRoot = 'C:\ProgramData\PVTraceBad'; New-Item -ItemType Directory $badRoot | Out-Null; Icacls @($badRoot, '/grant', '*S-1-5-32-545:(OI)(CI)M') | Out-Null
Refuse '-Root pre-created with Users:Modify' 'not trusted|not protected|has access' ($common + @('-Root', $badRoot))
$r2 = 'C:\ProgramData\PVTrace2'; New-Item -ItemType Directory $r2 | Out-Null; Icacls @($r2, '/inheritance:r', '/grant:r', '*S-1-5-32-544:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F') | Out-Null; Icacls @($r2, '/setowner', '*S-1-5-32-544') | Out-Null
New-Item -ItemType Directory (Join-Path $r2 'raw') | Out-Null   # created the lazy way: inherits instead of being protected
Refuse 'raw\ pre-created without a protected DACL' 'not protected|not trusted' ($common + @('-Root', $r2))
$real = Join-Path $env:USERPROFILE 'jreal'; New-Item -ItemType Directory $real | Out-Null; $junc = Join-Path $env:USERPROFILE 'jout'; New-Item -ItemType Junction -Path $junc -Target $real | Out-Null
Refuse '-Out is a junction' 'junction' @('-ExpectedSha256', $hash, '-RootExe', $exeList, '-Out', $junc)
$wo = Join-Path $env:USERPROFILE 'out-usersw'; New-Item -ItemType Directory $wo | Out-Null; Icacls @($wo, '/grant', '*S-1-5-32-545:(OI)(CI)M') | Out-Null
Refuse '-Out grants write to Users' 'grants write access|owned by' @('-ExpectedSha256', $hash, '-RootExe', $exeList, '-Out', $wo)
Refuse '-ReaderSid is Everyone' 'account SID' ($common + @('-ReaderSid', 'S-1-1-0'))
$result.refusals = $neg
$result.refusalsPassed = @($neg | Where-Object { $_.pass }).Count; $result.refusalsTotal = $neg.Count
$result.leftoverAfterRefusals = (Get-ChildItem (Join-Path $base 'raw') -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -join ','

# ---- 2b. can the control host start on this clean image at all? (it must not depend on the VC++ redistributable)
try {
  $cpsi = [System.Diagnostics.ProcessStartInfo]::new('C:\ctl\control_webview2_host.exe'); $cpsi.UseShellExecute = $false
  $cpsi.Environment['CONTROL_PROFILE'] = (Join-Path $env:TEMP 'ctlprobe'); $cpsi.Environment['CONTROL_ARGS'] = ''; $cpsi.Environment['LOCALAPPDATA'] = (Join-Path $env:TEMP 'ctlprobe\local')
  New-Item -ItemType Directory -Force (Join-Path $env:TEMP 'ctlprobe\local') | Out-Null
  $cp = [System.Diagnostics.Process]::Start($cpsi); Start-Sleep -Seconds 10
  $result.controlHostStartsOnCleanImage = (-not $cp.HasExited)
  if ($cp.HasExited) { $result.controlHostExitCode = ('0x{0:X8}' -f $cp.ExitCode) } else { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $cp.Id /T /F 2>&1 | Out-Null }
} catch { $result.controlHostStartsOnCleanImage = "error: $_" }
Log "control host starts on clean image: $($result.controlHostStartsOnCleanImage) $($result.controlHostExitCode)"

# ---- 3. the real run: elevated script + harness, 5 windows of 25 s on real ETW
$spArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script, '-ExpectedSha256', $hash, '-RootExe', $exeList, '-Out', $protocol, '-MinWindowSeconds', '20', '-MaxSeconds', '900')
$sp = Start-Process -FilePath $ps51 -ArgumentList $spArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $OUT 'script_stdout.txt') -RedirectStandardError (Join-Path $OUT 'script_stderr.txt')
Start-Sleep -Seconds 5
$result.sessionsWhileIdle = (& (Join-Path $env:SystemRoot 'System32\logman.exe') query -ets 2>&1 | Out-String)
if ($sp.HasExited) { $result.scriptDiedEarly = $true; $h = 'harness skipped: the elevated script exited before it could capture'; $harnessExit = -1 }
else {
  $h = & $ps51 -NoProfile -ExecutionPolicy Bypass -File C:\e2e\net_trace_harness.ps1 -Candidate C:\cand -Control C:\ctl\control_webview2_host.exe -Out $protocol -WindowSeconds 25 -MinSeconds 20 2>&1 | Out-String
  $harnessExit = $LASTEXITCODE
}
Set-Content (Join-Path $OUT 'harness_stdout.txt') $h
if (-not $sp.WaitForExit(240000)) { $sp.Kill(); $result.scriptTimedOut = $true }
$result.harnessExit = $harnessExit; $result.scriptExit = $sp.ExitCode
$rep = Get-ChildItem (Join-Path $base 'reports') -Directory | Select-Object -First 1
$result.reportFolder = $rep.Name
if ($rep) { Copy-Item $rep.FullName (Join-Path $OUT 'report') -Recurse; $result.runInfo = Get-Content (Join-Path $rep.FullName 'run_info.json') -Raw | ConvertFrom-Json }
$result.sessionsAfter = (& (Join-Path $env:SystemRoot 'System32\logman.exe') query -ets 2>&1 | Out-String) -split "`n" | Where-Object { $_ -match 'pvtr' }
$rawRun = Get-ChildItem (Join-Path $base 'raw') -Directory | Select-Object -First 1
$result.rawFolder = [ordered]@{ name = $rawRun.Name; acl = (Icacls @($rawRun.FullName)); files = (Get-ChildItem $rawRun.FullName | Select-Object Name, Length | ForEach-Object { "$($_.Name) $($_.Length)" }); retention = (Get-Content (Join-Path $rawRun.FullName 'RETENTION.txt') -ErrorAction SilentlyContinue) }
$result.reportAcl = Icacls @($rep.FullName); $result.rootAcl = Icacls @($base); $result.rawBaseAcl = Icacls @((Join-Path $base 'raw'))
$result.reportFiles = (Get-ChildItem $rep.FullName | ForEach-Object { "$($_.Name) $($_.Length)" })

# ---- 4. a standard user must not read raw or write the protocol folder (ACL effect, not just ACL text). Partial result first: nothing below may hang the run.
$result | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $OUT 'qa_trace_result_partial.json') -Encoding UTF8
try {
  $upw = 'Pvtest-Synthetic-1!'
  New-LocalUser -Name pvtest -Password (ConvertTo-SecureString $upw -AsPlainText -Force) -ErrorAction Stop | Out-Null
  $probe = "try { Get-ChildItem -LiteralPath '$($rawRun.FullName)' -ErrorAction Stop | Out-Null; 'RAW-READ-ALLOWED' } catch { 'raw denied' }; try { 'x' | Set-Content -LiteralPath '$protocol\planted.txt' -ErrorAction Stop; 'PROTOCOL-WRITE-ALLOWED' } catch { 'protocol write denied' }; try { Get-ChildItem -LiteralPath '$($rep.FullName)' -ErrorAction Stop | Out-Null; 'REPORT-READ-ALLOWED' } catch { 'report denied' }"
  $psi = [System.Diagnostics.ProcessStartInfo]::new($ps51)
  $psi.Arguments = '-NoProfile -NonInteractive -Command "' + $probe.Replace('"', '\"') + '"'
  $psi.UserName = 'pvtest'; $psi.Domain = '.'; $psi.Password = (ConvertTo-SecureString $upw -AsPlainText -Force); $psi.LoadUserProfile = $false
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true; $psi.WorkingDirectory = $env:SystemRoot
  $pp = [System.Diagnostics.Process]::Start($psi)
  if ($pp.WaitForExit(45000)) { $result.standardUserProbe = ($pp.StandardOutput.ReadToEnd().Trim() -replace "\r?\n", ' | '); $result.standardUserErr = $pp.StandardError.ReadToEnd().Trim() }
  else { try { $pp.Kill() } catch { }; $result.standardUserProbe = 'inconclusive: the probe did not finish in 45 s' }
} catch { $result.standardUserProbe = "inconclusive: $_" }

$result.finishedUtc = (Get-Date).ToUniversalTime().ToString('o')
$result | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $OUT 'qa_trace_result.json') -Encoding UTF8
'done' | Set-Content (Join-Path $OUT 'done.txt')
Start-Sleep 3; shutdown /s /t 0
