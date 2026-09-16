# Frankfurt Proxy Tray + Desktop shield toggle (stable shortcuts)
param(
  [switch]$Toggle,
  [switch]$StartOn
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$AppTitle = 'Proxy PC'
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GostPath = Join-Path $AppDir 'proxy-helper.exe'
$GostSourceName = 'proxy-helper.exe'
$SshPath = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
$IconOn = Join-Path $AppDir 'on.ico'
$IconOff = Join-Path $AppDir 'off.ico'
$ShieldBlue = Join-Path $AppDir 'shield-blue.ico'
$ShieldGreen = Join-Path $AppDir 'shield-green.ico'
$DesktopShield = Join-Path $AppDir 'desktop-shield.ico'
$VpsHost = '185.125.103.179'
$SsPort = 443
$SsMethod = 'chacha20-ietf-poly1305'
# SS mode not used in current SSH-only build; do not publish live Outline passwords in git.
$SsPassword = ''
$StateFile = Join-Path $AppDir 'state.json'
$CmdFile = Join-Path $AppDir 'command.txt'
$MutexName = 'Local\ProxyPCTrayMutex'
$PowerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$WScriptExe = Join-Path $env:SystemRoot 'System32\wscript.exe'
$Ps1Path = Join-Path $AppDir 'ProxyPC.ps1'
$VbsToggle = Join-Path $AppDir 'ProxyPC.vbs'
$VbsTray = Join-Path $AppDir 'ProxyPC-Tray.vbs'
$ToggleArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Ps1Path`" -Toggle"

$script:SshProc = $null
$script:GostProc = $null
$script:IsOn = $false
$script:ReconnectTries = 0
$script:ProxyMode = 'ssh'
$script:LastReconnectAt = [datetime]::MinValue

function Write-State {
  @{ on = [bool]$script:IsOn; updated = (Get-Date).ToString('s') } | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
}

function Get-DesktopDirs {
  $dirs = New-Object System.Collections.Generic.List[string]
  foreach ($d in @(
      [Environment]::GetFolderPath('Desktop'),
      (Join-Path $env:USERPROFILE 'OneDrive\Desktop'),
      (Join-Path $env:USERPROFILE 'Desktop')
    )) {
    if ($d -and (Test-Path $d) -and -not $dirs.Contains($d)) { [void]$dirs.Add($d) }
  }
  return ,@($dirs.ToArray())
}

function Ensure-DesktopShortcut {
  if (-not (Test-Path $DesktopShield)) {
    $seed = if (Test-Path $ShieldBlue) { $ShieldBlue } else { $IconOff }
    if (Test-Path $seed) { Copy-Item $seed $DesktopShield -Force }
  }
  if (-not (Test-Path $DesktopShield)) { return }
  if (-not (Test-Path $Ps1Path)) { return }
  if (-not (Test-Path $PowerShellExe)) { return }

  $lnkPaths = New-Object System.Collections.Generic.List[string]
  foreach ($desk in (Get-DesktopDirs)) {
    [void]$lnkPaths.Add((Join-Path $desk 'Proxy PC.lnk'))
    $old = Join-Path $desk 'Amsterdam Proxy.lnk'
    if (Test-Path $old) { Remove-Item $old -Force -ErrorAction SilentlyContinue }
  }
  $startDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Proxy PC'
  $oldStart = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Amsterdam Proxy'
  if (Test-Path $oldStart) {
    try { Remove-Item $oldStart -Recurse -Force -ErrorAction SilentlyContinue } catch {}
  }
  if (-not (Test-Path $startDir)) { New-Item -ItemType Directory -Force -Path $startDir | Out-Null }
  [void]$lnkPaths.Add((Join-Path $startDir 'Proxy PC.lnk'))

  $w = New-Object -ComObject WScript.Shell
  foreach ($lnkPath in $lnkPaths) {
    $need = $true
    $wantIcon = "$DesktopShield,0"
    $preferVbs = $false
    if (Test-Path $lnkPath) {
      try {
        $cur = $w.CreateShortcut($lnkPath)
        $okTarget = $false
        if ($cur.TargetPath -eq $WScriptExe -and $cur.Arguments -like '*ProxyPC.vbs*') {
          $okTarget = $true
          $preferVbs = $true
        } elseif ($cur.TargetPath -eq $PowerShellExe -and $cur.Arguments -like '*-Toggle*' -and $cur.Arguments -like '*ProxyPC.ps1*') {
          $okTarget = $true
          $preferVbs = $false
        }
        if ($okTarget -and $cur.IconLocation -eq $wantIcon -and $cur.Description -eq $AppTitle) { $need = $false }
      } catch { $need = $true }
    } else {
      $preferVbs = $false
    }
    if (-not $need) { continue }
    try {
      $s = $w.CreateShortcut($lnkPath)
      if ($preferVbs -and (Test-Path $VbsToggle) -and (Test-Path $WScriptExe)) {
        $s.TargetPath = $WScriptExe
        $s.Arguments = "//nologo `"$VbsToggle`""
      } else {
        $s.TargetPath = $PowerShellExe
        $s.Arguments = $ToggleArgs
      }
      $s.WorkingDirectory = $AppDir
      $s.WindowStyle = 7
      $s.Description = $AppTitle
      $s.IconLocation = $wantIcon
      $s.Save()
    } catch {}
  }
}

function Update-DesktopShieldIcon([bool]$on) {
  $src = if ($on) { $ShieldGreen } else { $ShieldBlue }
  if (-not (Test-Path $src)) { $src = if ($on) { $IconOn } else { $IconOff } }
  if (-not (Test-Path $src)) { return }
  try { Copy-Item $src $DesktopShield -Force } catch {}
  Ensure-DesktopShortcut
  try {
    if (-not ('Shell32Notify.Native' -as [type])) {
      Add-Type -Namespace Shell32Notify -Name Native -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode)]
public static extern void SHChangeNotify(int wEventId, uint uFlags, System.IntPtr dwItem1, System.IntPtr dwItem2);
[System.Runtime.InteropServices.DllImport("shell32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode)]
public static extern void SHChangeNotify(int wEventId, uint uFlags, [System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] string dwItem1, System.IntPtr dwItem2);
'@
    }
  } catch {}
  try {
    $SHCNE_UPDATEITEM = 0x00002000
    $SHCNF_PATHW = 0x0005
    $SHCNE_ASSOCCHANGED = 0x08000000
    $SHCNF_IDLIST = 0x0000
    foreach ($desk in (Get-DesktopDirs)) {
      $lnk = Join-Path $desk 'Proxy PC.lnk'
      if (Test-Path $lnk) {
        try { [Shell32Notify.Native]::SHChangeNotify($SHCNE_UPDATEITEM, $SHCNF_PATHW, $lnk, [IntPtr]::Zero) } catch {}
      }
    }
    try { [Shell32Notify.Native]::SHChangeNotify($SHCNE_UPDATEITEM, $SHCNF_PATHW, $DesktopShield, [IntPtr]::Zero) } catch {}
    [Shell32Notify.Native]::SHChangeNotify($SHCNE_ASSOCCHANGED, $SHCNF_IDLIST, [IntPtr]::Zero, [IntPtr]::Zero)
  } catch {}
}

function Set-CursorForProxyPc([bool]$enable) {
  # Proxy PC is WinINET-only; Cursor/Electron ignores WinINET unless http.proxy is set.
  # Bebra/Happ/Amnezia use a TUN/TAP — Cursor works with NO http.proxy.
  # Rule: set http://127.0.0.1:8080 only while Proxy PC is ON; on OFF remove keys completely
  # (never leave socks5://127.0.0.1:1080 or a dead proxy).
  $path = Join-Path $env:APPDATA 'Cursor\User\settings.json'
  if (-not (Test-Path $path)) { return }
  try {
    $j = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    $keys = @('http.proxy', 'http.proxySupport', 'http.proxyStrictSSL')
    if ($enable) {
      if (-not (Test-PortOpen 8080)) { return }
      $j | Add-Member -NotePropertyName 'http.proxy' -NotePropertyValue 'http://127.0.0.1:8080' -Force
      $j | Add-Member -NotePropertyName 'http.proxySupport' -NotePropertyValue 'override' -Force
      $j | Add-Member -NotePropertyName 'http.proxyStrictSSL' -NotePropertyValue $false -Force
      $j | Add-Member -NotePropertyName 'cursor.general.disableHttp2' -NotePropertyValue $true -Force
    } else {
      foreach ($k in $keys) {
        if ($j.PSObject.Properties[$k]) { $j.PSObject.Properties.Remove($k) }
      }
    }
    $json = $j | ConvertTo-Json -Depth 30
    [IO.File]::WriteAllText($path, $json, (New-Object Text.UTF8Encoding $false))
  } catch {}
}

function Set-SystemProxy([bool]$enable) {
  $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
  if ($enable) {
    Set-ItemProperty -Path $key -Name ProxyEnable -Value 1
    Set-ItemProperty -Path $key -Name ProxyServer -Value '127.0.0.1:8080'
    Set-ItemProperty -Path $key -Name ProxyOverride -Value 'localhost;127.0.0.1;<local>'
  } else {
    Set-ItemProperty -Path $key -Name ProxyEnable -Value 0
  }
  Set-CursorForProxyPc $enable
  try {
    if (-not ('WinInetProxy.Native' -as [type])) {
      Add-Type -Namespace WinInetProxy -Name Native -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("wininet.dll", SetLastError=true)]
public static extern bool InternetSetOption(System.IntPtr hInternet, int dwOption, System.IntPtr lpBuffer, int dwBufferLength);
'@
    }
    [WinInetProxy.Native]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null
    [WinInetProxy.Native]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null
  } catch {}
}

function Stop-OwnedProcesses {
  foreach ($name in @('gost.exe','proxy-helper.exe')) {
    Get-CimInstance Win32_Process -Filter "Name='$name'" -ErrorAction SilentlyContinue |
      Where-Object {
        $_.CommandLine -and (
          $_.CommandLine -like '*127.0.0.1:8080*' -or
          $_.CommandLine -like "*${VpsHost}:${SsPort}*"
        )
      } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  }
  Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$VpsHost*" -and $_.CommandLine -like '*-D 1080*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  if ($script:GostProc -and -not $script:GostProc.HasExited) { try { $script:GostProc.Kill() } catch {} }
  if ($script:SshProc -and -not $script:SshProc.HasExited) { try { $script:SshProc.Kill() } catch {} }
  $script:GostProc = $null
  $script:SshProc = $null
}

function Test-OwnedSshAlive {
  @(
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and $_.CommandLine -like "*$VpsHost*" -and $_.CommandLine -like '*-D 1080*' }
  ).Count -gt 0
}

function Test-OwnedGostAlive {
  @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        $_.Name -in @('proxy-helper.exe','gost.exe') -and
        $_.CommandLine -and $_.CommandLine -like '*127.0.0.1:8080*'
      }
  ).Count -gt 0
}

function Test-PortOpen([int]$Port) {
  try {
    $c = New-Object Net.Sockets.TcpClient
    $iar = $c.BeginConnect('127.0.0.1', $Port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(800, $false)
    if ($ok -and $c.Connected) { $c.Close(); return $true }
    try { $c.Close() } catch {}
    return $false
  } catch { return $false }
}

function Ensure-ProxyBinaries {
  $helper = Join-Path $AppDir 'proxy-helper.exe'
  $sources = @(
    @(
      $helper,
      'c:\Users\slava\OneDrive\Dokumente\New project 3\outline-vps\AmsterdamProxy\gost.exe',
      (Join-Path $AppDir 'gost.exe')
    ) | Where-Object { $_ -and (Test-Path $_) -and ((Get-Item $_).Length -gt 1000000) } | Select-Object -Unique
  )
  if (@($sources).Count -eq 0) { return $false }
  if (-not (Test-Path $helper) -or ((Get-Item $helper).Length -lt 1000000)) {
    try { Copy-Item -LiteralPath ([string]$sources[0]) -Destination $helper -Force } catch { return $false }
  }
  return (Test-Path $helper)
}

function Get-GostExePath {
  if (-not (Ensure-ProxyBinaries)) { return $null }
  $helper = Join-Path $AppDir 'proxy-helper.exe'
  if (Test-Path $helper) { return $helper }
  return $null
}

function Start-GostHttp([string]$GostPath, [string]$ForwardArgs) {
  $gpsi = New-Object System.Diagnostics.ProcessStartInfo
  $gpsi.FileName = $GostPath
  $gpsi.Arguments = "-L http://127.0.0.1:8080 $ForwardArgs"
  $gpsi.UseShellExecute = $false
  $gpsi.CreateNoWindow = $true
  $gpsi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
  $script:GostProc = [Diagnostics.Process]::Start($gpsi)
  $deadline = (Get-Date).AddSeconds(8)
  while ((Get-Date) -lt $deadline) {
    if (Test-PortOpen 8080) { return $true }
    Start-Sleep -Milliseconds 300
  }
  return $false
}

function Start-ProxyStack {
  # User switches VPN clients manually. Do not wait for / kill other clients.
  if (-not (Ensure-ProxyBinaries)) { throw "proxy-helper.exe not found in $AppDir (antivirus may have removed it)" }
  $GostPath = Get-GostExePath
  if (-not $GostPath) { throw "No proxy binary in $AppDir" }
  if (-not (Test-Path $SshPath)) { throw 'OpenSSH is missing.' }
  Stop-OwnedProcesses

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $SshPath
  $psi.Arguments = "-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -o TCPKeepAlive=yes -o ExitOnForwardFailure=yes -N -D 1080 root@$VpsHost"
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
  $script:SshProc = [Diagnostics.Process]::Start($psi)

  $deadline = (Get-Date).AddSeconds(20)
  while ((Get-Date) -lt $deadline) {
    if (Test-PortOpen 1080) { break }
    if ($script:SshProc -and $script:SshProc.HasExited) { break }
    Start-Sleep -Milliseconds 300
  }
  if (-not (Test-PortOpen 1080)) { throw 'SSH tunnel failed (port 1080).' }

  if (-not (Start-GostHttp $GostPath '-F socks5://127.0.0.1:1080')) {
    throw 'HTTP proxy failed on 8080.'
  }
  $script:ProxyMode = 'ssh'

  Set-SystemProxy $true
  $script:IsOn = $true
  Write-State
  Update-DesktopShieldIcon $true
}

function Stop-ProxyStack {
  Set-SystemProxy $false
  Stop-OwnedProcesses
  $script:IsOn = $false
  Write-State
  Update-DesktopShieldIcon $false
}

function Get-AppIcon([bool]$on) {
  $path = if ($on) {
    if (Test-Path $ShieldGreen) { $ShieldGreen } else { $IconOn }
  } else {
    if (Test-Path $ShieldBlue) { $ShieldBlue } else { $IconOff }
  }
  if (Test-Path $path) {
    try { return New-Object Drawing.Icon $path } catch {}
  }
  $bmp = New-Object Drawing.Bitmap 32,32
  $g = [Drawing.Graphics]::FromImage($bmp)
  $g.Clear([Drawing.Color]::Transparent)
  $color = if ($on) { [Drawing.Color]::FromArgb(34,170,90) } else { [Drawing.Color]::FromArgb(30,100,200) }
  $g.FillEllipse((New-Object Drawing.SolidBrush $color), 2, 2, 28, 28)
  $icon = [Drawing.Icon]::FromHandle($bmp.GetHicon())
  $g.Dispose(); $bmp.Dispose()
  return $icon
}

function Update-Ui {
  $tray.Icon = Get-AppIcon $script:IsOn
  if ($script:IsOn) {
    $tray.Text = "Frankfurt Proxy: ON - $VpsHost"
    $miToggle.Text = 'Turn OFF proxy'
    $miStatus.Text = "Status: ON ($VpsHost)"
  } else {
    $tray.Text = 'Frankfurt Proxy: OFF'
    $miToggle.Text = 'Turn ON proxy'
    $miStatus.Text = 'Status: OFF'
  }
}

function Invoke-Toggle {
  if ($script:IsOn) {
    Stop-ProxyStack
    if ($tray) { $tray.ShowBalloonTip(1800, $AppTitle, 'Proxy OFF', [Windows.Forms.ToolTipIcon]::Info) }
  } else {
    $script:ReconnectTries = 0
    $script:LastReconnectAt = [datetime]::MinValue
    Start-ProxyStack
    if ($tray) { $tray.ShowBalloonTip(2200, $AppTitle, "Proxy ON`n$VpsHost", [Windows.Forms.ToolTipIcon]::Info) }
  }
  if ($tray) { Update-Ui }
  Ensure-DesktopShortcut
}

if ($Toggle) {
  $existing = @(
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and $_.CommandLine -like '*ProxyPC.ps1*' -and $_.CommandLine -notlike '*-Toggle*' }
  )
  if (@($existing).Count -gt 0) {
    Set-Content -Path $CmdFile -Value 'toggle' -Encoding ASCII
    Start-Sleep -Milliseconds 2500
    exit 0
  }
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = $PowerShellExe
  $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Ps1Path`""
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  [void][Diagnostics.Process]::Start($psi)
  Start-Sleep -Milliseconds 1200
  Set-Content -Path $CmdFile -Value 'toggle' -Encoding ASCII
  exit 0
}

$createdNew = $false
$mutex = New-Object Threading.Mutex($true, $MutexName, [ref]$createdNew)
if (-not $createdNew) { exit 0 }

$tray = New-Object Windows.Forms.NotifyIcon
$tray.Visible = $true
$tray.Text = $AppTitle

$menu = New-Object Windows.Forms.ContextMenuStrip
$miStatus = $menu.Items.Add('Status: OFF')
$miStatus.Enabled = $false
$miToggle = $menu.Items.Add('Turn ON proxy')
[void]$menu.Items.Add('-')
$miCopy = $menu.Items.Add('Copy server IP')
$miRepair = $menu.Items.Add('Repair desktop icon')
[void]$menu.Items.Add('-')
$miExit = $menu.Items.Add('Exit')
$tray.ContextMenuStrip = $menu

$miToggle.Add_Click({
  try { Invoke-Toggle } catch {
    try { Stop-ProxyStack } catch {}
    Update-Ui
    [Windows.Forms.MessageBox]::Show("Error:`n$($_.Exception.Message)", $AppTitle, 'OK', 'Error') | Out-Null
  }
})
$miCopy.Add_Click({
  [Windows.Forms.Clipboard]::SetText($VpsHost)
  $tray.ShowBalloonTip(1500, $AppTitle, "Copied: $VpsHost", [Windows.Forms.ToolTipIcon]::Info)
})
$miRepair.Add_Click({
  Ensure-DesktopShortcut
  Update-DesktopShieldIcon $script:IsOn
  $tray.ShowBalloonTip(2000, $AppTitle, 'Desktop icon repaired', [Windows.Forms.ToolTipIcon]::Info)
})
$miExit.Add_Click({
  try { Stop-ProxyStack } catch {}
  $tray.Visible = $false
  $tray.Dispose()
  try { $mutex.ReleaseMutex() } catch {}
  [Windows.Forms.Application]::Exit()
})
$tray.Add_DoubleClick({ $miToggle.PerformClick() })

$timer = New-Object Windows.Forms.Timer
$timer.Interval = 8000
$timer.Add_Tick({
  if (Test-Path $CmdFile) {
    try {
      $cmd = (Get-Content -Path $CmdFile -Raw -ErrorAction SilentlyContinue).Trim()
      Remove-Item $CmdFile -Force -ErrorAction SilentlyContinue
      if ($cmd -eq 'toggle') {
        try { Invoke-Toggle } catch {
          try { Stop-ProxyStack } catch {}
          Update-Ui
          $tray.ShowBalloonTip(3500, $AppTitle, $_.Exception.Message, [Windows.Forms.ToolTipIcon]::Error)
        }
      }
    } catch {}
  }

  if ($script:IsOn) {
    $stackAlive = (Test-OwnedSshAlive) -and (Test-OwnedGostAlive)
    if (-not $stackAlive) {
      $since = (Get-Date) - $script:LastReconnectAt
      if ($since.TotalSeconds -lt 30) { return }
      if ($script:ReconnectTries -ge 2) {
        try { Stop-ProxyStack } catch {}
        Update-Ui
        $tray.ShowBalloonTip(4000, $AppTitle, 'Connection lost. Proxy OFF.', [Windows.Forms.ToolTipIcon]::Warning)
        return
      }
      $script:ReconnectTries++
      $script:LastReconnectAt = Get-Date
      try {
        Start-ProxyStack
        Update-Ui
        $tray.ShowBalloonTip(2500, $AppTitle, 'Reconnected', [Windows.Forms.ToolTipIcon]::Info)
      } catch {
        try { Stop-ProxyStack } catch {}
        Update-Ui
        $tray.ShowBalloonTip(4000, $AppTitle, 'Connection lost. Proxy OFF.', [Windows.Forms.ToolTipIcon]::Warning)
      }
    } else {
      $script:ReconnectTries = 0
    }
  }
})
$timer.Start()

try { Stop-ProxyStack } catch {}
Ensure-DesktopShortcut
Update-DesktopShieldIcon $false
Update-Ui

if ($StartOn) {
  try { Invoke-Toggle } catch {
    try { Stop-ProxyStack } catch {}
    Update-Ui
    $tray.ShowBalloonTip(4000, $AppTitle, $_.Exception.Message, [Windows.Forms.ToolTipIcon]::Error)
  }
} else {
  $tray.ShowBalloonTip(2200, $AppTitle, "Ready.`nDesktop shield: double-click ON/OFF.", [Windows.Forms.ToolTipIcon]::Info)
}

[Windows.Forms.Application]::Run()
try { $mutex.ReleaseMutex() } catch {}
