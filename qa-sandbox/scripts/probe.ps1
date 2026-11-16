$o = 'C:\out\probe.txt'
"start $(Get-Date -Format o)" | Out-File $o
"user: $env:USERNAME" | Out-File $o -Append
(Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version | Out-String) | Out-File $o -Append
$wv = Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction SilentlyContinue
"webview2: $($wv.pv)" | Out-File $o -Append
"cand files: " + ((Get-ChildItem C:\cand -ErrorAction SilentlyContinue | ForEach-Object Name) -join ',') | Out-File $o -Append
"admin: " + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) | Out-File $o -Append
"net: " + ((Test-NetConnection -ComputerName 1.1.1.1 -Port 443 -WarningAction SilentlyContinue).TcpTestSucceeded) | Out-File $o -Append
"done" | Out-File $o -Append
Start-Sleep 3
shutdown /s /t 0
