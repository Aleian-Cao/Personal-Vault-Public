param(
  [Parameter(Mandatory)][ValidateSet('shot','dialog','hotkey','hotkeycheck','showwin','winvisible','hidewin','memtree','procinfo','clip','tree','tcp')][string]$Action,
  [string]$Arg1 = '', [string]$Arg2 = ''
)
# Windows helpers for the real-EXE E2E. Synthetic QA only.
#  shot        : capture an app window with PrintWindow (works without an input desktop)
#  dialog      : drive a native file dialog through UI Automation (set File name, press Save)
#  hotkey      : inject a real Ctrl+Alt+V (may be blocked by the session; harness reports that honestly)
#  hotkeycheck : prove Ctrl+Alt+V is already registered system-wide by the app (RegisterHotKey must fail with 1409)
#  showwin     : ShowWindow(SW_SHOW) on a window by title (fallback when hotkey injection is blocked)
Add-Type -AssemblyName System.Drawing, UIAutomationClient, UIAutomationTypes
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Text;
public class W {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", EntryPoint="SendMessageW", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageStr(IntPtr h, uint m, IntPtr w, string l);
  [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr dlg, int id);
  static string Cls(IntPtr h) { var sb = new StringBuilder(256); GetClassName(h, sb, 256); return sb.ToString(); }
  public static string Dump(IntPtr p, int d) {
    var sb = new StringBuilder();
    EnumChildWindows(p, (h, l) => { sb.AppendLine(new string(' ', d * 2) + Cls(h) + " id=" + GetDlgCtrlID(h)); sb.Append(Dump(h, d + 1)); return true; }, IntPtr.Zero);
    return sb.ToString();
  }
  [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
  public static IntPtr FindFileNameEdit(IntPtr dlg) {
    IntPtr found = IntPtr.Zero;
    EnumChildWindows(dlg, (h, l) => {
      if (Cls(h) == "Edit" && GetDlgCtrlID(h) == 1001) { found = h; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string c, string t);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll", SetLastError=true)] public static extern bool RegisterHotKey(IntPtr h, int id, uint mod, uint vk);
  [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr h, int id);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
[void][W]::SetProcessDPIAware()
$AE = [System.Windows.Automation.AutomationElement]

function Find-Window([string]$title) { [W]::FindWindow([NullString]::Value, $title) }

switch ($Action) {
  'shot' {  # Arg1 = exact window title, Arg2 = output png
    $h = Find-Window $Arg1
    if ($h -eq [IntPtr]::Zero) { Write-Output 'NOWINDOW'; exit 2 }
    Start-Sleep -Milliseconds 500
    $r = New-Object W+RECT; [void][W]::GetWindowRect($h, [ref]$r)
    $w = $r.R - $r.L; $ht = $r.B - $r.T
    $bmp = New-Object System.Drawing.Bitmap $w, $ht
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    $ok = [W]::PrintWindow($h, $dc, 2); $g.ReleaseHdc($dc)
    $bmp.Save($Arg2, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
    if ($ok) { Write-Output "OK ${w}x${ht}" } else { Write-Output 'PRINTFAIL'; exit 3 }
  }
  'dialog' {  # Arg1 = dialog title, Arg2 = full path to type into "File name" and confirm
    # The native dialog is a child window of the app's top-level window.
    $PC = 'System.Windows.Automation.PropertyCondition'
    $dlg = $null; $deadline = (Get-Date).AddSeconds(20)
    while (-not $dlg -and (Get-Date) -lt $deadline) {
      $mh = Find-Window 'Personal Vault'
      if ($mh -ne [IntPtr]::Zero) {
        $main = $AE::FromHandle($mh)
        $dlg = $main.FindFirst('Descendants', (New-Object $PC($AE::NameProperty, $Arg1)))
      }
      if (-not $dlg) { Start-Sleep -Milliseconds 300 }
    }
    if (-not $dlg) { Write-Output 'NODIALOG'; exit 3 }
    Start-Sleep -Milliseconds 800
    $dh = [IntPtr]$dlg.Current.NativeWindowHandle
    if ($dh -eq [IntPtr]::Zero) { Write-Output 'NODLGHWND'; exit 3 }
    # Real "File name" control = Edit id 1001 inside a ComboBox (UIA exposes it only as a value-less Pane).
    if ($Arg2 -eq 'DUMP') { [W]::Dump($dh, 0); exit 0 }
    $edit = [W]::FindFileNameEdit($dh)
    if ($edit -eq [IntPtr]::Zero) { Write-Output 'NOEDIT'; exit 4 }
    [void][W]::SendMessageStr($edit, 0x000C, [IntPtr]::Zero, $Arg2)  # WM_SETTEXT
    Start-Sleep -Milliseconds 300
    $sh = [W]::GetDlgItem($dh, 1)  # IDOK = "Save"
    if ($sh -eq [IntPtr]::Zero) {
      $save = $dlg.FindFirst('Descendants', (New-Object $PC($AE::AutomationIdProperty, '1')))
      if ($save) { $sh = [IntPtr]$save.Current.NativeWindowHandle }
    }
    if ($sh -eq [IntPtr]::Zero) { Write-Output 'NOSAVEHWND'; exit 6 }
    [void][W]::PostMessage($sh, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)  # BM_CLICK on the real Save button
    Write-Output 'OK'
  }
  'hotkey' {
    [W]::keybd_event(0x11,0,0,[UIntPtr]::Zero); [W]::keybd_event(0x12,0,0,[UIntPtr]::Zero)
    [W]::keybd_event(0x56,0,0,[UIntPtr]::Zero); [W]::keybd_event(0x56,0,2,[UIntPtr]::Zero)
    [W]::keybd_event(0x12,0,2,[UIntPtr]::Zero); [W]::keybd_event(0x11,0,2,[UIntPtr]::Zero); Write-Output 'OK'
  }
  'hotkeycheck' {  # MOD_ALT|MOD_CONTROL = 3, 'V' = 0x56. Failing with 1409 = already registered by another process.
    $ok = [W]::RegisterHotKey([IntPtr]::Zero, 9001, 3, 0x56)
    $err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
    if ($ok) { [void][W]::UnregisterHotKey([IntPtr]::Zero, 9001) }
    Write-Output "registered_by_other=$((-not $ok) -and ($err -eq 1409)) err=$err"
  }
  'showwin' { $h = Find-Window $Arg1; if ($h -eq [IntPtr]::Zero) { Write-Output 'NOWINDOW'; exit 2 }; [void][W]::ShowWindow($h, 5); Write-Output 'OK' }
  'winvisible' { $h = Find-Window $Arg1; if ($h -eq [IntPtr]::Zero) { 'False' } else { [string][W]::IsWindowVisible($h) } }
  'hidewin' { $h = Find-Window $Arg1; if ($h -eq [IntPtr]::Zero) { Write-Output 'NOWINDOW'; exit 2 }; [void][W]::ShowWindow($h, 0); Write-Output 'OK' }
  'memtree' {  # Arg1 = root pid -> JSON: per-process Working Set, Private Bytes (commit), Private Working Set, role
    $all = Get-CimInstance Win32_Process
    $ids = New-Object System.Collections.Generic.HashSet[int]; [void]$ids.Add([int]$Arg1)
    do { $n = $ids.Count; foreach ($p in $all) { if ($ids.Contains([int]$p.ParentProcessId)) { [void]$ids.Add([int]$p.ProcessId) } } } while ($ids.Count -ne $n)
    $perf = @{}; Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | ForEach-Object { $perf[[int]$_.IDProcess] = $_ }
    $all | Where-Object { $ids.Contains([int]$_.ProcessId) } | ForEach-Object {
      $cl = [string]$_.CommandLine; $role = $_.Name
      if ($_.Name -eq 'msedgewebview2.exe') {
        if ($cl -match '--type=([\w-]+)') { $role = $Matches[1] } else { $role = 'browser' }
        if ($cl -match '--utility-sub-type=([\w\.]+)') { $role += ':' + ($Matches[1] -replace 'network.mojom.','') }
      } elseif ($_.Name -eq 'pvault-sidecar.exe') { $role = if ([int]$_.ParentProcessId -eq [int]$Arg1) { 'sidecar-bootloader' } else { 'sidecar-python' } }
      elseif ($_.ProcessId -eq [int]$Arg1) { $role = 'app(rust)' }
      $pf = $perf[[int]$_.ProcessId]
      [pscustomobject]@{ pid = $_.ProcessId; name = $_.Name; role = $role
        wsMB = [math]::Round($_.WorkingSetSize/1MB,1); privateMB = [math]::Round($_.PrivatePageCount/1MB,1)
        wsPrivateMB = if ($pf) { [math]::Round($pf.WorkingSetPrivate/1MB,1) } else { $null } }
    } | ConvertTo-Json -Compress
  }
  'procinfo' {  # Arg1 = pid -> JSON with start time, parent, command line and executable version
    $q = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$Arg1)" -ErrorAction SilentlyContinue
    if (-not $q) { '{}'; exit 0 }
    $v = try { (Get-Item $q.ExecutablePath).VersionInfo.ProductVersion } catch { '' }
    [pscustomobject]@{ pid = $q.ProcessId; ppid = $q.ParentProcessId; name = $q.Name; created = $q.CreationDate.ToString('o'); exeVersion = $v
      cmd = $(if ($q.CommandLine) { $q.CommandLine.Substring(0, [Math]::Min(900, $q.CommandLine.Length)) } else { '' }) } | ConvertTo-Json -Compress
  }
  'clip' { $c = Get-Clipboard -Raw; if ($null -eq $c) { '' } else { $c.TrimEnd("`r","`n") } }
  'tree' {  # Arg1 = root pid -> JSON [{pid,name,wsMB}] for the whole process tree
    $all = Get-CimInstance Win32_Process
    $ids = New-Object System.Collections.Generic.HashSet[int]; [void]$ids.Add([int]$Arg1)
    do { $n = $ids.Count; foreach ($p in $all) { if ($ids.Contains([int]$p.ParentProcessId)) { [void]$ids.Add([int]$p.ProcessId) } } } while ($ids.Count -ne $n)
    $all | Where-Object { $ids.Contains([int]$_.ProcessId) } |
      ForEach-Object { [pscustomobject]@{ pid = $_.ProcessId; name = $_.Name; wsMB = [math]::Round($_.WorkingSetSize/1MB,1) } } | ConvertTo-Json -Compress
  }
  'tcp' {  # Arg1 = comma-separated pids -> JSON of their TCP/UDP endpoints
    $ids = $Arg1.Split(',') | ForEach-Object { [int]$_ }
    $t = Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess } |
      ForEach-Object { [pscustomobject]@{ pid = $_.OwningProcess; proto = 'tcp'; local = "$($_.LocalAddress):$($_.LocalPort)"; remote = "$($_.RemoteAddress):$($_.RemotePort)"; state = "$($_.State)" } }
    $u = Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess } |
      ForEach-Object { [pscustomobject]@{ pid = $_.OwningProcess; proto = 'udp'; local = "$($_.LocalAddress):$($_.LocalPort)"; remote = ''; state = '' } }
    @($t) + @($u) | ConvertTo-Json -Compress
  }
}
