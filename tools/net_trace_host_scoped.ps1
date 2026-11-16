# Personal Vault - host-scoped network trace (QA, SYNTHETIC vault only). Revision R4 = v3 + the 6 findings of the Manager's source audit.
# STATUS: awaiting Manager re-review. NOT to be run elevated before review PASS. The AI Coding agent never runs it elevated.
#
# WHAT IT DOES (one elevated run): for each of the 5 windows driven by the non-elevated harness (<label>.start / <label>.end files in -Out) it starts its OWN
# ETW sessions (TCPIP + Kernel-Network [+ DNS-Client if -IncludeDns]) writing a NON-circular ETL for that window only, stops them at <label>.end, converts the ETL
# inside an admin-only folder and writes to the report folder ONLY the rows of tracked process instances (PID + creation time + lifetime). Every step is checked:
# exit codes, ETL present and not truncated, CSV schema, events present, time coverage, and a positive attribution control (this script's own loopback TCP
# connection must show up under its own PID in every provider). Anything missing => verdict INCOMPLETE (never PASS) and exit code 2.
# NEVER: firewall / registry / Edge-WebView2 policy change; touching other processes or other tracing sessions; payload capture; pktmon / WinHTTP / WPR;
#   raw command lines in the report; upload; recursive delete of a path whose owner/ACL was not verified.
#
# TRUST MODEL (checked before anything is written): run with the SYSTEM Windows PowerShell and -NoProfile; module path reduced to the system modules; logman/tracerpt/
# icacls are the absolute System32 binaries with a valid Microsoft signature; the script lives in an admin-owned, protected, admin-only staging folder; its
# SHA256 equals -ExpectedSha256; %ProgramData%\PVTrace (root), raw\ and reports\ are admin-owned, protected, admin-only real folders whose ancestors cannot be
# replaced by ordinary users; -Out (the only user-writable input) must be a real folder owned by the invoking account with no write ACE for anyone else,
# is only READ by this script, and every file read from it is bounded and must not be a link.
# Usage (Owner, elevated):
#   & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "<staging>\net_trace_host_scoped.ps1" `
#     -ExpectedSha256 <reviewed hash> -RootExe "<candidate>\PersonalVault.exe,<control>\control_webview2_host.exe" -Out "<protocol folder created by the harness>"
#   (-RootExe and -Labels are ONE comma-joined argument: powershell.exe -File passes it as a single string, the script splits it.)
#   -ExpectedSha256 is only a tripwire against running the wrong file: the Owner verifies the staged file's hash with Get-FileHash in the elevated shell BEFORE running it.
#   opt-in: -IncludeDns (single extra window: -Labels W2-unlocked -MinWindows irrelevant)   -DeleteRaw      tests without admin: -DryRun -Root <temp> [-DryRunFault ...]  and  -SelfTest
[CmdletBinding(PositionalBinding = $false)]
param(
  [Parameter(Mandatory)][string]$ExpectedSha256,
  [Parameter(Mandatory)][string[]]$RootExe,
  [Parameter(Mandatory)][string]$Out,
  [string]$Root = (Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'PVTrace'),
  [string]$ReaderSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value,   # the invoking account: READ-only on the report; pass the Owner's SID if elevating with another account
  [string[]]$Labels = @('W1-locked', 'W2-unlocked', 'W3-transition', 'W4-control-C1', 'W5-control-C2'),
  [ValidateRange(60, 2700)][int]$MaxSeconds = 2400,
  [ValidateRange(16, 512)][int]$MaxMB = 256,
  [int]$MinWindowSeconds = 180,
  [string]$BrowserProcessName = 'msedgewebview2.exe',   # every captured window must show at least one tracked instance of this process (the browser process, no --type=)
  [switch]$IncludeDns, [switch]$DeleteRaw, [switch]$DryRun, [switch]$SelfTest,
  [ValidateSet('none', 'etl-missing', 'csv-header', 'no-selfprobe', 'truncated', 'provider-empty', 'events-lost')][string]$DryRunFault = 'none'
)
$ErrorActionPreference = 'Stop'
$RootExe = @($RootExe | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().Trim('"') } | Where-Object { $_ })   # powershell.exe -File passes "a,b" as ONE argument
$Labels = @($Labels | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().Trim('"') } | Where-Object { $_ })
function Get-Safe([string]$s, [int]$max = 200) { if ($null -eq $s) { return '' }; $t = ($s -replace '[^\x20-\x7E]', '?'); if ($t.Length -gt $max) { $t = $t.Substring(0, $max) + '...' }; return $t }   # untrusted text never reaches the report unfiltered
$env:PSModulePath = (@("$PSHOME\Modules", (Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\Modules')) | Select-Object -Unique) -join ';'   # no user-writable module folder can shadow a cmdlet
$id = 'pvtr' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$AllLabels = @('W1-locked', 'W2-unlocked', 'W3-transition', 'W4-control-C1', 'W5-control-C2')
$SidAdmins = 'S-1-5-32-544'; $SidSystem = 'S-1-5-18'; $SidTI = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
$AdminSids = @($SidAdmins, $SidSystem); $TrustedOwners = @($SidAdmins, $SidSystem, $SidTI)
$MASK_STRICT = 0x10000000 -bor 0x40000000 -bor 0x80000 -bor 0x40000 -bor 0x10000 -bor 0x40 -bor 0x4 -bor 0x2   # generic all/write, take-ownership, write-DAC, delete, delete-child, append, write
$MASK_ANCESTOR = 0x10000000 -bor 0x40000000 -bor 0x80000 -bor 0x40000 -bor 0x10000 -bor 0x40                  # an ancestor must not be deletable/re-ownable/re-ACL-able by others (creating children is normal)

$SysDir = [Environment]::SystemDirectory
$WinDir = [Environment]::GetFolderPath('Windows')   # from the OS API, not from an environment variable the elevating shell could have changed
$Logman = Join-Path $SysDir 'logman.exe'; $Tracerpt = Join-Path $SysDir 'tracerpt.exe'; $Icacls = Join-Path $SysDir 'icacls.exe'; $Fsutil = Join-Path $SysDir 'fsutil.exe'
$log = New-Object System.Collections.Generic.List[string]
function Say($m) { $l = "$([DateTime]::UtcNow.ToString('o')) $m"; $log.Add($l); Write-Host $l }
function Iso([DateTime]$d) { $d.ToUniversalTime().ToString('o') }

# ---------------------------------------------------------------- native tools: absolute, signed, exit code checked
function Assert-SysExe([string]$p) {
  if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "missing system tool: $p" }
  if (-not ([IO.Path]::GetFullPath($p)).StartsWith($SysDir + '\', 'OrdinalIgnoreCase')) { throw "tool is not inside $SysDir`: $p" }
  $s = Get-AuthenticodeSignature -LiteralPath $p
  if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw "system tool has no valid Microsoft signature ($($s.Status)): $p" }
}
function Invoke-Sys([string]$exe, [string[]]$a, [string]$what) {
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1 turns native stderr into terminating errors under 'Stop'
  try { $o = (& $exe @a 2>&1 | Out-String); $code = $LASTEXITCODE } finally { $ErrorActionPreference = $old }
  if ($code -ne 0) { throw "$what failed (exit $code): $($o.Trim())" }
  return $o
}

# ---------------------------------------------------------------- filesystem trust checks (F1)
function Test-NotReparse([string]$path) {   # the path and every existing parent must be a real folder/file, not a junction/symlink
  $p = [IO.Path]::GetFullPath($path)
  while ($p) {
    if (Test-Path -LiteralPath $p) { if ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false } }
    $parent = Split-Path $p -Parent
    if (-not $parent -or $parent -eq $p) { break }
    $p = $parent
  }
  return $true
}
# mode strict  : owner trusted, DACL protected, ONLY Administrators/SYSTEM have any access
# mode report  : like strict, plus -ReaderSid may have read-only access
# mode ancestor: owner trusted, nobody untrusted can delete / re-own / re-ACL it (inherit-only ACEs are ignored: they only describe future children)
# In strict/report mode inherit-only ACEs ARE checked: they are exactly what files created inside the folder will inherit.
# returns $null when trusted, otherwise the reason
function Test-DirTrusted([string]$path, [string]$mode) {
  if (-not (Test-Path -LiteralPath $path -PathType Container)) { return "missing folder: $path" }
  if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return "junction/symlink: $path" }
  $acl = Get-Acl -LiteralPath $path
  $own = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
  if ($own -notin $TrustedOwners) { return "owner $own is not Administrators/SYSTEM/TrustedInstaller: $path" }
  if ($mode -ne 'ancestor' -and -not $acl.AreAccessRulesProtected) { return "DACL not protected (inherits from its parent): $path" }
  if ($mode -eq 'ancestor' -and (([IO.Path]::GetFullPath($path).TrimEnd('\') + '\') -eq [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($path)))) { return $null }   # a volume root cannot be deleted/renamed; its DACL differs between machines (seen: Authenticated Users:Modify in the Sandbox image). Owner + reparse were checked above.
  foreach ($r in $acl.Access) {
    if ($r.AccessControlType -ne 'Allow') { continue }
    if ($mode -eq 'ancestor' -and ($r.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)) { continue }
    $sid = $r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($sid -in $TrustedOwners) { continue }
    if ($mode -eq 'ancestor') { if (([int]$r.FileSystemRights -band $MASK_ANCESTOR) -ne 0) { return "untrusted principal $sid can delete/re-own/re-ACL: $path" }; continue }
    if ($mode -eq 'report' -and $sid -eq $ReaderSid -and (([int]$r.FileSystemRights -band $MASK_STRICT) -eq 0)) { continue }
    return "principal $sid has access on $path (admin-only required)"
  }
  return $null
}
function Test-FileTrusted([string]$path) {   # the staged script itself: real file, trusted owner, nobody but Administrators/SYSTEM has any access, single hard link
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return "missing file: $path" }
  if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return "link: $path" }
  $acl = Get-Acl -LiteralPath $path
  $own = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
  if ($own -notin $TrustedOwners) { return "file owner $own is not Administrators/SYSTEM/TrustedInstaller: $path" }
  foreach ($r in $acl.Access) {
    if ($r.AccessControlType -ne 'Allow') { continue }
    $sid = $r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($sid -in $TrustedOwners) { continue }
    return "principal $sid has access on the script file $path (copy it into staging as an administrator; do not Move it)"
  }
  $links = @((Invoke-Sys $Fsutil @('hardlink', 'list', $path) 'fsutil hardlink list') -split "`r?`n" | Where-Object { $_.Trim() })
  if ($links.Count -gt 1) { return "the script file has $($links.Count) hard links: $path" }
  return $null
}
function Test-AncestorsTrusted([string]$path) {
  $p = Split-Path ([IO.Path]::GetFullPath($path)) -Parent
  while ($p) {
    $e = Test-DirTrusted $p 'ancestor'; if ($e) { return $e }
    $par = Split-Path $p -Parent
    if (-not $par -or $par -eq $p) { break }
    $p = $par
  }
  return $null
}
function Test-OutDir([string]$path) {   # the only user-writable input: real folder, owned by the invoking account, nobody else can write
  if (-not (Test-Path -LiteralPath $path -PathType Container)) { return "-Out must be an existing folder created by the harness: $path" }
  if (-not (Test-NotReparse $path)) { return '-Out (or a parent) is a junction/symlink' }
  $acl = Get-Acl -LiteralPath $path
  $own = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
  if ($own -ne $ReaderSid -and $own -notin $AdminSids) { return "-Out is owned by $own, not by the invoking account" }
  foreach ($r in $acl.Access) {
    if ($r.AccessControlType -ne 'Allow') { continue }
    $sid = $r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($sid -eq $ReaderSid -or $sid -in $AdminSids) { continue }
    if (([int]$r.FileSystemRights -band $MASK_STRICT) -ne 0) { return "-Out grants write access to $sid" }
  }
  return $null
}
function New-SecureDir([string]$path, [string]$mode) {   # create + lock + verify; a folder that fails verification is only removed when empty (never recursively)
  if (Test-Path -LiteralPath $path) { throw "refusing to reuse an existing folder: $path" }
  New-Item -ItemType Directory -Path $path | Out-Null
  if ($DryRun) { return }
  $grants = @('*S-1-5-32-544:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'); if ($mode -eq 'report') { $grants += "*${ReaderSid}:(OI)(CI)R" }
  Invoke-Sys $Icacls (@($path, '/inheritance:r', '/grant:r') + $grants) "icacls grant $path" | Out-Null
  Invoke-Sys $Icacls @($path, '/setowner', '*S-1-5-32-544') "icacls setowner $path" | Out-Null
  $e = Test-DirTrusted $path $mode
  if ($e) { try { [IO.Directory]::Delete($path) } catch { }; throw "folder failed verification right after creation: $e" }
}
function Remove-OwnedRunDir([string]$dir, [string]$base, [string]$mode) {   # recursive delete ONLY of a verified run folder of this tool
  $full = [IO.Path]::GetFullPath($dir); $b = ([IO.Path]::GetFullPath($base)).TrimEnd('\') + '\'
  if (-not $full.StartsWith($b, 'OrdinalIgnoreCase') -or (Split-Path $full -Leaf) -notmatch '^pvtr[0-9a-f]{8}$') { Say "not deleting (not a run folder under $base): $full"; return }
  if (-not (Test-NotReparse $full)) { Say "not deleting (link): $full"; return }
  if (-not $DryRun) { $e = Test-DirTrusted $full $mode; if ($e) { Say "not deleting (unverified): $e"; return } }
  foreach ($f in (Get-ChildItem -LiteralPath $full -Recurse -Force)) { if ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) { Say "not deleting (link inside): $($f.FullName)"; return } }
  Remove-Item -LiteralPath $full -Recurse -Force
}
function Test-FlagFile([string]$name) {
  $p = Join-Path $Out $name
  return ((Test-Path -LiteralPath $p -PathType Leaf) -and -not ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint))
}

# ---------------------------------------------------------------- marker schema, validated HERE, not trusted from the harness (F5)
$MarkerKeys = @('label', 'startUtc', 'endUtc', 'stateVerified', 'profileVerified', 'flagsVerified', 'note')
function Get-TimeText($v) { if ($v -is [DateTime]) { return $v.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ') } else { return "$v" } }   # PowerShell 7 parses ISO strings into DateTime
function Test-MarkerFile([string]$path, [string[]]$labels, [int]$minSec, $caps, [DateTime]$notBefore) {
  $errs = @()
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return @('markers.jsonl missing') }
  $it = Get-Item -LiteralPath $path -Force
  if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { return @('markers.jsonl is a link') }
  if ($it.Length -gt 16384) { return @("markers.jsonl too large ($($it.Length) bytes, max 16384)") }
  $lines = @(Get-Content -LiteralPath $path | Where-Object { $_.Trim() })
  if ($lines.Count -ne $labels.Count) { $errs += "expected $($labels.Count) markers, found $($lines.Count)" }
  $prevEnd = $null
  for ($i = 0; $i -lt $lines.Count -and $i -lt $labels.Count; $i++) {
    $o = $null; try { $o = $lines[$i] | ConvertFrom-Json } catch { $errs += "marker $i is not JSON"; continue }
    $keys = @($o.PSObject.Properties.Name)
    foreach ($k in $keys) { if ($k -notin $MarkerKeys) { $errs += "marker $i has unknown key '$k'" } }
    foreach ($k in $MarkerKeys) { if ($k -notin $keys) { $errs += "marker $i misses '$k'" } }
    if ($errs.Count) { continue }
    if ($o.label -isnot [string] -or $o.label -ne $labels[$i]) { $errs += "marker $i must be '$($labels[$i])', got '$($o.label)'"; continue }
    foreach ($k in 'stateVerified', 'profileVerified', 'flagsVerified') { if ($o.$k -isnot [bool] -or -not $o.$k) { $errs += "$($o.label).$k must be true" } }
    if ($o.note -isnot [string] -or $o.note.Length -gt 200) { $errs += "$($o.label).note must be a string of at most 200 characters" }
    $s = $null; $e = $null
    foreach ($k in 'startUtc', 'endUtc') { if ((Get-TimeText $o.$k) -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?Z$') { $errs += "$($o.label).$k is not ISO-8601 UTC" } }
    if ($errs.Count) { continue }
    $s = [DateTime]::Parse((Get-TimeText $o.startUtc), $null, [Globalization.DateTimeStyles]::AdjustToUniversal); $e = [DateTime]::Parse((Get-TimeText $o.endUtc), $null, [Globalization.DateTimeStyles]::AdjustToUniversal)
    $sec = ($e - $s).TotalSeconds
    if ($sec -lt $minSec -or $sec -gt 900) { $errs += "$($o.label) lasted $([int]$sec) s (allowed $minSec..900)" }
    if ($s -lt $notBefore -or $e -gt [DateTime]::UtcNow.AddSeconds(5)) { $errs += "$($o.label) lies outside this run" }
    if ($prevEnd -and $s -lt $prevEnd) { $errs += "$($o.label) overlaps the previous window" }
    $prevEnd = $e
    $c = $caps[$o.label]
    if (-not $c) { $errs += "$($o.label) has no capture" } elseif ($s -lt $c.start.AddSeconds(-2) -or $e -gt $c.end.AddSeconds(2)) { $errs += "$($o.label) marker is not inside the captured interval" }   # 2 s slack: the harness polls for the sessions
  }
  return $errs
}

# ---------------------------------------------------------------- tracerpt CSV schema (F6)
$CsvColumns = @('Event Name', 'Type', 'Event ID', 'Version', 'Channel', 'Level', 'Opcode', 'Task', 'Keyword', 'PID', 'TID', 'Processor Number', 'Instance ID', 'Parent Instance ID', 'Activity ID', 'Related Activity ID', 'Clock-Time', 'Kernel(ms)', 'User(ms)', 'User Data')
function Test-CsvHeader([string]$line) { $c = @($line.Split(',') | ForEach-Object { $_.Trim() }); return (($c.Count -eq $CsvColumns.Count) -and (-not (Compare-Object $c $CsvColumns -SyncWindow 0))) }

# ---------------------------------------------------------------- -SelfTest (no admin): unit tests of the validators above
if ($SelfTest) {
  $res = New-Object System.Collections.Generic.List[object]
  function T([string]$n, [bool]$ok) { $res.Add([pscustomobject]@{ test = $n; pass = $ok }); Write-Host ("{0}  {1}" -f ($(if ($ok) { 'PASS' } else { 'FAIL' })), $n) }
  $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $t = Join-Path ([IO.Path]::GetTempPath()) ('pvtr-selftest-' + [guid]::NewGuid().ToString('N').Substring(0, 8)); New-Item -ItemType Directory $t | Out-Null
  try {
    $own = Join-Path $t 'user-owned'; New-Item -ItemType Directory $own | Out-Null
    & $Icacls $own /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' | Out-Null
    & $Icacls $own /setowner "*$me" | Out-Null   # a folder this account owns (on a host with UAC off the creator would already be Administrators)
    T 'F1 owner check: a folder owned by the invoking user is rejected even with an admin-only protected DACL' ([bool](Test-DirTrusted $own 'strict'))
    $open = Join-Path $t 'inherits'; New-Item -ItemType Directory $open | Out-Null; & $Icacls $open /setowner "*$me" | Out-Null
    T 'F1 a folder that inherits its DACL (not protected) or is user-owned is rejected' ([bool](Test-DirTrusted $open 'strict'))
    $real = Join-Path $t 'real'; New-Item -ItemType Directory $real | Out-Null; $j = Join-Path $t 'junction'; New-Item -ItemType Junction -Path $j -Target $real | Out-Null
    T 'F1 a junction is rejected' ([bool](Test-DirTrusted $j 'strict') -and -not (Test-NotReparse $j))
    T 'F1 an ancestor chain through a junction is rejected' (-not (Test-NotReparse (Join-Path $j 'child')))
    T 'F1 missing folder is rejected' ([bool](Test-DirTrusted (Join-Path $t 'nope') 'strict'))
    T 'F1 -Out owned by the invoking account with no foreign write ACE is accepted' (-not (Test-OutDir $own))
    $wo = Join-Path $t 'out-foreign-write'; New-Item -ItemType Directory $wo | Out-Null; & $Icacls $wo /grant '*S-1-5-32-545:(OI)(CI)M' | Out-Null
    T 'F1 -Out that grants write to the Users group is rejected' ([bool](Test-OutDir $wo))
    $ab = Test-DirTrusted (Split-Path $env:ProgramData -Parent) 'ancestor'
    T "F1 the system drive root passes the ancestor test ($(if ($ab) { $ab } else { 'ok' }))" (-not $ab)
    T 'F1 C:\ProgramData passes the ancestor test' (-not (Test-DirTrusted $env:ProgramData 'ancestor'))
    T 'F1 a user profile folder fails the ancestor test (user can re-ACL it)' ([bool](Test-DirTrusted $t 'ancestor'))
    $io = Join-Path $t 'inherit-only'; New-Item -ItemType Directory $io | Out-Null
    & $Icacls $io /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)(IO)M' | Out-Null; & $Icacls $io /setowner '*S-1-5-32-544' | Out-Null
    T 'F1 an inherit-only ACE for Users in a strict folder (what its files would inherit) is rejected' ([bool](Test-DirTrusted $io 'strict'))
    $sf = Join-Path $t 'staged.ps1'; Set-Content -LiteralPath $sf -Value 'x'
    T 'F1 a script file that other principals can access is rejected' ([bool](Test-FileTrusted $sf))
    T 'F1 untrusted text is stripped of control characters and truncated before it reaches the report' ((Get-Safe ("a`r`nb`0" + ('x' * 500)) 50).Length -le 53 -and (Get-Safe "a`r`nb") -eq 'a??b')
    foreach ($e in $Logman, $Tracerpt, $Icacls) { $ok = $true; try { Assert-SysExe $e } catch { $ok = $false }; T "F2 trusted system tool: $(Split-Path $e -Leaf)" $ok }
    $bad = $true; try { Assert-SysExe (Join-Path $t 'logman.exe') } catch { $bad = $false }; T 'F2 a look-alike outside System32 is rejected' (-not $bad)
    T 'F2 module path contains no user-writable folder' (-not ($env:PSModulePath -match [regex]::Escape($env:USERPROFILE)))
    T 'F6 CSV header accepted' (Test-CsvHeader (($CsvColumns | ForEach-Object { '  ' + $_ }) -join ','))
    T 'F6 CSV header with a missing column rejected' (-not (Test-CsvHeader (($CsvColumns[0..18]) -join ',')))
    T 'F6 CSV header in the wrong order rejected' (-not (Test-CsvHeader ((@($CsvColumns[1], $CsvColumns[0]) + $CsvColumns[2..19]) -join ',')))
    $now = [DateTime]::UtcNow; $nb = $now.AddMinutes(-30)
    $caps = @{}; $good = @(); for ($i = 0; $i -lt 5; $i++) { $s = $now.AddSeconds(-1500 + $i * 250); $caps[$AllLabels[$i]] = @{ start = $s.AddSeconds(-3); end = $s.AddSeconds(200) }; $good += ([ordered]@{ label = $AllLabels[$i]; startUtc = (Iso $s); endUtc = (Iso $s.AddSeconds(190)); stateVerified = $true; profileVerified = $true; flagsVerified = $true; note = 'x' } | ConvertTo-Json -Compress) }
    function Mk($lines) { $p = Join-Path $t ('m' + [guid]::NewGuid().ToString('N').Substring(0, 6) + '.jsonl'); [IO.File]::WriteAllLines($p, [string[]]$lines); $p }
    T 'F5 good markers accepted' (-not @(Test-MarkerFile (Mk $good) $AllLabels 180 $caps $nb).Count)
    T 'F5 4 of 5 windows rejected' ([bool]@(Test-MarkerFile (Mk $good[0..3]) $AllLabels 180 $caps $nb).Count)
    $m = $good.Clone(); $m[2] = $m[2] -replace '"stateVerified":true', '"stateVerified":false'; T 'F5 stateVerified=false rejected' ([bool]@(Test-MarkerFile (Mk $m) $AllLabels 180 $caps $nb).Count)
    $m = $good.Clone(); $m[1] = $m[1] -replace '"profileVerified":true', '"profileVerified":"yes"'; T 'F5 non-boolean profileVerified rejected' ([bool]@(Test-MarkerFile (Mk $m) $AllLabels 180 $caps $nb).Count)
    $m = $good.Clone(); $m[0], $m[1] = $m[1], $m[0]; T 'F5 wrong order rejected' ([bool]@(Test-MarkerFile (Mk $m) $AllLabels 180 $caps $nb).Count)
    $m = $good.Clone(); $m[3] = $m[3] -replace ',"note"', ',"extra":1,"note"'; T 'F5 unknown key rejected' ([bool]@(Test-MarkerFile (Mk $m) $AllLabels 180 $caps $nb).Count)
    $m = $good.Clone(); $m[2] = ($m[2] | ConvertFrom-Json); $m[2].endUtc = $m[2].startUtc; $m[2] = ($m[2] | ConvertTo-Json -Compress); T 'F5 zero-length window rejected' ([bool]@(Test-MarkerFile (Mk $m) $AllLabels 180 $caps $nb).Count)
    $m = $good.Clone(); $m[1] = ($m[1] | ConvertFrom-Json); $m[1].startUtc = (Iso $now.AddSeconds(-1700)); $m[1] = ($m[1] | ConvertTo-Json -Compress); T 'F5 overlap / outside-run rejected' ([bool]@(Test-MarkerFile (Mk $m) $AllLabels 180 $caps $nb).Count)
    $m = $good.Clone(); $m[0] = $m[0] -replace '"startUtc":"[^"]+"', '"startUtc":"2026-11-14 10:00:00"'; T 'F5 non-ISO time rejected' ([bool]@(Test-MarkerFile (Mk $m) $AllLabels 180 $caps $nb).Count)
    $big = Mk @(('x' * 20000)); T 'F5 oversized file rejected before parsing' ([bool]@(Test-MarkerFile $big $AllLabels 180 $caps $nb).Count)
    $caps2 = @{}; foreach ($k in $caps.Keys) { $caps2[$k] = @{ start = $caps[$k].start.AddSeconds(30); end = $caps[$k].end } }; T 'F5 marker outside the captured interval rejected' ([bool]@(Test-MarkerFile (Mk $good) $AllLabels 180 $caps2 $nb).Count)
  } finally { Remove-Item -LiteralPath $t -Recurse -Force -ErrorAction SilentlyContinue }
  $fails = @($res | Where-Object { -not $_.pass }).Count
  Write-Host "selftest: $($res.Count - $fails) PASS / $fails FAIL"
  exit $(if ($fails) { 1 } else { 0 })
}

# ---------------------------------------------------------------- preconditions
$selfHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
if ($selfHash -ne $ExpectedSha256.ToUpper()) { throw "SHA256 of this script ($selfHash) differs from -ExpectedSha256. Refusing to run." }
$sidObj = [Security.Principal.SecurityIdentifier]::new($ReaderSid)
if ($sidObj.Value -notmatch '^S-1-(5-21-\d+-\d+-\d+-(50\d|51[01]|[1-9]\d{3,})|12-1-[\d-]+)$') { throw '-ReaderSid must be one user account SID (RID 500-511 built-in users, or >= 1000), not a well-known or group SID.' }   # RIDs 512-999 are groups
$ReaderSid = $sidObj.Value
$badLabels = @($Labels | Where-Object { $_ -notin $AllLabels })
if ($badLabels.Count -or $Labels.Count -lt 1 -or (@($AllLabels | Where-Object { $_ -in $Labels }) -join ',') -ne ($Labels -join ',')) { throw "-Labels must be a subset of the 5 canonical labels in canonical order." }
if (-not $DryRun) {
  if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run elevated (Owner action), or use -DryRun / -SelfTest.' }
  if ([Environment]::CommandLine -notmatch '(?i)\s-NoProfile\b') { throw 'Start the script with powershell.exe -NoProfile (a profile is user-controlled code).' }
  if (-not $PSHOME.StartsWith((Join-Path $WinDir 'System32\WindowsPowerShell'), 'OrdinalIgnoreCase')) { throw "Run with the system Windows PowerShell ($WinDir\System32\WindowsPowerShell\v1.0\powershell.exe), not $PSHOME." }
  foreach ($e in $Logman, $Tracerpt, $Icacls, $Fsutil) { Assert-SysExe $e }
  $se = Test-DirTrusted (Split-Path $PSCommandPath) 'strict'; if ($se) { throw "Script folder is not a trusted staging folder: $se" }
  $fe = Test-FileTrusted $PSCommandPath; if ($fe) { throw "Script file is not trusted: $fe" }
  $an = Test-AncestorsTrusted $PSCommandPath; if ($an) { throw "Unsafe ancestor of the staging folder: $an" }
  foreach ($p in $PSCommandPath, $Root) { $drv = [IO.DriveInfo]::new(([IO.Path]::GetFullPath($p)).Substring(0, 1)); if ($drv.DriveType -ne 'Fixed' -or $drv.DriveFormat -ne 'NTFS') { throw "$p is not on a local fixed NTFS volume" } }
} elseif (-not $PSBoundParameters.ContainsKey('Root')) { throw '-DryRun requires an explicit -Root (a temp folder): it must never touch the production root.' }
if ($RootExe.Count -lt 1) { throw '-RootExe is empty.' }
foreach ($x in $RootExe) { if (-not [IO.Path]::IsPathRooted($x) -or -not (Test-Path -LiteralPath $x -PathType Leaf)) { throw "-RootExe entry is not an existing absolute file path: $x" } }
$roots = @($RootExe | ForEach-Object { [IO.Path]::GetFullPath($_) })
$rootExeHashes = [ordered]@{}; foreach ($x in $roots) { $rootExeHashes[(Split-Path $x -Leaf)] = (Get-FileHash -LiteralPath $x -Algorithm SHA256).Hash }   # binds the evidence to the binaries that were traced
if (-not (Test-Path -LiteralPath $Out -PathType Container)) { throw "-Out must already exist (the harness creates it with a locked ACL): $Out" }
$Out = (Resolve-Path -LiteralPath $Out).Path
if (-not $DryRun) { $oe = Test-OutDir $Out; if ($oe) { throw $oe } } elseif (-not (Test-NotReparse $Out)) { throw '-Out (or a parent) is a junction/symlink' }

# ---------------------------------------------------------------- safe roots: root -> raw / reports -> run folders
$Root = [IO.Path]::GetFullPath($Root)
if (-not (Test-NotReparse $Root)) { throw "-Root (or a parent) is a junction/symlink: $Root" }
if (-not $DryRun) { $an = Test-AncestorsTrusted $Root; if ($an) { throw "Unsafe ancestor of -Root: $an" } }
if (-not (Test-Path -LiteralPath $Root)) { New-SecureDir $Root 'strict' } elseif (-not $DryRun) { $e = Test-DirTrusted $Root 'strict'; if ($e) { throw "-Root exists but is not trusted ($e). Owner: remove it or fix owner/ACL (icacls <dir> /setowner *S-1-5-32-544 and /inheritance:r /grant:r admin+SYSTEM), then rerun." } }
$RawBase = Join-Path $Root 'raw'; $ReportBase = Join-Path $Root 'reports'
foreach ($b in $RawBase, $ReportBase) { if (-not (Test-Path -LiteralPath $b)) { New-SecureDir $b 'strict' } elseif (-not $DryRun) { $e = Test-DirTrusted $b 'strict'; if ($e) { throw "$b exists but is not trusted ($e)" } } }
$RawRun = Join-Path $RawBase $id; $Report = Join-Path $ReportBase $id
if ($Out.StartsWith($Root, 'OrdinalIgnoreCase') -or $Root.StartsWith($Out, 'OrdinalIgnoreCase')) { throw '-Out and -Root must be separate folders.' }
New-SecureDir $RawRun 'strict'
New-SecureDir $Report 'report'
Say "folders verified (owner Administrators/SYSTEM, protected, admin-only; report readable by $ReaderSid only): $(-not $DryRun)"

# ---------------------------------------------------------------- command-line allowlist (nothing else is ever exported)
$allowSwitch = '^--(type|utility-sub-type|embedded-browser-webview|webview-exe-name|webview-exe-version|disable-features|enable-features|disable-background-networking|disable-component-update|disable-domain-reliability|disable-sync|disable-gpu|disable-breakpad|no-pings|no-proxy-server|renderer-process-limit|lang|noerrdialogs|embedded-browser-webview-dpi-awareness|remote-debugging-port)$'
function Get-AllowedFlags([string]$cmd) {
  if (-not $cmd) { return @() }
  $o = @()
  foreach ($m in [regex]::Matches($cmd, '--[^\s=]+(?:=(?:"[^"]*"|\S*))?')) { if (($m.Value -split '=', 2)[0] -match $allowSwitch) { $o += $m.Value } }
  return $o
}

# ---------------------------------------------------------------- capture per window (F4) + attribution control (F6)
$providers = [ordered]@{ tcpip = 'Microsoft-Windows-TCPIP'; kernnet = '{7DD42A49-5329-4832-8DFD-43D979153A88}' }   # Kernel-Network adds send/recv byte counts (no payload)
if ($IncludeDns) { $providers['dns'] = 'Microsoft-Windows-DNS-Client' }
$openSessions = New-Object System.Collections.Generic.List[string]
$inst = @{}; $sock = @{}; $udp = @{}
$caps = @{}; $fatal = @()
function Invoke-SelfProbe {   # a loopback TCP connection made by THIS process: every provider must attribute it to this PID
  $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start()
  try {
    $c = [Net.Sockets.TcpClient]::new(); $c.Connect([Net.IPAddress]::Loopback, $l.LocalEndpoint.Port); $s = $l.AcceptTcpClient()
    $b = [byte[]](1..32); $c.GetStream().Write($b, 0, 32); $c.GetStream().Flush(); $buf = New-Object byte[] 32; [void]$s.GetStream().Read($buf, 0, 32)
    $s.Close(); $c.Close()
  } finally { $l.Stop() }
  return [DateTime]::UtcNow
}
function Start-Capture([string]$label, [int]$i) {
  $c = [ordered]@{ label = $label; index = $i + 1; sessions = @(); files = @{}; reasons = @(); probes = @(); start = $null; end = $null; prov = [ordered]@{}; ok = $true }
  foreach ($k in $providers.Keys) {
    $name = "$id-w$($i + 1)-$k"; $etl = Join-Path $RawRun "w$($i + 1)-$k.etl"; $c.files[$k] = $etl
    if ($DryRun) { continue }
    Invoke-Sys $Logman @('create', 'trace', $name, '-p', $providers[$k], '0xFFFFFFFFFFFFFFFF', '0x5', '-o', $etl, '-ets', '-f', 'bin', '-max', "$MaxMB", '-bs', '256', '-nb', '32', '128') "logman create $name" | Out-Null
    $script:openSessions.Add($name); $c.sessions += $name
  }
  $c.start = [DateTime]::UtcNow
  $c.probes += (Invoke-SelfProbe)
  Say "capture $label started ($(if ($DryRun) { 'dry run' } else { $c.sessions -join ', ' }))"
  return $c
}
function Stop-Capture($c) {
  $c.probes += (Invoke-SelfProbe); Start-Sleep -Milliseconds 1200
  $c.end = [DateTime]::UtcNow
  foreach ($n in $c.sessions) {   # lost events are verified later from the ETL's own EventTrace header (EventsLost), which does not depend on the logman output language
    try { Invoke-Sys $Logman @('stop', $n, '-ets') "logman stop $n" | Out-Null; [void]$script:openSessions.Remove($n) } catch { $c.reasons += "$_"; $c.ok = $false }   # a session that failed to stop stays in the list: the final cleanup retries it
  }
  if (-not $DryRun) { $left = Invoke-Sys $Logman @('query', '-ets') 'logman query'; foreach ($n in $c.sessions) { if ($left -match [regex]::Escape($n)) { $c.reasons += "session $n still listed after stop"; $c.ok = $false } } }
  Say "capture $($c.label) stopped"
}
function Get-Lifetimes {
  $lt = @{}
  foreach ($i in $script:inst.Values) {
    if (-not $lt.ContainsKey($i.pid)) { $lt[$i.pid] = New-Object System.Collections.Generic.List[object] }
    $lt[$i.pid].Add(@(([DateTime]::Parse($i.created)).ToUniversalTime().AddSeconds(-2), ([DateTime]::Parse($i.lastSeen)).ToUniversalTime().AddSeconds(2)))
  }
  return $lt
}
function New-SyntheticCsv([string]$csv, $c, [string]$prov) {   # -DryRun only: tracerpt layout, with the rows the filters must keep / drop
  $h = ($CsvColumns | ForEach-Object { '  ' + $_ }) -join ','
  if ($DryRunFault -eq 'csv-header') { $h = ($CsvColumns[0..18] | ForEach-Object { '  ' + $_ }) -join ',' }
  $first = $script:inst.Values | Where-Object { $_.pid -ne $PID } | Select-Object -First 1   # never this script's own PID (that one is the attribution probe)
  $mine = if ($first) { [int]$first.pid } else { 4242 }
  $mk = { param($pidv, $t, $d) ('  Ev, 0, 1, 0, 11, 5, 0, 0, 0x0, 0x{0:X8}, 0x1, 0, , , {{0}}, , {1}, 1, 1, {2}' -f $pidv, ([DateTime]$t).ToFileTimeUtc(), $d) }
  $lostN = if ($DryRunFault -eq 'events-lost') { 17 } else { 0 }
  $rows = @($h, ('  EventTrace, Header, 0, 2, 0, 0, 0, 0, 0x0, 0x00000001, 0x1, 0, , , {0}, , ' + $c.start.ToFileTimeUtc() + ', 1, 1, 8192, 83951626, 26100, 16, ' + $c.end.ToFileTimeUtc() + ', 156250, 0, 0x0, 29, 1, 8, ' + $lostN + ', 3793, 0xA, 0x7'))
  if ($DryRunFault -ne 'provider-empty') {
    $rows += (& $mk 1 $c.start.AddMilliseconds(100) 'OTHER-PID-first')
    $rows += (& $mk 1 $c.end.AddMilliseconds(-100) 'OTHER-PID-last')
    $rows += (& $mk $mine $c.start.AddSeconds(1) 'KEEP-ME -> 52.98.189.226:443')
    $rows += (& $mk $mine $c.start.AddDays(-30) 'REUSED-PID-OLD-INSTANCE')
    if ($prov -eq 'dns') { $rows += (& $mk 57005 $c.start.AddSeconds(1) 'OTHER-PID-DNS-SAME-IP 52.98.189.226') }
    if ($DryRunFault -ne 'no-selfprobe') { foreach ($p in $c.probes) { $rows += (& $mk $PID $p ('selfprobe ' + $prov)) } }
  }
  [IO.File]::WriteAllLines($csv, $rows)
}
function Read-CsvFiltered([string]$csv, [string]$dst, $c, $lt) {   # one pass: schema, event/attribution/time statistics, filtered output
  $st = [ordered]@{ headerOk = $false; eventRows = 0; parseErrors = 0; firstEvent = $null; lastEvent = $null; selfProbeRows = 0; keptRows = 0; eventsLost = $null }
  $w = [IO.StreamWriter]::new($dst, $false, [Text.UTF8Encoding]::new($false)); $n = 0
  try {
    foreach ($line in [IO.File]::ReadLines($csv)) {
      $n++
      if ($n -eq 1) { $st.headerOk = Test-CsvHeader $line; if (-not $st.headerOk) { break }; $w.WriteLine('utc_time,window,' + $line); continue }
      $f = $line.Split(',', 18)
      if ($f.Count -lt 18) { $st.parseErrors++; continue }
      if ($f[0].Trim() -eq 'EventTrace') {
        if ($f[1].Trim() -eq 'Header') { $ud = $f[17].Split(','); if ($ud.Count -ge 14) { $lost = 0L; if ([long]::TryParse($ud[13].Trim(), [ref]$lost)) { $st.eventsLost = $lost } } }   # remainder = Kernel(ms), User(ms), then the TRACE_LOGFILE_HEADER dump: BufferSize, Version, ProviderVersion, Processors, EndTime, TimerRes, MaxFileSize, LogFileMode, BuffersWritten, StartBuffers, PointerSize, EventsLost (index 13, verified on real tracerpt output)
        continue
      }
      $pidv = 0; $t = $null
      try { $pidv = [Convert]::ToInt32($f[9].Trim().Replace('0x', ''), 16); $t = [DateTime]::FromFileTimeUtc([int64]$f[16].Trim()) } catch { $st.parseErrors++; continue }
      $st.eventRows++
      if (-not $st.firstEvent -or $t -lt $st.firstEvent) { $st.firstEvent = $t }
      if (-not $st.lastEvent -or $t -gt $st.lastEvent) { $st.lastEvent = $t }
      if ($pidv -eq $PID -and $t -ge $c.probes[0].AddSeconds(-2) -and $t -le $c.probes[$c.probes.Count - 1].AddSeconds(2)) { $st.selfProbeRows++; continue }
      if (-not $lt.ContainsKey($pidv)) { continue }
      $okLife = $false; foreach ($x in $lt[$pidv]) { if ($t -ge $x[0] -and $t -le $x[1]) { $okLife = $true; break } }
      if (-not $okLife) { continue }
      $w.WriteLine((Iso $t) + ',' + $c.label + ',' + $line); $st.keptRows++
    }
  } finally { $w.Dispose() }
  return $st
}
function Complete-Capture($c) {   # convert + verify every provider; any gap makes the window (and the run) INCOMPLETE
  $lt = Get-Lifetimes
  $cap = [Math]::Floor($MaxMB * 1MB * 0.95)
  Push-Location $RawRun   # tracerpt writes summary.txt/dumpfile.csv into the CWD: keep them in the admin-only folder
  try {
    foreach ($k in $providers.Keys) {
      $etl = $c.files[$k]; $csv = Join-Path $RawRun "w$($c.index)-$k.csv"; $p = [ordered]@{ etlBytes = 0; headerOk = $false; eventsLost = $null; eventRows = 0; keptRows = 0; selfProbeRows = 0; firstEventLagS = $null; lastEventLagS = $null }
      try {
        if ($DryRun) {
          if ($DryRunFault -ne 'etl-missing') { [IO.File]::WriteAllBytes($etl, [byte[]](1..64)); if ($DryRunFault -eq 'truncated') { $fs = [IO.File]::OpenWrite($etl); $fs.SetLength([long]($cap + 1)); $fs.Dispose() } }
          if (Test-Path -LiteralPath $etl) { New-SyntheticCsv $csv $c $k }
        }
        if (-not (Test-Path -LiteralPath $etl -PathType Leaf)) { throw "no ETL produced for $k" }
        $p.etlBytes = (Get-Item -LiteralPath $etl).Length
        if ($p.etlBytes -le 0) { throw "ETL for $k is empty" }
        if ($p.etlBytes -ge $cap) { throw "ETL for $k reached the size cap ($($p.etlBytes) bytes): events were probably dropped" }
        if (-not $DryRun) { Invoke-Sys $Tracerpt @($etl, '-of', 'CSV', '-o', $csv, '-y') "tracerpt $k" | Out-Null }
        if (-not (Test-Path -LiteralPath $csv -PathType Leaf)) { throw "tracerpt produced no CSV for $k" }
        $st = Read-CsvFiltered $csv (Join-Path $Report "etw_$($c.label)_$k.filtered.csv") $c $lt
        $p.headerOk = $st.headerOk; $p.eventRows = $st.eventRows; $p.keptRows = $st.keptRows; $p.selfProbeRows = $st.selfProbeRows
        if (-not $st.headerOk) { throw "CSV header of $k does not match the tracerpt schema" }
        if ($null -eq $st.eventsLost) { throw "provider ${k}: no readable EventTrace header row, lost events cannot be verified" }
        $p.eventsLost = $st.eventsLost
        if ($st.eventsLost -gt 0) { throw "provider $k lost $($st.eventsLost) events (ETW buffers overflowed): the evidence is incomplete" }
        if ($st.eventRows -lt 1) { throw "provider $k delivered no events in this window" }
        if ($st.parseErrors -gt [Math]::Max(2, $st.eventRows / 100)) { throw "provider $k CSV has $($st.parseErrors) unparsable rows" }
        $p.firstEventLagS = [Math]::Round(($st.firstEvent - $c.start).TotalSeconds, 1); $p.lastEventLagS = [Math]::Round(($c.end - $st.lastEvent).TotalSeconds, 1)
        if ($k -ne 'dns' -and ($p.firstEventLagS -gt 5 -or $p.lastEventLagS -gt 5)) { throw "provider $k does not cover the whole window (first event +$($p.firstEventLagS) s, last event -$($p.lastEventLagS) s)" }
        if ($k -in 'tcpip', 'kernnet' -and $st.selfProbeRows -lt 1) { throw "attribution control failed: this script's own loopback connection is not visible under its PID in $k" }
      } catch { $c.reasons += "$($c.label)/${k}: $_"; $c.ok = $false }
      $c.prov[$k] = $p
    }
  } finally { Pop-Location }
}

# ---------------------------------------------------------------- main loop: sample the process trees, drive one capture per window
$t0 = Get-Date; $t0u = [DateTime]::UtcNow
$deadline = $t0.AddSeconds($(if ($DryRun) { [Math]::Min($MaxSeconds, 180) } else { $MaxSeconds }))
$current = $null; $labelIdx = 0; $reason = 'time cap'; $samplerErrors = 0
try {
  while ((Get-Date) -lt $deadline) {
    if (Test-FlagFile 'abort.flag') { $reason = 'abort.flag'; break }
    if (Test-FlagFile 'scenario_done.flag') { $reason = 'scenario_done.flag'; break }
    try {
      if (-not $current -and $labelIdx -lt $Labels.Count) {
        if (Test-FlagFile "$($Labels[$labelIdx]).start") { $current = Start-Capture $Labels[$labelIdx] $labelIdx }
      } elseif ($current) {
        $over = ([DateTime]::UtcNow - $current.start).TotalSeconds -gt 900
        if ((Test-FlagFile "$($current.label).end") -or $over) {
          if ($over) { $current.reasons += "$($current.label): no .end flag within 900 s"; $current.ok = $false }
          Stop-Capture $current; Complete-Capture $current; $caps[$current.label] = $current; $current = $null; $labelIdx++
        }
      }
    } catch { $fatal += "capture control: $(Get-Safe "$_" 300)"; Say "FATAL $(Get-Safe "$_" 300)"; $reason = 'fatal'; break }
    try {   # read-only sampling of the tracked process trees and their non-loopback sockets; an error here is counted, never fatal for the capture
    $all = @(Get-CimInstance Win32_Process)
    $tr = @{}
    foreach ($p in $all) { if ($p.ExecutablePath -and ($roots -contains [IO.Path]::GetFullPath($p.ExecutablePath))) { $tr[[int]$p.ProcessId] = $p } }
    do { $n = $tr.Count
      foreach ($p in $all) { $pp = [int]$p.ParentProcessId; if (-not $tr.ContainsKey([int]$p.ProcessId) -and $tr.ContainsKey($pp) -and $p.CreationDate -ge $tr[$pp].CreationDate) { $tr[[int]$p.ProcessId] = $p } }   # a child must be younger than its parent (PPID reuse)
    } while ($tr.Count -ne $n)
    $now = Iso (Get-Date)
    foreach ($p in $tr.Values) {
      $key = "$([int]$p.ProcessId)|$(Iso $p.CreationDate)"
      if (-not $inst.ContainsKey($key)) {
        $ver = ''; try { if ($p.ExecutablePath) { $ver = (Get-Item -LiteralPath $p.ExecutablePath).VersionInfo.FileVersion } } catch { }
        $inst[$key] = [ordered]@{ pid = [int]$p.ProcessId; ppid = [int]$p.ParentProcessId; name = $p.Name; created = (Iso $p.CreationDate); exeVersion = $ver; flags = (Get-AllowedFlags $p.CommandLine); firstSeen = $now }
      }
      $inst[$key].lastSeen = $now
    }
    $ids = New-Object 'System.Collections.Generic.HashSet[int]'; $tr.Keys | ForEach-Object { [void]$ids.Add([int]$_) }
    foreach ($c in (Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $ids.Contains([int]$_.OwningProcess) -and $_.RemoteAddress -notin '0.0.0.0', '::', '127.0.0.1', '::1' })) {
      $k = "$($c.OwningProcess)|$(Iso $tr[[int]$c.OwningProcess].CreationDate)|$($c.LocalPort)|$($c.RemoteAddress):$($c.RemotePort)|$($c.State)"
      if (-not $sock.ContainsKey($k)) { $sock[$k] = [ordered]@{ pid = [int]$c.OwningProcess; procCreated = (Iso $tr[[int]$c.OwningProcess].CreationDate); localPort = [int]$c.LocalPort; remote = "$($c.RemoteAddress):$($c.RemotePort)"; state = "$($c.State)"; firstSeen = $now } }
      $sock[$k].lastSeen = $now
    }
    foreach ($u in (Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $ids.Contains([int]$_.OwningProcess) })) {
      $k = "$($u.OwningProcess)|$($u.LocalPort)"
      if (-not $udp.ContainsKey($k)) { $udp[$k] = [ordered]@{ pid = [int]$u.OwningProcess; localPort = [int]$u.LocalPort; firstSeen = $now } }
    }
    } catch { $samplerErrors++; if ($samplerErrors -le 3) { Say "sampler error: $(Get-Safe "$_" 200)" } }
    Start-Sleep -Milliseconds 500
  }
  Say "loop ended: $reason after $([int]((Get-Date) - $t0).TotalSeconds) s"
  if ($current) { $current.reasons += "$($current.label): run ended before its .end flag"; $current.ok = $false; try { Stop-Capture $current; Complete-Capture $current } catch { $fatal += "closing open window: $_" }; $caps[$current.label] = $current; $current = $null }
}
finally {
  foreach ($n in @($openSessions)) { try { Invoke-Sys $Logman @('stop', $n, '-ets') "logman stop $n" | Out-Null } catch { Say "stop failed: $n" }; [void]$openSessions.Remove($n) }   # ONLY this run's sessions
}
$cleanNote = 'dry run'
if (-not $DryRun) { $left = Invoke-Sys $Logman @('query', '-ets') 'logman query'; $cleanNote = if ($left -match [regex]::Escape($id)) { "WARNING: session(s) with prefix $id still listed" } else { "no session with prefix $id remains" } }
Say "cleanup: $cleanNote"

# ---------------------------------------------------------------- verdict: COMPLETE only when every check passed
$reasons = @($fatal)
foreach ($l in $Labels) {
  if (-not $caps.ContainsKey($l)) { $reasons += "window $l was never captured"; continue }
  $c = $caps[$l]; $reasons += $c.reasons
  if (($c.end - $c.start).TotalSeconds -lt $MinWindowSeconds) { $reasons += "$l captured only $([int]($c.end - $c.start).TotalSeconds) s (< $MinWindowSeconds)" }
  # something must really have been watched: a tracked process tree AND its browser process alive during this window (a wrong -RootExe form must not read as "no connections")
  $live = @($inst.Values | Where-Object { ([DateTime]::Parse($_.created)).ToUniversalTime() -le $c.end -and ([DateTime]::Parse($_.lastSeen)).ToUniversalTime().AddSeconds(2) -ge $c.start })
  if ($live.Count -lt 1) { $reasons += "$l : no tracked process instance was alive during the capture (check -RootExe)" }
  elseif (@($live | Where-Object { $_.name -ieq $BrowserProcessName -and -not (@($_.flags) -match '^--type=') }).Count -lt 1) { $reasons += "$l : no tracked $BrowserProcessName browser process was alive during the capture" }
}
if ($samplerErrors -gt 20) { $reasons += "the process/socket sampler failed $samplerErrors times" }
$markerErrs = @(Test-MarkerFile (Join-Path $Out 'markers.jsonl') $Labels $MinWindowSeconds $caps $t0u.AddSeconds(-5) | ForEach-Object { Get-Safe $_ })
$reasons += $markerErrs
$reasons = @($reasons | ForEach-Object { Get-Safe "$_" 400 })
$verdict = if ($reasons.Count -eq 0) { 'COMPLETE' } else { 'INCOMPLETE' }
$winSummary = @()
foreach ($l in $Labels) {
  if (-not $caps.ContainsKey($l)) { continue }
  $c = $caps[$l]
  $s = @($sock.Values | Where-Object { ([DateTime]::Parse($_.firstSeen)).ToUniversalTime() -le $c.end -and ([DateTime]::Parse($_.lastSeen)).ToUniversalTime() -ge $c.start })
  $winSummary += [ordered]@{ label = $l; captureStartUtc = (Iso $c.start); captureEndUtc = (Iso $c.end); seconds = [int]($c.end - $c.start).TotalSeconds; ok = $c.ok
    sampledNonLoopbackSockets = $s.Count; sampledEstablished = @($s | Where-Object { $_.state -eq 'Established' }).Count; providers = $c.prov }
}

# ---------------------------------------------------------------- report (filtered only) and retention
@($inst.Values) | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Report 'process_tree.json') -Encoding UTF8
@($sock.Values) | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Report 'tcp_sockets_timeline.json') -Encoding UTF8
@($udp.Values) | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Report 'udp_endpoints.json') -Encoding UTF8
$wv = ''; try { $wv = (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction Stop).pv } catch { }
$delAfter = (Get-Date).ToUniversalTime().AddHours(24)
[ordered]@{
  scriptSha256 = $selfHash; runId = $id; dryRun = [bool]$DryRun; dryRunFault = $DryRunFault; startedUtc = (Iso $t0); finishedUtc = (Iso (Get-Date)); endReason = $reason
  os = [Environment]::OSVersion.VersionString; psVersion = $PSVersionTable.PSVersion.ToString(); webview2Runtime = $wv; providers = @($providers.Values); dnsIncluded = [bool]$IncludeDns
  maxSeconds = $MaxSeconds; maxMB = $MaxMB; labels = $Labels; minWindowSeconds = $MinWindowSeconds; windowsRequested = $Labels.Count; windowsCaptured = $caps.Count
  rootExeSha256 = $rootExeHashes; browserProcessName = $BrowserProcessName; samplerErrors = $samplerErrors; trackedProcessInstances = $inst.Count
  verdict = $verdict; reasons = $reasons; markers = [ordered]@{ valid = ($markerErrs.Count -eq 0); errors = $markerErrs }
  windows = $winSummary; cleanup = $cleanNote; rawRetentionDeleteAfterUtc = (Iso $delAfter)
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Report 'run_info.json') -Encoding UTF8
"Raw trace of run $id. Contains machine-wide network metadata. Local only, admin-only, never upload, never give to the AI agent.`r`nDelete after $(Iso $delAfter) (Owner): Remove-Item -LiteralPath '$RawRun' -Recurse -Force" | Set-Content -LiteralPath (Join-Path $RawRun 'RETENTION.txt')
if ($DeleteRaw -or $DryRun) { Remove-OwnedRunDir $RawRun $RawBase 'strict'; Say "raw deleted: $RawRun" } else { Say "raw kept (admin-only, retention 24 h, Owner deletes): $RawRun" }
$log | Set-Content -LiteralPath (Join-Path $Report 'run_log.txt') -Encoding UTF8
Say "Report (filtered only) in $Report ; verdict $verdict"
exit $(if ($verdict -eq 'COMPLETE') { 0 } else { 2 })
