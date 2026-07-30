#Requires -Version 5.1
<#
.SYNOPSIS
    Install the Minecraft Infra Pack modpack on Windows via Prism Launcher.

.DESCRIPTION
    This script:
      - Verifies (or installs) Prism Launcher
      - Verifies (or installs) Java 21+
      - Locates Prism Launcher's real "instances" directory and creates the
        NeoForge 1.21.1 instance directly inside it - no manual folder
        picking or copying required
      - Falls back to a folder picker only if Prism's instances directory
        cannot be determined automatically
      - Shows a completion dialog with next steps

.NOTES
    Run from PowerShell 5.1+ (ships with Windows 10/11):
        powershell -NoExit -ExecutionPolicy Bypass -File install-client-windows.ps1
    Or double-click install-client-windows.bat instead, which runs this
    file with the right flags for you.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

$PackName            = "Minecraft Infra Pack 1.21.1 (NeoForge)"
$InstanceDirName     = "minecraft-infra-pack"
$McVersion           = "1.21.1"
$NeoForgeVersion     = "21.1.244"
$LwjglVersion        = "3.3.3"
$BootstrapUrl        = "https://github.com/packwiz/packwiz-installer-bootstrap/releases/latest/download/packwiz-installer-bootstrap.jar"
$PackwizPackUrl      = "https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/packwiz/pack.toml"
$PrismDownloadUrl    = "https://prismlauncher.org/download/windows"
$PrismDirectUrl      = "https://github.com/PrismLauncher/PrismLauncher/releases/latest/download/PrismLauncher-Windows-Setup.exe"
$AdoptiumApiUrl      = "https://api.adoptium.net/v3/assets/feature_releases/21/ga?image_type=jdk&os=windows&architecture=x64&vendor=eclipse&page_size=1"
$JavaDownloadPageUrl = "https://adoptium.net/temurin/releases/?version=21"
$ScriptVersion       = "2026-07-31-v2"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Show-MessageBox {
    param(
        [string]$Message,
        [string]$Title = "Minecraft Infra Pack Installer",
        [System.Windows.Forms.MessageBoxButtons]$Buttons = [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]$Icon = [System.Windows.Forms.MessageBoxIcon]::Information
    )
    return [System.Windows.Forms.MessageBox]::Show($Message, $Title, $Buttons, $Icon)
}

function Write-Step {
    param([string]$Message)
    Write-Host "[....] $Message" -ForegroundColor Cyan
}

function Write-OK {
    param([string]$Message)
    Write-Host "[ OK ] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

# Log file lives in Prism's instances folder (same place the uninstaller's
# own log ends up), named with the script version + a timestamp so runs
# from different copies/attempts of this file can't be confused with each
# other. Initialize-Log is called once the instances directory is known;
# until then Write-Log is a no-op so early calls don't error out.
$LogPath = $null

function Initialize-Log {
    param([string]$Directory)
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $script:LogPath = Join-Path $Directory "install-log-$ScriptVersion-$timestamp.txt"
    "=== install-client-windows.ps1 $ScriptVersion started $timestamp ===" | Out-File -FilePath $script:LogPath -Encoding UTF8
    $isAdmin = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
    Write-Log "[env] User=$env:USERNAME Is64BitProcess=$([Environment]::Is64BitProcess) IsAdmin=$isAdmin PSVersion=$($PSVersionTable.PSVersion) PSEdition=$($PSVersionTable.PSEdition)"
}

function Write-Log {
    param([string]$Message)
    if ($script:LogPath) {
        $line = "[$(Get-Date -Format 'HH:mm:ss')] $Message"
        Add-Content -Path $script:LogPath -Value $line -Encoding UTF8
    }
}

function Write-DiagLine {
    param([string]$Message)
    Write-Host "  [diag] $Message" -ForegroundColor DarkGray
    Write-Log "[diag-install] $Message"
}

# ---------------------------------------------------------------------------
# Step 1 - Locate or install Prism Launcher
# ---------------------------------------------------------------------------

function Find-PrismLauncher {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\PrismLauncher\prismlauncher.exe"),
        (Join-Path $env:PROGRAMFILES "PrismLauncher\prismlauncher.exe")
    )

    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

function Install-PrismLauncher {
    $answer = Show-MessageBox `
        -Message "Prism Launcher does not appear to be installed on this machine.`n`nWould you like to download and install it automatically?`n`n(Clicking 'No' will open the download page in your browser instead, so you can choose your own install location.)" `
        -Title "Prism Launcher Not Found" `
        -Buttons YesNo `
        -Icon Question

    if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
        Write-Step "Downloading Prism Launcher installer..."
        $installerPath = Join-Path $env:TEMP "PrismLauncher-Setup.exe"

        try {
            $webClient = New-Object System.Net.WebClient
            $webClient.DownloadFile($PrismDirectUrl, $installerPath)
            Write-OK "Downloaded Prism Launcher installer."
        } catch {
            Show-MessageBox `
                -Message "Failed to download Prism Launcher:`n$_`n`nPlease download it manually from:`n$PrismDownloadUrl" `
                -Title "Download Failed" `
                -Icon Error
            Start-Process $PrismDownloadUrl
            exit 1
        }

        Write-Step "Running Prism Launcher installer silently..."
        try {
            $proc = Start-Process -FilePath $installerPath -ArgumentList "/S" -PassThru -Wait
            if ($proc.ExitCode -ne 0) {
                throw "Installer exited with code $($proc.ExitCode)"
            }
            Write-OK "Prism Launcher installed successfully."
        } catch {
            Show-MessageBox `
                -Message "Prism Launcher installation failed:`n$_`n`nPlease install it manually from:`n$PrismDownloadUrl" `
                -Title "Installation Failed" `
                -Icon Error
            exit 1
        }

        # Clean up
        Remove-Item -Force -ErrorAction SilentlyContinue $installerPath

    } else {
        Start-Process $PrismDownloadUrl
        Show-MessageBox `
            -Message "Please install Prism Launcher (pick whatever location you like), then re-run this script - it will find it automatically." `
            -Title "Manual Installation Required" `
            -Icon Information
        exit 0
    }

    # Re-check after installation
    $prismExe = Find-PrismLauncher
    if (-not $prismExe) {
        Show-MessageBox `
            -Message "Could not locate Prism Launcher after installation.`nPlease launch it once manually, then re-run this script." `
            -Title "Prism Launcher Not Found" `
            -Icon Warning
        exit 1
    }

    return $prismExe
}

# ---------------------------------------------------------------------------
# Step 2 - Locate Prism Launcher's real "instances" directory
# ---------------------------------------------------------------------------

function Get-PrismInstancesDir {
    param([string]$PrismExePath)

    $prismExeDir = Split-Path -Parent $PrismExePath

    # Portable installs keep their data (including instances/) right next to
    # the executable, marked by a prismlauncher.cfg file there.
    if (Test-Path (Join-Path $prismExeDir "prismlauncher.cfg")) {
        $portableInstances = Join-Path $prismExeDir "instances"
        New-Item -ItemType Directory -Force -Path $portableInstances | Out-Null
        return $portableInstances
    }

    # Installed (non-portable) Prism keeps user data under %APPDATA%.
    $installedInstances = Join-Path $env:APPDATA "PrismLauncher\instances"
    New-Item -ItemType Directory -Force -Path $installedInstances | Out-Null
    return $installedInstances
}

# ---------------------------------------------------------------------------
# Step 3 - Check / auto-install Java 21+
# ---------------------------------------------------------------------------

function Test-JavaVersion {
    try {
        $javaOutput = & java -version 2>&1
    } catch {
        return $false, 0
    }

    if ($LASTEXITCODE -ne 0 -and $null -eq $javaOutput) {
        return $false, 0
    }

    # java -version prints to stderr; $javaOutput should contain the text
    $versionLine = ($javaOutput | Select-Object -First 1).ToString()

    # Match "21.0.7", "21", "1.8.0_xxx" etc.
    if ($versionLine -match '"(\d+)\.') {
        $major = [int]$Matches[1]
        # Handle legacy "1.x" notation (Java 8 = "1.8")
        if ($major -eq 1 -and $versionLine -match '"1\.(\d+)') {
            $major = [int]$Matches[1]
        }
        return $true, $major
    }

    return $true, -1
}

function Find-RegisteredJava21 {
    # java -version on PATH can miss an already-installed JDK (stale PATH in
    # this shell, PATH never refreshed since install, etc). Before offering
    # to run the MSI installer, check the Windows Installer registry
    # directly - if Temurin 21 is already registered per-machine, re-running
    # msiexec /i on it drops into repair/maintenance mode instead of a fresh
    # install and fails with exit code 1603 (source resolution failure),
    # since the freshly re-downloaded MSI lives at a different temp path
    # than whatever the original install used.
    $uninstallPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $matchedEntry = $null
    foreach ($path in $uninstallPaths) {
        $entries = @(Get-ItemProperty -Path $path -ErrorAction SilentlyContinue)
        Write-DiagLine "$path -> $($entries.Count) subkeys read"
        $withName = @($entries | Where-Object { $_.PSObject.Properties.Name -contains "DisplayName" -and $_.DisplayName })
        Write-DiagLine "$path -> $($withName.Count) subkeys have a non-empty DisplayName"

        if (-not $matchedEntry) {
            foreach ($entry in $withName) {
                $displayName = $entry.DisplayName
                if ($displayName -match "Temurin" -and $displayName -match "21") {
                    Write-DiagLine "matched: $displayName"
                    $installLocation = $null
                    if ($entry.PSObject.Properties.Name -contains "InstallLocation") {
                        $installLocation = $entry.InstallLocation
                    }
                    $matchedEntry = [PSCustomObject]@{
                        DisplayName     = $displayName
                        InstallLocation = $installLocation
                    }
                    break
                }
            }
        }
    }
    if (-not $matchedEntry) {
        Write-DiagLine "no match found across all paths"
    }
    return $matchedEntry
}

function Update-CurrentProcessPath {
    # Merges the Machine + User PATH from the registry into this process's
    # PATH. A PATH change made by an MSI installer only reaches processes
    # started after that point - this script's own PowerShell session may
    # have been launched before Java was installed, so `java` resolves to
    # nothing until we pull the current PATH in manually.
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Get-LatestTemurinInstallerUrl {
    try {
        $response = Invoke-RestMethod -Uri $AdoptiumApiUrl -UseBasicParsing
        return $response[0].binaries[0].installer.link
    } catch {
        return $null
    }
}

function Install-Java {
    Write-Step "Looking up the latest Java 21 (Temurin) installer..."
    $installerUrl = Get-LatestTemurinInstallerUrl
    if (-not $installerUrl) {
        Write-Warn "Could not resolve the latest Java 21 installer URL automatically."
        Show-MessageBox `
            -Message "Could not determine the latest Java 21 installer automatically.`n`nOpening the manual download page instead." `
            -Title "Java Auto-Install Failed" `
            -Icon Warning
        Start-Process $JavaDownloadPageUrl
        return $false
    }

    Write-Step "Downloading Java 21 installer (this is a large file, please wait)..."
    $installerPath = Join-Path $env:TEMP "temurin21-installer.msi"
    try {
        $webClient = New-Object System.Net.WebClient
        $webClient.DownloadFile($installerUrl, $installerPath)
        Write-OK "Downloaded Java 21 installer."
    } catch {
        Write-Warn "Failed to download Java installer: $_"
        Show-MessageBox `
            -Message "Failed to download the Java 21 installer:`n$_`n`nPlease install it manually from:`n$JavaDownloadPageUrl" `
            -Title "Download Failed" `
            -Icon Error
        Start-Process $JavaDownloadPageUrl
        return $false
    }

    Write-Step "Installing Java 21 (a Windows admin prompt (UAC) may appear - approve it)..."
    $logPath = Join-Path $env:TEMP "temurin21-install.log"
    try {
        # -Verb RunAs requests elevation: the Temurin MSI installs per-machine
        # (Program Files, HKLM), which msiexec refuses without admin rights -
        # that shows up as exit code 1625 (ERROR_INSTALL_REJECTED) otherwise.
        # /l*v writes a verbose log so a generic exit code (e.g. 1603, "fatal
        # error during installation") can actually be diagnosed afterward.
        $proc = Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", "`"$installerPath`"", "/quiet", "/norestart", "/l*v", "`"$logPath`"") -Verb RunAs -PassThru -Wait
        if ($proc.ExitCode -eq 1625) {
            throw "msiexec exited with code 1625 (installation rejected). This almost always means it ran without administrator rights, or a Group Policy on this machine blocks MSI installs. Try again and approve the UAC prompt, or install manually as an administrator."
        }
        if ($proc.ExitCode -eq 1603) {
            throw "msiexec exited with code 1603 (fatal error during installation - a generic code, the real reason is only in the log). This often means this exact Java 21 build is already registered on this machine, and msiexec dropped into repair mode instead of a fresh install. Restart Windows (so any pending Java changes finish applying) and run this installer again - it will now detect the existing install first instead of retrying msiexec blindly. Log saved to: $logPath"
        }
        if ($proc.ExitCode -ne 0) {
            throw "msiexec exited with code $($proc.ExitCode). Log saved to: $logPath"
        }
        Write-OK "Java 21 installed successfully."
        return $true
    } catch {
        $errorText = "$_"
        if ($errorText -match "cancel") {
            $errorText = "The administrator prompt (UAC) was declined, so Java could not be installed."
        }
        Write-Warn "Java installation failed: $errorText"
        Show-MessageBox `
            -Message "Java installation failed:`n$errorText`n`nPlease install it manually from:`n$JavaDownloadPageUrl" `
            -Title "Installation Failed" `
            -Icon Error
        Start-Process $JavaDownloadPageUrl
        return $false
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $installerPath
    }
}

function Confirm-JavaVersion {
    Write-Step "Checking Java version..."
    $javaFound, $javaVersion = Test-JavaVersion
    Write-Log "Test-JavaVersion: found=$javaFound version=$javaVersion"

    $needsInstall = (-not $javaFound) -or ($javaVersion -ne -1 -and $javaVersion -lt 21)

    if ($needsInstall) {
        # Not found on PATH - before concluding Java is missing, check
        # whether it is already registered on this machine and just not
        # visible to this process's PATH yet.
        $registered = Find-RegisteredJava21
        if ($registered) {
            Write-Warn "Java 21 (Temurin) is already registered on this machine ($($registered.DisplayName)) but wasn't found on PATH - refreshing PATH for this session..."
            Update-CurrentProcessPath
            $javaFound, $javaVersion = Test-JavaVersion
            $needsInstall = (-not $javaFound) -or ($javaVersion -ne -1 -and $javaVersion -lt 21)

            if ($needsInstall) {
                Write-OK "Java 21 is already installed ($($registered.DisplayName)); skipping installer to avoid re-running the MSI over an existing install (which fails with error 1603)."
                Write-Warn "It's not resolvable as 'java' in this window though. Restart Windows (or at least log out/in) so the PATH change takes effect everywhere, or in Prism Launcher use the Java settings page's Auto-detect button and point it at:`n$($registered.InstallLocation)bin\javaw.exe"
                return
            }
        }
    }

    if (-not $needsInstall) {
        if ($javaVersion -eq -1) {
            Write-OK "Java detected (version could not be parsed - verify it is 21+)."
        } else {
            Write-OK "Java $javaVersion detected."
        }
        return
    }

    if (-not $javaFound) {
        $msg = "Java does not appear to be installed or is not on the PATH."
    } else {
        $msg = "Java $javaVersion detected, but Minecraft $McVersion requires Java 21 or newer."
    }

    $answer = Show-MessageBox `
        -Message "$msg`n`nWould you like to automatically download and install Java 21 (Eclipse Temurin)?`n`n(Clicking 'No' will open the download page in your browser instead.)" `
        -Title "Java 21+ Required" `
        -Buttons YesNo `
        -Icon Question

    if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
        $installed = Install-Java
        if ($installed) {
            Write-Warn "Java 21 was installed. If Prism Launcher doesn't pick it up automatically, use its Java settings page to Auto-detect."
        }
    } else {
        Start-Process $JavaDownloadPageUrl
        Write-Warn "Continuing without confirmed Java 21 - install it before launching the instance."
    }
}

# ---------------------------------------------------------------------------
# Step 4 - Download packwiz-installer-bootstrap.jar
# ---------------------------------------------------------------------------

function Get-PackwizBootstrap {
    param([string]$DestinationPath)

    if (Test-Path $DestinationPath) {
        Write-OK "packwiz-installer-bootstrap.jar already present."
        return
    }

    Write-Step "Downloading packwiz-installer-bootstrap.jar..."
    try {
        $webClient = New-Object System.Net.WebClient
        $webClient.DownloadFile($BootstrapUrl, $DestinationPath)
        Write-OK "Downloaded packwiz-installer-bootstrap.jar."
    } catch {
        throw "Failed to download packwiz-installer-bootstrap.jar: $_"
    }
}

# ---------------------------------------------------------------------------
# Step 5 - Create the Prism Launcher instance
# ---------------------------------------------------------------------------

function Write-UninstallScripts {
    param([string]$TargetInstancesDir)

    # Written into the *parent* instances/ folder, not inside the instance
    # folder itself: deleting a directory while a script living inside it is
    # still running can fail with "in use by another application" (a real
    # user hit this). Living one level up as a sibling avoids that entirely.

    # Single-quoted here-string: no variable interpolation at all, so none
    # of the $-signs below need escaping. InstanceDir is passed in at
    # uninstall time as a real -InstanceDir argument, not baked in here.
    $uninstallPs1B64 = 'cGFyYW0oCiAgICBbUGFyYW1ldGVyKE1hbmRhdG9yeT0kdHJ1ZSldCiAgICBbc3RyaW5nXSRJbnN0YW5jZURpcgopCgokU2NyaXB0VmVyc2lvbiA9ICIyMDI2LTA3LTMxLXYyIgoKQWRkLVR5cGUgLUFzc2VtYmx5TmFtZSBTeXN0ZW0uV2luZG93cy5Gb3JtcwoKZnVuY3Rpb24gU2hvdy1Nc2dCb3ggewogICAgcGFyYW0oCiAgICAgICAgW3N0cmluZ10kTWVzc2FnZSwKICAgICAgICBbc3RyaW5nXSRUaXRsZSA9ICLQo9C00LDQu9C10L3QuNC1IE1pbmVjcmFmdCBJbmZyYSBQYWNrIiwKICAgICAgICBbU3lzdGVtLldpbmRvd3MuRm9ybXMuTWVzc2FnZUJveEJ1dHRvbnNdJEJ1dHRvbnMgPSBbU3lzdGVtLldpbmRvd3MuRm9ybXMuTWVzc2FnZUJveEJ1dHRvbnNdOjpPSywKICAgICAgICBbU3lzdGVtLldpbmRvd3MuRm9ybXMuTWVzc2FnZUJveEljb25dJEljb24gPSBbU3lzdGVtLldpbmRvd3MuRm9ybXMuTWVzc2FnZUJveEljb25dOjpJbmZvcm1hdGlvbgogICAgKQogICAgcmV0dXJuIFtTeXN0ZW0uV2luZG93cy5Gb3Jtcy5NZXNzYWdlQm94XTo6U2hvdygkTWVzc2FnZSwgJFRpdGxlLCAkQnV0dG9ucywgJEljb24pCn0KCiMgTG9nIGZpbGUgbGl2ZXMgbmV4dCB0byB0aGlzIHNjcmlwdCAodGhlIGluc3RhbmNlcyBmb2xkZXIpLCBzbyBpdCBzdXJ2aXZlcwojIHRoZSBzZWxmLWNsZWFudXAgYXQgdGhlIGVuZCBhbmQgdGhlIHVzZXIgY2FuIHNlbmQgaXQgYmFjayBmb3IgZGlhZ25vc2lzLgojIE5hbWVkIHdpdGggdGhlIHNjcmlwdCB2ZXJzaW9uICsgYSB0aW1lc3RhbXAgc28gcnVucyBmcm9tIGRpZmZlcmVudCBjb3BpZXMKIyBvZiB0aGlzIGZpbGUgKGFuZCBkaWZmZXJlbnQgYXR0ZW1wdHMpIGNhbid0IGJlIGNvbmZ1c2VkIHdpdGggZWFjaCBvdGhlci4KJGluc3RhbmNlc0RpckZvckxvZyA9IFNwbGl0LVBhdGggLVBhcmVudCAkSW5zdGFuY2VEaXIKJGxvZ1RpbWVzdGFtcCA9IEdldC1EYXRlIC1Gb3JtYXQgInl5eXlNTWRkLUhIbW1zcyIKJExvZ1BhdGggPSBKb2luLVBhdGggJGluc3RhbmNlc0RpckZvckxvZyAidW5pbnN0YWxsLWxvZy0kU2NyaXB0VmVyc2lvbi0kbG9nVGltZXN0YW1wLnR4dCIKCmZ1bmN0aW9uIFdyaXRlLUxvZyB7CiAgICBwYXJhbShbc3RyaW5nXSRNZXNzYWdlKQogICAgJGxpbmUgPSAiWyQoR2V0LURhdGUgLUZvcm1hdCAnSEg6bW06c3MnKV0gJE1lc3NhZ2UiCiAgICBBZGQtQ29udGVudCAtUGF0aCAkTG9nUGF0aCAtVmFsdWUgJGxpbmUgLUVuY29kaW5nIFVURjgKfQoKZnVuY3Rpb24gV3JpdGUtRGlhZ0xpbmUgewogICAgcGFyYW0oW3N0cmluZ10kTWVzc2FnZSkKICAgIFdyaXRlLUhvc3QgIiAgW2RpYWddICRNZXNzYWdlIiAtRm9yZWdyb3VuZENvbG9yIERhcmtHcmF5CiAgICBXcml0ZS1Mb2cgIltkaWFnLXVuaW5zdGFsbF0gJE1lc3NhZ2UiCn0KCiI9PT0gdW5pbnN0YWxsLWluZnJhLW1vZHBhY2sucHMxICRTY3JpcHRWZXJzaW9uIHN0YXJ0ZWQgJGxvZ1RpbWVzdGFtcCA9PT0iIHwgT3V0LUZpbGUgLUZpbGVQYXRoICRMb2dQYXRoIC1FbmNvZGluZyBVVEY4CldyaXRlLUxvZyAiSW5zdGFuY2VEaXI9JEluc3RhbmNlRGlyIgokaXNBZG1pbiA9IChOZXctT2JqZWN0IFNlY3VyaXR5LlByaW5jaXBhbC5XaW5kb3dzUHJpbmNpcGFsKFtTZWN1cml0eS5QcmluY2lwYWwuV2luZG93c0lkZW50aXR5XTo6R2V0Q3VycmVudCgpKSkuSXNJblJvbGUoW1NlY3VyaXR5LlByaW5jaXBhbC5XaW5kb3dzQnVpbHRpblJvbGVdOjpBZG1pbmlzdHJhdG9yKQpXcml0ZS1Mb2cgIltlbnZdIFVzZXI9JGVudjpVU0VSTkFNRSBJczY0Qml0UHJvY2Vzcz0kKFtFbnZpcm9ubWVudF06OklzNjRCaXRQcm9jZXNzKSBJc0FkbWluPSRpc0FkbWluIFBTVmVyc2lvbj0kKCRQU1ZlcnNpb25UYWJsZS5QU1ZlcnNpb24pIFBTRWRpdGlvbj0kKCRQU1ZlcnNpb25UYWJsZS5QU0VkaXRpb24pIgoKV3JpdGUtSG9zdCAiIgpXcml0ZS1Ib3N0ICI9PT0g0KPQtNCw0LvQtdC90LjQtSBNaW5lY3JhZnQgSW5mcmEgUGFjayA9PT0iIC1Gb3JlZ3JvdW5kQ29sb3IgQ3lhbgpXcml0ZS1Ib3N0ICIgICAgKNCy0LXRgNGB0LjRjyDRgdC60YDQuNC/0YLQsDogJFNjcmlwdFZlcnNpb24sINC70L7QszogJExvZ1BhdGgpIiAtRm9yZWdyb3VuZENvbG9yIERhcmtHcmF5CldyaXRlLUhvc3QgIiIKCiRjb25maXJtID0gU2hvdy1Nc2dCb3ggYAogICAgLU1lc3NhZ2UgItCj0LTQsNC70LjRgtGMINC80L7QtNC/0LDQuiBNaW5lY3JhZnQgSW5mcmEgUGFjaz9gbmBu0JHRg9C00LXRgiDRg9C00LDQu9C10L3QsCDQstGB0Y8g0L/QsNC/0LrQsDpgbiRJbnN0YW5jZURpcmBuYG4o0LLQutC70Y7Rh9Cw0Y8g0YHQvtGF0YDQsNC90LXQvdC40Y8g0LzQuNGA0L7Qsiwg0LrQvtC90YTQuNCz0Lgg0Lgg0LLRgdC1INC80L7QtNGLKSIgYAogICAgLVRpdGxlICLQn9C+0LTRgtCy0LXRgNC20LTQtdC90LjQtSDRg9C00LDQu9C10L3QuNGPIiAtQnV0dG9ucyBZZXNObyAtSWNvbiBXYXJuaW5nCmlmICgkY29uZmlybSAtbmUgW1N5c3RlbS5XaW5kb3dzLkZvcm1zLkRpYWxvZ1Jlc3VsdF06OlllcykgewogICAgV3JpdGUtTG9nICJVc2VyIGNhbmNlbGxlZCBhdCBjb25maXJtYXRpb24gZGlhbG9nLiIKICAgIFdyaXRlLUhvc3QgItCe0YLQvNC10L3QtdC90L4g0L/QvtC70YzQt9C+0LLQsNGC0LXQu9C10LwuIgogICAgUmVhZC1Ib3N0ICLQndCw0LbQvNC40YLQtSBFbnRlciDQtNC70Y8g0LLRi9GF0L7QtNCwIgogICAgZXhpdCAwCn0KCmZ1bmN0aW9uIEZpbmQtVGVtdXJpblVuaW5zdGFsbGVycyB7CiAgICAkcGF0aHMgPSBAKAogICAgICAgICJIS0xNOlxTT0ZUV0FSRVxNaWNyb3NvZnRcV2luZG93c1xDdXJyZW50VmVyc2lvblxVbmluc3RhbGxcKiIsCiAgICAgICAgIkhLTE06XFNPRlRXQVJFXFdPVzY0MzJOb2RlXE1pY3Jvc29mdFxXaW5kb3dzXEN1cnJlbnRWZXJzaW9uXFVuaW5zdGFsbFwqIiwKICAgICAgICAiSEtDVTpcU09GVFdBUkVcTWljcm9zb2Z0XFdpbmRvd3NcQ3VycmVudFZlcnNpb25cVW5pbnN0YWxsXCoiCiAgICApCiAgICAkZm91bmQgPSBAKCkKICAgIGZvcmVhY2ggKCRwIGluICRwYXRocykgewogICAgICAgICRlcnIgPSAkbnVsbAogICAgICAgICRlbnRyaWVzID0gQChHZXQtSXRlbVByb3BlcnR5IC1QYXRoICRwIC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlIC1FcnJvclZhcmlhYmxlIGVycikKICAgICAgICBXcml0ZS1EaWFnTGluZSAiJHAgLT4gJCgkZW50cmllcy5Db3VudCkgc3Via2V5cyByZWFkIgogICAgICAgIGlmICgkZXJyKSB7CiAgICAgICAgICAgIFdyaXRlLURpYWdMaW5lICJHZXQtSXRlbVByb3BlcnR5IGVycm9yOiAkKCRlcnJbMF0pIgogICAgICAgIH0KICAgICAgICAkd2l0aE5hbWUgPSBAKCRlbnRyaWVzIHwgV2hlcmUtT2JqZWN0IHsgJF8uUFNPYmplY3QuUHJvcGVydGllcy5OYW1lIC1jb250YWlucyAiRGlzcGxheU5hbWUiIC1hbmQgJF8uRGlzcGxheU5hbWUgfSkKICAgICAgICBXcml0ZS1EaWFnTGluZSAiJHAgLT4gJCgkd2l0aE5hbWUuQ291bnQpIHN1YmtleXMgaGF2ZSBhIG5vbi1lbXB0eSBEaXNwbGF5TmFtZSIKICAgICAgICAjIE5hbWVkICRqYXZhTWF0Y2hlcywgbm90ICRtYXRjaGVzIC0gIiRtYXRjaGVzIi8iJE1hdGNoZXMiIGlzIGEKICAgICAgICAjIFBvd2VyU2hlbGwgYXV0b21hdGljIHZhcmlhYmxlIHRoYXQgdGhlIC1tYXRjaCBvcGVyYXRvciBpdHNlbGYKICAgICAgICAjIHdyaXRlcyB0bywgd2hpY2ggaXMgZXhhY3RseSB0aGUga2luZCBvZiB0aGluZyB3b3J0aCBub3QKICAgICAgICAjIHNoYWRvd2luZyBldmVuIGlmIGl0IGhhcHBlbnMgdG8gd29yayBvdXQgaGVyZS4KICAgICAgICAkamF2YU1hdGNoZXMgPSBAKCR3aXRoTmFtZSB8IFdoZXJlLU9iamVjdCB7ICRfLkRpc3BsYXlOYW1lIC1tYXRjaCAiVGVtdXJpbiIgLWFuZCAkXy5EaXNwbGF5TmFtZSAtbWF0Y2ggIjIxIiB9KQogICAgICAgIGlmICgkamF2YU1hdGNoZXMuQ291bnQgLWd0IDApIHsKICAgICAgICAgICAgV3JpdGUtRGlhZ0xpbmUgIm1hdGNoZWQ6ICQoKCRqYXZhTWF0Y2hlcyB8IEZvckVhY2gtT2JqZWN0IHsgJF8uRGlzcGxheU5hbWUgfSkgLWpvaW4gJzsgJykiCiAgICAgICAgfQogICAgICAgIGZvcmVhY2ggKCRtIGluICRqYXZhTWF0Y2hlcykgeyAkZm91bmQgKz0gJG0gfQogICAgfQogICAgV3JpdGUtTG9nICJGaW5kLVRlbXVyaW5Vbmluc3RhbGxlcnMgcmV0dXJuaW5nICQoJGZvdW5kLkNvdW50KSBlbnRyaWVzIHRvdGFsIgogICAgIyBUaGUgY29tbWEgb3BlcmF0b3IgZm9yY2VzIHRoaXMgdG8gYmUgZW1pdHRlZCBhcyBhIHNpbmdsZSBhcnJheSBvYmplY3QKICAgICMgaW5zdGVhZCBvZiBQb3dlclNoZWxsIHVud3JhcHBpbmcgYSBvbmUtZWxlbWVudCBhcnJheSBpbnRvIGEgYmFyZQogICAgIyBzY2FsYXIgb24gdGhlIHBpcGVsaW5lIC0gd2l0aG91dCBpdCwgd2hlbiBleGFjdGx5IG9uZSBKYXZhIGluc3RhbGwgaXMKICAgICMgZm91bmQsIHRoZSBjYWxsZXIncyBgJGphdmFFbnRyaWVzLkNvdW50YCBjaGVjayBzaWxlbnRseSBtaXNiZWhhdmVzCiAgICAjIGV2ZW4gdGhvdWdoIHRoaXMgZnVuY3Rpb24ncyBvd24gJGZvdW5kLkNvdW50IHdhcyBjb3JyZWN0bHkgMSAodGhpcwogICAgIyBpcyBwcmVjaXNlbHkgdGhlICLQvdC1INC90LDQudC00LXQvdCwIiBidWc6IGl0IG9ubHkgZXZlciBmYWlsZWQgd2hlbiB0aGVyZSB3YXMKICAgICMgZXhhY3RseSBvbmUgbWF0Y2gsIHdoaWNoIGlzIGV4YWN0bHkgdGhlIG5vcm1hbCBjYXNlKS4KICAgIHJldHVybiAsJGZvdW5kCn0KCiRqYXZhRW50cmllcyA9IEZpbmQtVGVtdXJpblVuaW5zdGFsbGVycwppZiAoJGphdmFFbnRyaWVzLkNvdW50IC1ndCAwKSB7CiAgICAkbmFtZXMgPSAoJGphdmFFbnRyaWVzIHwgRm9yRWFjaC1PYmplY3QgeyAkXy5EaXNwbGF5TmFtZSB9KSAtam9pbiAiYG4iCiAgICAkamF2YUFuc3dlciA9IFNob3ctTXNnQm94IGAKICAgICAgICAtTWVzc2FnZSAi0J3QsNC50LTQtdC90LAgSmF2YSAyMSAoRWNsaXBzZSBUZW11cmluKSwg0YPRgdGC0LDQvdC+0LLQu9C10L3QvdCw0Y8g0LLQvNC10YHRgtC1INGBINGN0YLQuNC8INC80L7QtNC/0LDQutC+0Lw6YG5gbiRuYW1lc2BuYG7Qo9C00LDQu9C40YLRjCDRgtCw0LrQttC1IEphdmEgMjE/YG5gbtCS0YvQsdC10YDQuNGC0LUgJ9Cd0LXRgicsINC10YHQu9C4IEphdmEg0LjRgdC/0L7Qu9GM0LfRg9C10YLRgdGPINC00YDRg9Cz0LjQvNC4INC/0YDQvtCz0YDQsNC80LzQsNC80Lgg0L3QsCDRjdGC0L7QvCDQutC+0LzQv9GM0Y7RgtC10YDQtS4iIGAKICAgICAgICAtVGl0bGUgItCj0LTQsNC70LjRgtGMIEphdmEgMjE/IiAtQnV0dG9ucyBZZXNObyAtSWNvbiBRdWVzdGlvbgoKICAgIGlmICgkamF2YUFuc3dlciAtZXEgW1N5c3RlbS5XaW5kb3dzLkZvcm1zLkRpYWxvZ1Jlc3VsdF06OlllcykgewogICAgICAgICRhbGxSZW1vdmVkID0gJHRydWUKICAgICAgICBmb3JlYWNoICgkZW50cnkgaW4gJGphdmFFbnRyaWVzKSB7CiAgICAgICAgICAgIFdyaXRlLUxvZyAiUmVtb3Zpbmc6ICQoJGVudHJ5LkRpc3BsYXlOYW1lKSAoUFNDaGlsZE5hbWU9JCgkZW50cnkuUFNDaGlsZE5hbWUpKSIKICAgICAgICAgICAgV3JpdGUtSG9zdCAi0KPQtNCw0LvQtdC90LjQtTogJCgkZW50cnkuRGlzcGxheU5hbWUpLi4uIiAtRm9yZWdyb3VuZENvbG9yIEN5YW4KICAgICAgICAgICAgIyBUaGlzIGlzIGEgcGVyLW1hY2hpbmUgTVNJIGluc3RhbGwgKEhLTE0sIEFMTFVTRVJTPTEpIC0gcmVtb3ZpbmcKICAgICAgICAgICAgIyBpdCBuZWVkcyB0aGUgc2FtZSBlbGV2YXRpb24gdGhlIGluc3RhbGxlciByZXF1ZXN0cyB3aGVuCiAgICAgICAgICAgICMgaW5zdGFsbGluZyBpdCAoLVZlcmIgUnVuQXMpLCBvciBtc2lleGVjIHNpbGVudGx5IGZhaWxzIHVuZGVyIGEKICAgICAgICAgICAgIyBub24tYWRtaW4gdG9rZW4gYW5kIG5vdGhpbmcgYWN0dWFsbHkgZ2V0cyByZW1vdmVkIGV2ZW4gdGhvdWdoCiAgICAgICAgICAgICMgdGhlIGV4aXQgY29kZSB3YXMgbmV2ZXIgY2hlY2tlZCBoZXJlIGJlZm9yZS4KICAgICAgICAgICAgaWYgKCRlbnRyeS5Vbmluc3RhbGxTdHJpbmcgLW1hdGNoICJtc2lleGVjIikgewogICAgICAgICAgICAgICAgJHByb2MgPSBTdGFydC1Qcm9jZXNzIC1GaWxlUGF0aCAibXNpZXhlYy5leGUiIC1Bcmd1bWVudExpc3QgQCgiL3giLCAkZW50cnkuUFNDaGlsZE5hbWUsICIvcXVpZXQiLCAiL25vcmVzdGFydCIpIC1WZXJiIFJ1bkFzIC1QYXNzVGhydSAtV2FpdAogICAgICAgICAgICB9IGVsc2UgewogICAgICAgICAgICAgICAgJHByb2MgPSBTdGFydC1Qcm9jZXNzIC1GaWxlUGF0aCAiY21kLmV4ZSIgLUFyZ3VtZW50TGlzdCBAKCIvYyIsICRlbnRyeS5Vbmluc3RhbGxTdHJpbmcsICIvcXVpZXQiKSAtVmVyYiBSdW5BcyAtUGFzc1RocnUgLVdhaXQKICAgICAgICAgICAgfQogICAgICAgICAgICBXcml0ZS1Mb2cgIlVuaW5zdGFsbCBwcm9jZXNzIGV4aXQgY29kZTogJCgkcHJvYy5FeGl0Q29kZSkiCiAgICAgICAgICAgIGlmICgkcHJvYy5FeGl0Q29kZSAtbmUgMCkgewogICAgICAgICAgICAgICAgJGFsbFJlbW92ZWQgPSAkZmFsc2UKICAgICAgICAgICAgICAgIFdyaXRlLUhvc3QgIiAgW0ZBSUxdINCa0L7QtCDQstC+0LfQstGA0LDRgtCwOiAkKCRwcm9jLkV4aXRDb2RlKSIgLUZvcmVncm91bmRDb2xvciBSZWQKICAgICAgICAgICAgfQogICAgICAgIH0KICAgICAgICBpZiAoJGFsbFJlbW92ZWQpIHsKICAgICAgICAgICAgV3JpdGUtTG9nICJKYXZhIHJlbW92YWw6IGFsbCBlbnRyaWVzIHJlcG9ydGVkIGV4aXQgY29kZSAwLiIKICAgICAgICAgICAgV3JpdGUtSG9zdCAiSmF2YSAyMSDRg9C00LDQu9C10L3QsC4iIC1Gb3JlZ3JvdW5kQ29sb3IgR3JlZW4KICAgICAgICB9IGVsc2UgewogICAgICAgICAgICBXcml0ZS1Mb2cgIkphdmEgcmVtb3ZhbDogYXQgbGVhc3Qgb25lIGVudHJ5IGZhaWxlZCAtIHNlZSBleGl0IGNvZGVzIGFib3ZlLiIKICAgICAgICAgICAgV3JpdGUtSG9zdCAi0J3QtSDRg9C00LDQu9C+0YHRjCDQv9C+0LvQvdC+0YHRgtGM0Y4g0YPQtNCw0LvQuNGC0YwgSmF2YSAo0YHQvC4g0LrQvtC0INCy0L7Qt9Cy0YDQsNGC0LAg0LLRi9GI0LUpLiDQktC+0LfQvNC+0LbQvdC+LCDQsdGL0Lsg0L7RgtC60LvQvtC90ZHQvSDQt9Cw0L/RgNC+0YEg0L3QsCDQv9GA0LDQstCwINCw0LTQvNC40L3QuNGB0YLRgNCw0YLQvtGA0LAgKFVBQykuIiAtRm9yZWdyb3VuZENvbG9yIFJlZAogICAgICAgIH0KICAgIH0gZWxzZSB7CiAgICAgICAgV3JpdGUtTG9nICJVc2VyIGNob3NlIHRvIGtlZXAgSmF2YS4iCiAgICAgICAgV3JpdGUtSG9zdCAiSmF2YSDQvtGB0YLQsNCy0LvQtdC90LAg0LHQtdC3INC40LfQvNC10L3QtdC90LjQuS4iCiAgICB9Cn0gZWxzZSB7CiAgICBXcml0ZS1Mb2cgIk5vIEphdmEgZW50cmllcyBmb3VuZCAtIHNraXBwaW5nIEphdmEgcmVtb3ZhbC4iCiAgICBXcml0ZS1Ib3N0ICJKYXZhIDIxIChUZW11cmluKSwg0YHQstGP0LfQsNC90L3QsNGPINGBINGN0YLQuNC8INGD0YHRgtCw0L3QvtCy0YnQuNC60L7QvCwg0L3QtSDQvdCw0LnQtNC10L3QsCAtINC/0YDQvtC/0YPRgdC60LDQtdC8LiIKfQoKV3JpdGUtSG9zdCAiIgpXcml0ZS1Ib3N0ICLQo9C00LDQu9C10L3QuNC1INC/0LDQv9C60Lgg0LzQvtC00L/QsNC60LA6ICRJbnN0YW5jZURpciIgLUZvcmVncm91bmRDb2xvciBDeWFuClN0YXJ0LVNsZWVwIC1TZWNvbmRzIDEKdHJ5IHsKICAgIFJlbW92ZS1JdGVtIC1MaXRlcmFsUGF0aCAkSW5zdGFuY2VEaXIgLVJlY3Vyc2UgLUZvcmNlIC1FcnJvckFjdGlvbiBTdG9wCiAgICBXcml0ZS1Mb2cgIk1vZHBhY2sgZm9sZGVyIHJlbW92ZWQgc3VjY2Vzc2Z1bGx5LiIKICAgIFdyaXRlLUhvc3QgItCc0L7QtNC/0LDQuiDRg9GB0L/QtdGI0L3QviDRg9C00LDQu9GR0L0uIiAtRm9yZWdyb3VuZENvbG9yIEdyZWVuCgogICAgIyBTZWxmLWNsZWFudXA6IHJlbW92ZSB0aGUgdW5pbnN0YWxsZXIgZmlsZXMgdGhlbXNlbHZlcyB0b28gKGJ1dCBub3QgdGhlCiAgICAjIGxvZyAtIHRoYXQncyBsZWZ0IGJlaGluZCBvbiBwdXJwb3NlIHNvIGl0IGNhbiBiZSBzZW50IGJhY2spLiBTYWZlIGF0CiAgICAjIHRoaXMgcG9pbnQgLS0gdGhpcyBzY3JpcHQgaXMgcnVubmluZyBmcm9tIGEgdGVtcCBjb3B5IChzZWUgdGhlIC5iYXQKICAgICMgdGhhdCBsYXVuY2hlZCBpdCksIHNvIHRoZSBvcmlnaW5hbHMgaW4gdGhlIGluc3RhbmNlcyBmb2xkZXIgYXJlbid0CiAgICAjIG9wZW4gYnkgYW55dGhpbmcgYW5kIGNhbiBiZSBkZWxldGVkIGxpa2UgYW55IG90aGVyIGZpbGUuCiAgICAkaW5zdGFuY2VzRGlyID0gU3BsaXQtUGF0aCAtUGFyZW50ICRJbnN0YW5jZURpcgogICAgUmVtb3ZlLUl0ZW0gLUxpdGVyYWxQYXRoIChKb2luLVBhdGggJGluc3RhbmNlc0RpciAidW5pbnN0YWxsLWluZnJhLW1vZHBhY2suYmF0IikgLUZvcmNlIC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlCiAgICBSZW1vdmUtSXRlbSAtTGl0ZXJhbFBhdGggKEpvaW4tUGF0aCAkaW5zdGFuY2VzRGlyICJ1bmluc3RhbGwtaW5mcmEtbW9kcGFjay5wczEiKSAtRm9yY2UgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUKCiAgICBTaG93LU1zZ0JveCAtTWVzc2FnZSAi0JzQvtC00L/QsNC6INGD0YHQv9C10YjQvdC+INGD0LTQsNC70ZHQvS4iIC1UaXRsZSAi0JPQvtGC0L7QstC+IiAtSWNvbiBJbmZvcm1hdGlvbiB8IE91dC1OdWxsCn0gY2F0Y2ggewogICAgV3JpdGUtTG9nICJFUlJPUiByZW1vdmluZyBtb2RwYWNrIGZvbGRlcjogJF8iCiAgICBXcml0ZS1Ib3N0ICLQntGI0LjQsdC60LAg0L/RgNC4INGD0LTQsNC70LXQvdC40Lg6ICRfIiAtRm9yZWdyb3VuZENvbG9yIFJlZAogICAgU2hvdy1Nc2dCb3ggYAogICAgICAgIC1NZXNzYWdlICLQndC1INGD0LTQsNC70L7RgdGMINC/0L7Qu9C90L7RgdGC0YzRjiDRg9C00LDQu9C40YLRjCDQv9Cw0L/QutGDINC80L7QtNC/0LDQutCwOmBuJF9gbmBu0J/QvtC/0YDQvtCx0YPQudGC0LUg0YPQtNCw0LvQuNGC0Ywg0LLRgNGD0YfQvdGD0Y46YG4kSW5zdGFuY2VEaXIiIGAKICAgICAgICAtVGl0bGUgItCe0YjQuNCx0LrQsCIgLUljb24gRXJyb3IgfCBPdXQtTnVsbAp9CgpXcml0ZS1Ib3N0ICIiCldyaXRlLUhvc3QgItCb0L7QsyDRgdC+0YXRgNCw0L3RkdC9INCyOiAkTG9nUGF0aCIgLUZvcmVncm91bmRDb2xvciBEYXJrR3JheQpXcml0ZS1Ib3N0ICLQndCw0LbQvNC40YLQtSBFbnRlciDQtNC70Y8g0LLRi9GF0L7QtNCwLi4uIiAtRm9yZWdyb3VuZENvbG9yIEdyYXkKUmVhZC1Ib3N0IHwgT3V0LU51bGwK'
    $uninstallPs1 = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($uninstallPs1B64))

    # Double-quoted here-string: this one needs $InstanceDirName interpolated
    # (a plain identifier, safe to expand -- unlike the .ps1 above there's no
    # risk of colliding with the generated content's own variable names).
    $uninstallBat = @"
@echo off
setlocal
set "PARENT_DIR=%~dp0"
if "%PARENT_DIR:~-1%"=="\" set "PARENT_DIR=%PARENT_DIR:~0,-1%"
set "INSTANCE_DIR=%PARENT_DIR%\$InstanceDirName"
set "TMPPS1=%TEMP%\mip-uninstall-%RANDOM%.ps1"
copy "%~dp0uninstall-infra-modpack.ps1" "%TMPPS1%" >nul
start "Uninstall Minecraft Infra Pack" powershell -NoExit -ExecutionPolicy Bypass -File "%TMPPS1%" -InstanceDir "%INSTANCE_DIR%"
exit /b
"@

    Set-Content -Path (Join-Path $TargetInstancesDir "uninstall-infra-modpack.ps1") -Value $uninstallPs1 -Encoding UTF8
    Set-Content -Path (Join-Path $TargetInstancesDir "uninstall-infra-modpack.bat") -Value $uninstallBat -Encoding ASCII
}

function New-PrismInstance {
    param([string]$BaseDir)

    $instanceDir = Join-Path $BaseDir $InstanceDirName
    $minecraftDir = Join-Path $instanceDir ".minecraft"

    if (Test-Path $instanceDir) {
        $overwrite = Show-MessageBox `
            -Message "An instance directory already exists at:`n$instanceDir`n`nOverwrite it?" `
            -Title "Instance Already Exists" `
            -Buttons YesNo `
            -Icon Warning

        if ($overwrite -ne [System.Windows.Forms.DialogResult]::Yes) {
            Write-Warn "Keeping existing instance. Exiting."
            exit 0
        }

        Write-Step "Removing existing instance directory..."
        Remove-Item -Recurse -Force $instanceDir
    }

    Write-Step "Creating instance directory structure..."
    New-Item -ItemType Directory -Force -Path $minecraftDir | Out-Null

    # --- instance.cfg ---
    Write-Step "Writing instance.cfg..."
    $instanceCfg = @"
InstanceType=OneSix
IntendedVersion=$McVersion
LogPrePostOutput=true
MaxMemAlloc=4096
MinMemAlloc=1024
OverrideJavaArgs=true
JvmArgs=-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200
OverrideCommands=true
PreLaunchCommand="`$INST_JAVA" -jar packwiz-installer-bootstrap.jar $PackwizPackUrl
iconKey=default
name=$PackName
"@
    Set-Content -Path (Join-Path $instanceDir "instance.cfg") -Value $instanceCfg -Encoding UTF8

    # --- mmc-pack.json ---
    Write-Step "Writing mmc-pack.json..."
    $mmcPack = @"
{
  "components": [
    {"cachedName": "LWJGL 3", "dependencyOnly": true, "uid": "org.lwjgl3", "version": "$LwjglVersion"},
    {"cachedName": "Minecraft", "important": true, "uid": "net.minecraft", "version": "$McVersion"},
    {"cachedName": "NeoForge", "uid": "net.neoforged", "version": "$NeoForgeVersion"}
  ],
  "formatVersion": 1
}
"@
    Set-Content -Path (Join-Path $instanceDir "mmc-pack.json") -Value $mmcPack -Encoding UTF8

    # --- packwiz-installer-bootstrap.jar ---
    # Must live inside .minecraft: Prism runs PreLaunchCommand with the
    # instance's .minecraft directory as its working directory, and the
    # command above references the jar by relative path.
    Write-Step "Downloading packwiz-installer-bootstrap.jar into instance..."
    $bootstrapDest = Join-Path $minecraftDir "packwiz-installer-bootstrap.jar"
    Get-PackwizBootstrap -DestinationPath $bootstrapDest

    Write-OK "Instance created at: $instanceDir"
    return $instanceDir
}

# ---------------------------------------------------------------------------
# Fallback - manual folder picker (only used if Prism's instances dir can't
# be determined, which shouldn't normally happen)
# ---------------------------------------------------------------------------

function Get-FallbackInstallDirectory {
    Show-MessageBox `
        -Message "Could not automatically determine Prism Launcher's instances folder.`n`nYou'll be asked to pick a folder instead - copy it into Prism's 'instances' directory yourself afterward." `
        -Title "Manual Location Needed" `
        -Icon Warning | Out-Null

    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description     = "Select where to create the modpack instance folder"
    $dialog.ShowNewFolderButton = $true
    $dialog.RootFolder      = [System.Environment+SpecialFolder]::UserProfile

    $result = $dialog.ShowDialog()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }

    return $dialog.SelectedPath
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

function Main {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  Minecraft Infra Pack - Windows Installer  " -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""

    try {
        # 1. Prism Launcher
        Write-Step "Checking for Prism Launcher..."
        $prismExe = Find-PrismLauncher
        if (-not $prismExe) {
            Write-Warn "Prism Launcher not found - prompting for installation."
            $prismExe = Install-PrismLauncher
        }
        Write-OK "Prism Launcher found: $prismExe"

        # 2. Locate its instances directory (falls back to a folder picker
        #    only if this genuinely can't be determined)
        Write-Step "Locating Prism Launcher's instances directory..."
        $instancesDir = $null
        try {
            $instancesDir = Get-PrismInstancesDir -PrismExePath $prismExe
        } catch {
            $instancesDir = $null
        }
        if (-not $instancesDir) {
            $instancesDir = Get-FallbackInstallDirectory
            if (-not $instancesDir) {
                Write-Warn "Installation cancelled by user."
                exit 0
            }
        }
        Write-OK "Instances directory: $instancesDir"

        Initialize-Log -Directory $instancesDir
        Write-OK "Script version: $ScriptVersion (log: $LogPath)"

        # 3. Java check / auto-install
        Confirm-JavaVersion

        # Always refresh the uninstaller pair, even if the user keeps their
        # existing instance below (New-PrismInstance can exit early in that
        # case). Otherwise a stale copy from an older version of this script
        # sits in the instances folder indefinitely and never self-heals.
        Write-Step "Refreshing uninstall scripts..."
        Write-UninstallScripts -TargetInstancesDir $instancesDir

        # 4. Create instance directly inside Prism's instances directory
        $instanceDir = New-PrismInstance -BaseDir $instancesDir

        # 5. Done
        Write-Host ""
        Write-Host "============================================" -ForegroundColor Green
        Write-Host "  Installation complete!                    " -ForegroundColor Green
        Write-Host "============================================" -ForegroundColor Green
        Write-Host ""

        Show-MessageBox `
            -Message "Installation complete!`n`nThe instance was created directly inside Prism Launcher's instances folder - no manual copying needed.`n`nNext steps:`n`n1. Open (or restart) Prism Launcher.`n2. Find and select '$PackName'.`n3. Click Launch - packwiz will automatically download all mods on first launch.`n4. Enjoy the server!`n`nInstance location:`n$instanceDir`n`nTo remove the modpack later, run uninstall-infra-modpack.bat, found one level up in the instances folder (not inside this one - that's intentional, so the uninstaller isn't deleting the folder it's running from)." `
            -Title "Installation Complete" `
            -Icon Information | Out-Null

    } catch {
        Write-Fail "An unexpected error occurred: $_"
        Write-Host ""
        Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
        Show-MessageBox `
            -Message "Installation failed with the following error:`n`n$_`n`nPlease check the console output for details." `
            -Title "Installation Failed" `
            -Icon Error | Out-Null
        exit 1
    }
}

# Wrapped so the window stays open on any exit path (success, handled error,
# or an unhandled exception) - otherwise "Run with PowerShell" closes the
# console the instant the script finishes, before you can read anything.
try {
    Main
} finally {
    Write-Host ""
    Write-Host "Press Enter to close this window..." -ForegroundColor Gray
    Read-Host | Out-Null
}
