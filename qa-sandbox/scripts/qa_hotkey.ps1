# QA inside Windows Sandbox (disposable VM). SYNTHETIC ONLY, no vault is created or opened.
# Question: does the REAL global hotkey Ctrl+Alt+V, delivered through the OS input queue (SendInput, scan codes = what a keyboard driver produces),
# make the app show its Quick Access window? ShowWindow is NOT used anywhere in this script.
# Positive control first: a throw-away RegisterHotKey listener (Ctrl+Alt+B) proves that injected keys DO trigger global hotkeys in this VM.
# Also records the sleep states the VM supports (powercfg /a): suspend/resume of the guest is only meaningful if it lists them.
$ErrorActionPreference = 'Continue'
$OUT = 'C:\out'; $CAND = 'C:\cand'
New-Item -ItemType Directory -Force $OUT | Out-Null
$log = Join-Path $OUT 'qa_hotkey_log.txt'
function Log($m) { "$(Get-Date -Format 'HH:mm:ss.fff') $m" | Tee-Object -FilePath $log -Append | Out-Null }
$result = [ordered]@{ startedUtc = (Get-Date).ToUniversalTime().ToString('o') }
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Text; using System.Windows.Forms; using System.Collections.Generic;
public class HK : NativeWindow {
  public int hits = 0;
  public HK() { CreateHandle(new CreateParams()); }
  protected override void WndProc(ref Message m) { if (m.Msg == 0x312) hits++; base.WndProc(ref m); }
  [DllImport("user32.dll", SetLastError=true)] public static extern bool RegisterHotKey(IntPtr h, int id, uint mod, uint vk);
  [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr h, int id);
  [StructLayout(LayoutKind.Sequential)] struct KI { public ushort vk; public ushort scan; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Explicit, Size=40)] struct IN { [FieldOffset(0)] public uint type; [FieldOffset(8)] public KI ki; }
  [DllImport("user32.dll", SetLastError=true)] static extern uint SendInput(uint n, IN[] i, int size);
  public static uint Key(ushort scan, bool up) { var a = new IN[1]; a[0].type = 1; a[0].ki.scan = scan; a[0].ki.flags = 0x8u | (up ? 0x2u : 0u); return SendInput(1, a, Marshal.SizeOf(typeof(IN))); }
  public static uint KeyVk(ushort vk, bool up) { var a = new IN[1]; a[0].type = 1; a[0].ki.vk = vk; a[0].ki.flags = (up ? 0x2u : 0u); return SendInput(1, a, Marshal.SizeOf(typeof(IN))); }
  // Ctrl+Alt+<scan>  via scan codes (Ctrl 1D, Alt 38)
  public static void Chord(ushort scan) { Key(0x1D, false); Key(0x38, false); Key(scan, false); Key(scan, true); Key(0x38, true); Key(0x1D, true); }
  public static void ChordVk(ushort vk) { KeyVk(0x11, false); KeyVk(0x12, false); KeyVk(vk, false); KeyVk(vk, true); KeyVk(0x12, true); KeyVk(0x11, true); }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern IntPtr OpenInputDesktop(int f, bool i, int a);
  [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr d);
  public static bool InputDesktop() { var h = OpenInputDesktop(0, false, 1); if (h == IntPtr.Zero) return false; CloseDesktop(h); return true; }
  public static IntPtr Find(string title) { IntPtr f = IntPtr.Zero; EnumWindows((h, l) => { var sb = new StringBuilder(256); GetWindowText(h, sb, 256); if (sb.ToString() == title) { f = h; return false; } return true; }, IntPtr.Zero); return f; }
  public static string Foreground() { var sb = new StringBuilder(256); GetWindowText(GetForegroundWindow(), sb, 256); return sb.ToString(); }
}
"@
function Pump([int]$ms) { $end = (Get-Date).AddMilliseconds($ms); while ((Get-Date) -lt $end) { [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 20 } }

$result.env = [ordered]@{ os = (Get-CimInstance Win32_OperatingSystem).Caption; build = (Get-CimInstance Win32_OperatingSystem).Version; user = $env:USERNAME
  inputDesktopOpen = [HK]::InputDesktop(); powercfgAvailableStates = ((powercfg /a 2>&1) -join ' | ') }
Log "env: $($result.env | ConvertTo-Json -Compress)"

# ---- positive control: injected Ctrl+Alt+B must trigger a throw-away global hotkey ----
$w = New-Object HK
$okReg = [HK]::RegisterHotKey($w.Handle, 1, 3, 0x42)
$ctl = [ordered]@{ registered = $okReg }
if ($okReg) {
  [HK]::Chord(0x30); Pump 800; $ctl.scanCodeHits = $w.hits
  [HK]::ChordVk(0x42); Pump 800; $ctl.afterVkHits = $w.hits
  [void][HK]::UnregisterHotKey($w.Handle, 1)
}
$result.positiveControl = $ctl
Log "positive control: $($ctl | ConvertTo-Json -Compress)"

# ---- the app: release candidate, throw-away profile, no vault ----
$local = Join-Path $env:TEMP 'pv-hk'; New-Item -ItemType Directory -Force $local | Out-Null
$env:LOCALAPPDATA = $local; $env:WEBVIEW2_USER_DATA_FOLDER = Join-Path $local 'wv'
$app = Start-Process (Join-Path $CAND 'PersonalVault.exe') -PassThru
$QT = 'Personal Vault - Quick Access'
$mainUp = $false; for ($i = 0; $i -lt 60 -and -not $mainUp; $i++) { Start-Sleep -Milliseconds 500; $mainUp = [HK]::Find('Personal Vault') -ne [IntPtr]::Zero }
$result.app = [ordered]@{ pid = $app.Id; mainWindowUp = $mainUp; quickExistsHidden = ([HK]::Find($QT) -ne [IntPtr]::Zero -and -not [HK]::IsWindowVisible([HK]::Find($QT))) }
Start-Sleep -Seconds 8   # let the quick webview finish loading
$reg = [HK]::RegisterHotKey($w.Handle, 9, 3, 0x56); $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error(); if ($reg) { [void][HK]::UnregisterHotKey($w.Handle, 9) }
$result.app.hotkeyHeldByApp = (-not $reg) -and ($err -eq 1409)
$runs = @()
for ($n = 1; $n -le 4; $n++) {
  $q = [HK]::Find($QT)
  $before = $q -ne [IntPtr]::Zero -and [HK]::IsWindowVisible($q)
  if ($n % 2) { [HK]::Chord(0x2F) } else { [HK]::ChordVk(0x56) }   # odd runs: scan codes, even runs: virtual keys
  $shown = $false; for ($i = 0; $i -lt 20 -and -not $shown; $i++) { Start-Sleep -Milliseconds 200; $shown = [HK]::IsWindowVisible([HK]::Find($QT)) }
  $fg = [HK]::Foreground()
  [HK]::Key(0x01, $false); [HK]::Key(0x01, $true)   # Esc via scan code: the page hides the window
  $hidden = $false; for ($i = 0; $i -lt 20 -and -not $hidden; $i++) { Start-Sleep -Milliseconds 200; $hidden = -not [HK]::IsWindowVisible([HK]::Find($QT)) }
  $runs += [ordered]@{ run = $n; method = $(if ($n % 2) { 'SendInput scan codes' } else { 'SendInput virtual keys' }); visibleBefore = $before; visibleAfterHotkey = $shown; foregroundTitle = $fg; hiddenAfterEsc = $hidden }
  Log "run $n : $($runs[-1] | ConvertTo-Json -Compress)"
  Start-Sleep -Seconds 1
}
$result.hotkeyRuns = $runs
Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
$result.finishedUtc = (Get-Date).ToUniversalTime().ToString('o')
$result | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $OUT 'qa_hotkey_result.json') -Encoding UTF8
'done' | Set-Content (Join-Path $OUT 'done.txt')
Start-Sleep 3; shutdown /s /t 0
