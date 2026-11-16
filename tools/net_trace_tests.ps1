# Regression tests for the 6 findings of the Manager's source audit (F1..F6). Non-elevated, SYNTHETIC only, no ETW.
# Usage: powershell.exe -NoProfile -File net_trace_tests.ps1 -Script <net_trace_host_scoped.ps1> -Harness <net_trace_harness.ps1> [-Dynamic]
# Static tests read the sources; dynamic tests drive the script with -DryRun (synthetic ETL/CSV) and a simulated harness writing the real protocol files.
# The same file is run against the audited v3 files (expected: RED for every finding) and against revision R4 (expected: all GREEN).
param([Parameter(Mandatory)][string]$Script, [Parameter(Mandatory)][string]$Harness, [switch]$Dynamic, [switch]$SkipFullDynamic)
$ErrorActionPreference = 'Stop'
$ps51 = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$res = New-Object System.Collections.Generic.List[object]
function T([string]$id, [string]$name, [bool]$ok, [string]$why = '') { $res.Add([pscustomobject]@{ id = $id; test = $name; pass = $ok; detail = $why }); Write-Host ("{0}  [{1}] {2}{3}" -f ($(if ($ok) { 'PASS' } else { 'FAIL' })), $id, $name, $(if (-not $ok -and $why) { "  -> $why" } else { '' })) }

# ---------------------------------------------------------------- helpers
$sTxt = [IO.File]::ReadAllText($Script); $hTxt = [IO.File]::ReadAllText($Harness)
function Get-Production([string]$t, [bool]$blankStrings) {   # drop the -SelfTest block (column-0 'if ($SelfTest) {' .. column-0 '}'), comment lines, trailing comments; optionally blank string literals
  $t = [regex]::Replace($t, '(?ms)^if \(\$SelfTest\) \{.*?^\}\r?$', '')
  $lines = foreach ($l in ($t -split "`r?`n")) {
    if ($l.TrimStart().StartsWith('#')) { continue }
    $l = [regex]::Replace($l, '\s+#.*$', '')
    if ($blankStrings) { $l = [regex]::Replace($l, '"(?:[^"`]|`.)*"', '""'); $l = [regex]::Replace($l, "'[^']*'", "''") }
    $l
  }
  return ($lines -join "`n")
}
$sProd = Get-Production $sTxt $false; $hProd = Get-Production $hTxt $false; $sCode = Get-Production $sTxt $true; $hCode = Get-Production $hTxt $true
$isR4 = ($sTxt -match 'Revision R4')

# ---------------------------------------------------------------- F1 privileged filesystem
T 'F1' 'owner of every privileged folder is verified (GetOwner)' ($sProd -match 'GetOwner\(')
T 'F1' 'ancestors of the trusted roots are verified' ($sProd -match 'Test-AncestorsTrusted')
T 'F1' 'every icacls call goes through the exit-code checking helper' (($sCode -notmatch '(?<![\w$.\\-])icacls\b') -and ($sCode -notmatch '&\s*\$Icacls') -and ($sProd -match 'Invoke-Sys \$Icacls'))
T 'F1' 'no recursive delete outside Remove-OwnedRunDir (which verifies owner/ACL/reparse first)' ((@([regex]::Matches(([regex]::Replace($sCode, '(?ms)^function Remove-OwnedRunDir.*?^\}', '')), '-Recurse')).Count) -eq 0)
T 'F1' 'the report/raw roots are created under a verified admin-only root, not under a user-supplied path' ($sProd -match '\$Root' -and $sProd -notmatch '\[string\]\$Raw\s*=')
T 'F1' 'staging folder must be protected (AreAccessRulesProtected) and owned by a trusted principal' ($sProd -match 'AreAccessRulesProtected' -and $sProd -match "Test-DirTrusted \(Split-Path \`$PSCommandPath\) 'strict'")
T 'F1' 'the elevated script never writes into -Out (user-writable)' ($sProd -notmatch '(?i)(Set-Content|Out-File|WriteAllText|WriteAllLines|StreamWriter[^\r\n]*)\(?[^\r\n]*Join-Path \$Out')

# ---------------------------------------------------------------- F2 trusted executables and PowerShell
$bare = [regex]::Matches($sCode, '(?<![\w$.\\&-])(logman|tracerpt|icacls|pktmon)(?:\.exe)?\b')
T 'F2' 'logman/tracerpt/icacls/pktmon are never invoked by bare name' ($bare.Count -eq 0) ($(if ($bare.Count) { ($bare | Select-Object -First 3 | ForEach-Object { $_.Value }) -join ' | ' }))
T 'F2' 'system tools are absolute System32 paths with a verified Microsoft signature' ($sProd -match 'SystemDirectory' -and $sProd -match 'Get-AuthenticodeSignature')
T 'F2' 'native exit codes are checked' ($sProd -match 'LASTEXITCODE')
T 'F2' 'PSModulePath is reduced to the system modules' ($sProd -match '\$env:PSModulePath\s*=')
T 'F2' 'the elevated run requires -NoProfile and the system Windows PowerShell' ($sProd -match 'NoProfile' -and $sProd -match 'WindowsPowerShell')
T 'F2' 'the harness uses absolute system tools too' ($hCode -notmatch '(?<![\w$.\\&-])(logman|taskkill|icacls)(?:\.exe)?\b')

# ---------------------------------------------------------------- F3 harness environment
$leak = [regex]::Matches($hProd, '\$env:(LOCALAPPDATA|WEBVIEW2_USER_DATA_FOLDER|CONTROL_ARGS|CONTROL_PROFILE)\s*=')
T 'F3' 'the harness never assigns process-wide environment variables' ($leak.Count -eq 0) ($(if ($leak.Count) { "$($leak.Count) assignments of `$env:..." }))
T 'F3' 'children get their own environment (ProcessStartInfo.Environment)' ($hProd -match 'psi\.Environment\[' -or $hProd -match '\.Environment\[\$k\]')
T 'F3' 'children never inherit WEBVIEW2_* / PVAULT_* / CONTROL_* variables' ($hProd -match "\^\(WEBVIEW2_\|PVAULT_\|CONTROL_\)")
T 'F3' 'C2 must carry none of ours nor of the wry-injected switches (disable-features, enable-features, autoplay-policy)' ($hProd -match "'disable-features', 'enable-features', 'autoplay-policy'")
T 'AUDIT' 'Stop-Own never throws and every window writes its .end flag even when its body failed' (($hProd -match '(?s)function Stop-Own.*?ErrorActionPreference = .Continue.') -and ($hProd -match '(?s)finally \{.{0,400}?\.end'))
T 'AUDIT' 'the staged script file itself is verified (owner/ACL/hard links) and inherit-only ACEs are not skipped in strict mode' (($sProd -match 'Test-FileTrusted \$PSCommandPath') -and ($sProd -match "-eq 'ancestor' -and \(\`$r\.PropagationFlags"))
T 'AUDIT' 'lost events are read from the ETL header (EventsLost) and any loss makes the window INCOMPLETE' ($sProd -match 'eventsLost' -and $sProd -match 'lost \$\(\$st\.eventsLost\) events')
T 'AUDIT' 'the evidence is bound to the traced binaries (rootExeSha256) and to a live tracked browser process per window' (($sProd -match 'rootExeSha256') -and ($sProd -match 'BrowserProcessName'))
T 'F3' 'the profile and the effective browser flags are verified for every window' (($hProd -match 'Test-Isolation') -and ($hProd -match 'profileVerified') -and ($hProd -match 'flagsVerified'))

# ---------------------------------------------------------------- F4 one capture per window, no circular overwrite
T 'F4' 'no circular (bincirc) session: each window has its own sequential ETL' ($sProd -notmatch 'bincirc' -and $sProd -match "'-f', 'bin'")
T 'F4' 'the capture is driven per window (<label>.start / <label>.end) and the sessions stop at .end' ($sProd -match '\.start' -and $sProd -match '\.end' -and $sProd -match 'Stop-Capture')
T 'F4' 'the harness waits for the window sessions before it launches anything and for their end afterwards' ($hProd -match 'Wait-Sessions')

# ---------------------------------------------------------------- F5 / F6 at the elevated reader
T 'F5' 'marker schema, order, count, time bounds, overlap, stateVerified and file size are validated at the elevated reader' ($sProd -match 'Test-MarkerFile' -and $sProd -match '16384' -and $sProd -match 'stateVerified')
T 'F6' 'ETL existence/size, CSV schema, event presence, time coverage and PID attribution are verified; failure => INCOMPLETE' ($sProd -match 'Test-CsvHeader' -and $sProd -match 'attribution control' -and $sProd -match 'INCOMPLETE')

# ---------------------------------------------------------------- dynamic: the script in -DryRun against a simulated harness
if ($Dynamic -and $isR4) {
  $hash = (Get-FileHash -LiteralPath $Script -Algorithm SHA256).Hash
  $labels = 'W1-locked', 'W2-unlocked', 'W3-transition', 'W4-control-C1', 'W5-control-C2'
  function Invoke-Scenario([string]$name, [string]$fault, [scriptblock]$mutate, [int]$stopAfter = 5, [bool]$writeDone = $true, [bool]$skipLastEnd = $false, [string]$rootExe = $ps51, [string]$browser = 'powershell.exe') {
    $d = Join-Path ([IO.Path]::GetTempPath()) ('pvtr-t-' + [guid]::NewGuid().ToString('N').Substring(0, 8)); $out = Join-Path $d 'out'; $root = Join-Path $d 'root'; New-Item -ItemType Directory $out | Out-Null
    $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Script, '-ExpectedSha256', $hash, '-RootExe', $rootExe, '-Out', $out, '-Root', $root, '-DryRun', '-DryRunFault', $fault, '-MinWindowSeconds', '2', '-MaxSeconds', '150', '-BrowserProcessName', $browser)
    $p = Start-Process -FilePath $ps51 -ArgumentList $psArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $d 'stdout.txt') -RedirectStandardError (Join-Path $d 'stderr.txt')
    $null = $p.Handle   # keep the handle so ExitCode is available after WaitForExit (Windows PowerShell 5.1)
    Start-Sleep -Seconds 3
    $rows = @()
    for ($i = 0; $i -lt $stopAfter; $i++) {
      $l = $labels[$i]; New-Item -ItemType File -Path (Join-Path $out "$l.start") | Out-Null
      $until = (Get-Date).AddSeconds(25)   # like the real harness: wait until the capture of this window is really running
      while ((Get-Date) -lt $until -and -not ((Get-Content -LiteralPath (Join-Path $d 'stdout.txt') -Raw -ErrorAction SilentlyContinue) -match "capture $l started")) { Start-Sleep -Milliseconds 200 }
      Start-Sleep -Milliseconds 500
      $s = [DateTime]::UtcNow; Start-Sleep -Seconds 3; $e = [DateTime]::UtcNow
      $rows += [ordered]@{ label = $l; startUtc = $s.ToString('o'); endUtc = $e.ToString('o'); stateVerified = $true; profileVerified = $true; flagsVerified = $true; note = 'sim' }
      if (-not ($skipLastEnd -and $i -eq $stopAfter - 1)) { New-Item -ItemType File -Path (Join-Path $out "$l.end") | Out-Null }
      Start-Sleep -Milliseconds 2600
    }
    $lines = if ($mutate) { & $mutate $rows } else { $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } }
    [IO.File]::WriteAllLines((Join-Path $out 'markers.jsonl'), [string[]]$lines)
    if ($writeDone) { New-Item -ItemType File -Path (Join-Path $out 'scenario_done.flag') | Out-Null } else { New-Item -ItemType File -Path (Join-Path $out 'abort.flag') | Out-Null }
    if (-not $p.WaitForExit(90000)) { $p.Kill() }
    $info = $null; $ri = Get-ChildItem -LiteralPath (Join-Path $root 'reports') -Recurse -Filter run_info.json -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ri) { $info = Get-Content -LiteralPath $ri.FullName -Raw | ConvertFrom-Json }
    return [pscustomobject]@{ dir = $d; exit = $p.ExitCode; info = $info; report = $(if ($ri) { Split-Path $ri.FullName -Parent }); err = (Get-Content (Join-Path $d 'stderr.txt') -Raw -ErrorAction SilentlyContinue) }
  }
  function Has-Reason($r, [string]$rx) { return [bool](@($r.info.reasons | Where-Object { $_ -match $rx }).Count) }
  $keep = @()
  $r = Invoke-Scenario 'good' 'none' $null
  $keep += $r.dir
  T 'F4' 'five windows -> five independent captures, verdict COMPLETE, exit code 0' (($r.info.verdict -eq 'COMPLETE') -and ($r.exit -eq 0) -and (@($r.info.windows).Count -eq 5)) "verdict=$($r.info.verdict) exit=$($r.exit) reasons=$(@($r.info.reasons) -join ' | ') err=$($r.err)"
  if ($r.info) {
    $w = @($r.info.windows); $nonOverlap = $true; for ($i = 1; $i -lt $w.Count; $i++) { if ([DateTime]$w[$i].captureStartUtc -lt [DateTime]$w[$i - 1].captureEndUtc) { $nonOverlap = $false } }
    T 'F4' 'every window has its own ETL/CSV evidence and the capture intervals do not overlap' ($nonOverlap -and (@($w | Where-Object { $_.providers.tcpip.etlBytes -gt 0 -and $_.providers.kernnet.etlBytes -gt 0 -and $_.providers.tcpip.selfProbeRows -ge 1 }).Count -eq 5))
    $all = ''; foreach ($f in (Get-ChildItem -LiteralPath $r.report -Filter 'etw_*.filtered.csv')) { $all += [IO.File]::ReadAllText($f.FullName) }
    T 'F6' 'filtered report keeps the tracked live instance and drops reused PID / other PID / probe rows' (($all -match 'KEEP-ME') -and ($all -notmatch 'OTHER-PID|REUSED-PID|selfprobe'))
    T 'F1' 'run folders were created under the safe root (raw deleted by -DryRun, report kept) and nothing was written into -Out' (@(Get-ChildItem -LiteralPath (Join-Path $r.dir 'out') | Where-Object { $_.Name -notmatch '\.(start|end|flag|jsonl)$' }).Count -eq 0)
  }
  $r = Invoke-Scenario 'audit: browser process never alive' 'none' $null 5 $true $false $ps51 'msedgewebview2.exe'
  T 'AUDIT' 'no tracked browser process during a window => INCOMPLETE (a wrong -RootExe must not read as "no connections")' (($r.info.verdict -eq 'INCOMPLETE') -and (Has-Reason $r 'browser process was alive')) "verdict=$($r.info.verdict) reasons=$(@($r.info.reasons | Select-Object -First 2) -join ' | ')"
  $r = Invoke-Scenario 'audit: events lost' 'events-lost' $null
  T 'AUDIT' 'lost events/buffers reported by a session => INCOMPLETE' (($r.info.verdict -eq 'INCOMPLETE') -and (Has-Reason $r 'lost')) "verdict=$($r.info.verdict) reasons=$(@($r.info.reasons | Select-Object -First 2) -join ' | ')"
  $r = Invoke-Scenario 'audit: nonexistent RootExe' 'none' $null 1 $true $false 'C:\nonexistent\PersonalVault.exe'
  T 'AUDIT' 'a nonexistent -RootExe is refused at start (no run, no report)' (($r.exit -ne 0) -and -not $r.info -and ($r.err -match 'RootExe')) "exit=$($r.exit) err=$($r.err)"
  foreach ($case in @(
      @{ n = 'F6 etl missing'; f = 'etl-missing'; rx = 'no ETL' }, @{ n = 'F6 bad CSV header'; f = 'csv-header'; rx = 'header' },
      @{ n = 'F6 PID attribution control fails'; f = 'no-selfprobe'; rx = 'attribution control' }, @{ n = 'F6 ETL reached the size cap'; f = 'truncated'; rx = 'size cap' },
      @{ n = 'F6 provider delivers no events'; f = 'provider-empty'; rx = 'no events' })) {
    $r = Invoke-Scenario $case.n $case.f $null
    T 'F6' "$($case.n) => INCOMPLETE (never PASS), exit 2" (($r.info.verdict -eq 'INCOMPLETE') -and ($r.exit -eq 2) -and (Has-Reason $r $case.rx)) "verdict=$($r.info.verdict) exit=$($r.exit) reasons=$(@($r.info.reasons | Select-Object -First 2) -join ' | ')"
  }
  $bad = @(
    @{ n = 'F5 stateVerified=false'; rx = 'stateVerified'; m = { param($rows) $rows[2].stateVerified = $false; $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } } },
    @{ n = 'F5 profileVerified=false'; rx = 'profileVerified'; m = { param($rows) $rows[3].profileVerified = $false; $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } } },
    @{ n = 'F5 wrong window order'; rx = 'must be'; m = { param($rows) $x = $rows[0]; $rows[0] = $rows[1]; $rows[1] = $x; $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } } },
    @{ n = 'F5 unknown key'; rx = 'unknown key'; m = { param($rows) $rows[1].extra = 1; $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } } },
    @{ n = 'F5 marker not inside the captured interval'; rx = 'not inside the captured interval'; m = { param($rows) $rows[2].startUtc = ([DateTime]::Parse($rows[2].startUtc).AddSeconds(-5)).ToUniversalTime().ToString('o'); $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } } },
    @{ n = 'F5 window shorter than the minimum'; rx = 'lasted'; m = { param($rows) $rows[4].endUtc = $rows[4].startUtc; $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } } },
    @{ n = 'F5 oversized markers file'; rx = 'too large'; m = { param($rows) , (('x' * 20000)) } },
    @{ n = 'F5 non-ISO time'; rx = 'ISO-8601'; m = { param($rows) $rows[0].startUtc = '2026-11-14 10:00:00'; $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } } })
  foreach ($b in $bad) {
    $r = Invoke-Scenario $b.n 'none' $b.m
    T 'F5' "$($b.n) => INCOMPLETE" (($r.info.verdict -eq 'INCOMPLETE') -and ($r.exit -eq 2) -and (Has-Reason $r $b.rx)) "verdict=$($r.info.verdict) reasons=$(@($r.info.reasons | Select-Object -First 3) -join ' | ')"
  }
  $r = Invoke-Scenario 'F5 only four windows' 'none' $null 4
  T 'F5' 'only four of five windows => INCOMPLETE (window never captured)' (($r.info.verdict -eq 'INCOMPLETE') -and (Has-Reason $r 'never captured')) "verdict=$($r.info.verdict) reasons=$(@($r.info.reasons | Select-Object -First 3) -join ' | ')"
  $r = Invoke-Scenario 'F4 abort after window 2' 'none' $null 2 $false
  T 'F4' 'abort.flag after two windows => INCOMPLETE, the finished windows keep their evidence' (($r.info.verdict -eq 'INCOMPLETE') -and (@($r.info.windows).Count -eq 2) -and ($r.info.endReason -eq 'abort.flag')) "verdict=$($r.info.verdict) windows=$(@($r.info.windows).Count) end=$($r.info.endReason)"
  $r = Invoke-Scenario 'F4 last window never ends' 'none' $null 3 $true $true
  T 'F4' 'a window without its .end flag when the run finishes => INCOMPLETE (closed and reported)' (($r.info.verdict -eq 'INCOMPLETE') -and (Has-Reason $r 'before its \.end flag')) "verdict=$($r.info.verdict) reasons=$(@($r.info.reasons | Select-Object -First 3) -join ' | ')"
  Get-ChildItem ([IO.Path]::GetTempPath()) -Directory -Filter 'pvtr-t-*' | ForEach-Object { try { Remove-Item -LiteralPath $_.FullName -Recurse -Force } catch { } }
}
$fails = @($res | Where-Object { -not $_.pass })
Write-Host "tests: $($res.Count - $fails.Count) PASS / $($fails.Count) FAIL"
$res | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path ([IO.Path]::GetTempPath()) 'net_trace_tests_last.json') -Encoding UTF8
exit $(if ($fails.Count) { 1 } else { 0 })
