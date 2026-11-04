<#
Windows desktop installer. Run by "Install <product>.cmd" from the release zip.

  1. Unblock the extracted files (Windows marks a downloaded zip).
  2. Download uv, checking its published checksum.
  3. Install a private Python 3.12 into <InstallDir>\python with uv.
  4. Copy the source to <InstallDir>\app.
  5. Install the dependencies with `uv sync --frozen --no-dev`.
  6. Allow the server through Windows Firewall on Private networks (one Yes).
  7. Create the desktop and Start menu shortcuts to the control panel.
  8. Write install.ok and open the panel.

Run it again at any time: every step checks whether its work is already done,
and the download cache in <InstallDir>\cache is kept, so a dropped connection
costs only what was not yet downloaded. No step needs admin rights except the
firewall rule.

See docs/plans/2026-11-05-desktop-panel-and-reset-plan.md, M3.5.
#>
param(
    [string]$InstallDir = "C:\FastAlgo",
    [string]$Source = $PSScriptRoot,
    [string]$CacheDir = "",
    [string]$UvVersion = "0.12.17",
    [switch]$SkipFirewall,
    [switch]$NoShortcuts,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # the progress bar slows downloads tenfold in PowerShell 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $CacheDir) { $CacheDir = Join-Path $InstallDir "cache" }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$Log = Join-Path $InstallDir "install.log"
Start-Transcript -Path $Log -Append | Out-Null

# The product name, from the same source as the app (utils/brand.py), so a
# rename never needs this script changed.
function Get-ProductName {
    foreach ($root in @((Join-Path $Source "app"), (Join-Path $InstallDir "app"))) {
        $brand = Join-Path $root "utils\brand.py"
        if (Test-Path $brand) {
            $m = Select-String -Path $brand -Pattern '^PRODUCT_NAME\s*=\s*"([^"]+)"' | Select-Object -First 1
            if ($m) { return $m.Matches[0].Groups[1].Value }
        }
    }
    return "Trading platform"
}
$Name = Get-ProductName

function Say([string]$Message) { Write-Host $Message -ForegroundColor Cyan }

function Stop-Install([string]$Message) {
    Write-Host ""
    Write-Host $Message -ForegroundColor Yellow
    Write-Host "Details for support are in $Log" -ForegroundColor Gray
    Stop-Transcript | Out-Null
    exit 1
}

$NetworkHelp = "The internet connection dropped while downloading. Check your connection and " +
    "double-click `"Install $Name.cmd`" again. It will continue from where it stopped."

function Invoke-WithRetry([scriptblock]$Action, [string]$What, [int]$Tries = 3) {
    for ($i = 1; $i -le $Tries; $i++) {
        try { return & $Action }
        catch {
            Write-Host "  $What failed (try $i of $Tries): $($_.Exception.Message)" -ForegroundColor Gray
            if ($i -eq $Tries) { throw }
            Start-Sleep -Seconds 10
        }
    }
}

# Download to a temporary name and rename only when complete, so a half file
# is never mistaken for a whole one.
function Save-Url([string]$Url, [string]$Target) {
    $partial = "$Target.partial"
    Invoke-WithRetry { Invoke-WebRequest -Uri $Url -OutFile $partial -UseBasicParsing -TimeoutSec 300 } "Download"
    Move-Item -Force $partial $Target
}

Say "Installing $Name into $InstallDir"

# --- 1. unblock ------------------------------------------------------------------
Get-ChildItem -Path $Source -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

# --- 2. uv -----------------------------------------------------------------------
$Uv = Join-Path $InstallDir "uv.exe"
$haveUv = $false
if (Test-Path $Uv) {
    try { $haveUv = ((& $Uv --version) -match [regex]::Escape($UvVersion)) } catch { $haveUv = $false }
}
if (-not $haveUv) {
    Say "Downloading uv $UvVersion"
    $asset = "uv-x86_64-pc-windows-msvc.zip"
    $base = "https://github.com/astral-sh/uv/releases/download/$UvVersion"
    $zip = Join-Path $InstallDir $asset
    try {
        Save-Url "$base/$asset" $zip
        Save-Url "$base/$asset.sha256" "$zip.sha256"
    } catch { Stop-Install $NetworkHelp }
    $expected = ((Get-Content "$zip.sha256" -Raw).Trim() -split '\s+')[0].ToLower()
    $actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($expected -ne $actual) {
        Remove-Item -Force $zip, "$zip.sha256"
        Stop-Install "The uv download was damaged. Double-click `"Install $Name.cmd`" again to download it fresh."
    }
    $unpack = Join-Path $InstallDir "uv-unpack"
    Remove-Item -Recurse -Force $unpack -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $unpack -Force
    Get-ChildItem -Path $unpack -Recurse -Include "uv.exe", "uvx.exe" | ForEach-Object {
        Copy-Item -Force $_.FullName (Join-Path $InstallDir $_.Name)
    }
    Remove-Item -Recurse -Force $unpack, $zip, "$zip.sha256"
}

$env:UV_PYTHON_INSTALL_DIR = Join-Path $InstallDir "python"
$env:UV_PYTHON_PREFERENCE = "only-managed"   # never a Python someone else installed
$env:UV_CACHE_DIR = $CacheDir
$env:UV_HTTP_RETRIES = "5"
$env:UV_HTTP_TIMEOUT = "120"
$env:UV_PYTHON = "3.12"

# --- 3. Python -------------------------------------------------------------------
Say "Installing Python 3.12"
& $Uv python install 3.12
if ($LASTEXITCODE -ne 0) { Stop-Install $NetworkHelp }
if (-not (& $Uv python find 3.12)) { Stop-Install "Python could not be installed. Send $Log to support." }

# --- 4. the source ---------------------------------------------------------------
$App = Join-Path $InstallDir "app"
$fromApp = Join-Path $Source "app"
if ((Test-Path $fromApp) -and ((Resolve-Path $fromApp).Path -ne [IO.Path]::GetFullPath($App))) {
    Say "Copying $Name to $App"
    # /E copies and never deletes, so a re-run leaves the client's files alone.
    robocopy $fromApp $App /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Stop-Install "The files could not be copied to $App. Send $Log to support." }
    foreach ($file in @("install-desktop.ps1", "Install $Name.cmd")) {
        $from = Join-Path $Source $file
        if (Test-Path $from) { Copy-Item -Force $from (Join-Path $InstallDir $file) }
    }
}
if (-not (Test-Path (Join-Path $App "app.py"))) { Stop-Install "The program files are missing from $App. Extract the whole zip and try again." }

# --- 5. dependencies -------------------------------------------------------------
Say "Installing dependencies (a few minutes the first time)"
Push-Location $App
try {
    & $Uv sync --frozen --no-dev
    $ok = ($LASTEXITCODE -eq 0)
} finally { Pop-Location }
if (-not $ok) { Stop-Install $NetworkHelp }

# The interpreter the server really runs as. The venv's launcher starts the
# Python named in pyvenv.cfg, which uv points at its version folder
# (cpython-3.12-...), not the patch folder `uv python find` reports
# (cpython-3.12.14-...). A firewall rule matches the exact path, so it must be
# this one; it also survives a Python patch upgrade.
$cfg = Get-Content (Join-Path $App ".venv\pyvenv.cfg") | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
$PythonHome = ($cfg -split '=', 2)[1].Trim()
$Python = Join-Path $PythonHome "python.exe"
$PythonW = Join-Path $PythonHome "pythonw.exe"
if (-not (Test-Path $PythonW)) { Stop-Install "The Python environment is incomplete. Run the installer again." }

# --- 6. firewall -----------------------------------------------------------------
if (-not $SkipFirewall) {
    Say "Allowing phones and other computers on your home or office network (Windows will ask once)"
    $rule = "$Name server"
    $command = "Remove-NetFirewallRule -DisplayName '$rule' -ErrorAction SilentlyContinue; " +
        "New-NetFirewallRule -DisplayName '$rule' -Direction Inbound -Program '$Python' " +
        "-Profile Private -Action Allow | Out-Null"
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden `
            -ArgumentList "-NoProfile", "-Command", $command
    } catch {
        Write-Host "  Skipped. Phones on your network cannot connect until this is allowed; run the installer again to retry." -ForegroundColor Yellow
    }
}

# --- 7. shortcuts ----------------------------------------------------------------
$PanelArgs = "`"$App\launcher\panel.py`" --home `"$InstallDir`""
if (-not $NoShortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
        $link = $shell.CreateShortcut((Join-Path $folder "$Name.lnk"))
        $link.TargetPath = $PythonW
        $link.Arguments = $PanelArgs
        $link.WorkingDirectory = $App
        $icon = Join-Path $App "frontend\dist\favicon.ico"
        if (Test-Path $icon) { $link.IconLocation = $icon }
        $link.Description = "$Name control panel"
        $link.Save()
    }
}

# --- 8. done ---------------------------------------------------------------------
$version = (Select-String -Path (Join-Path $App "utils\version.py") -Pattern '^VERSION\s*=\s*"([^"]+)"' |
    Select-Object -First 1).Matches[0].Groups[1].Value
Set-Content -Path (Join-Path $InstallDir "install.ok") -Value "$version $(Get-Date -Format s)" -Encoding ASCII
Say "$Name $version is installed."
Stop-Transcript | Out-Null

if (-not $NoLaunch) {
    Start-Process -FilePath $PythonW -ArgumentList $PanelArgs -WorkingDirectory $App
}
exit 0
