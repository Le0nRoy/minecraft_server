#Requires -Version 5.1
<#
.SYNOPSIS
    Install the Minecraft Infra Pack modpack on Windows via Prism Launcher.

.DESCRIPTION
    This script:
      - Presents a native folder browser dialog so the user picks where to install
      - Verifies (or installs) Prism Launcher
      - Verifies Java 21+ is present
      - Creates a NeoForge 1.21.1 Prism Launcher instance with packwiz bootstrap
      - Shows a completion dialog with next steps

.NOTES
    Run from PowerShell 5.1+ (ships with Windows 10/11).
    If execution policy blocks the script, run:
        powershell -ExecutionPolicy Bypass -File install-client-windows.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

$PackName         = "Minecraft Infra Pack 1.21.1 (NeoForge)"
$InstanceDirName  = "minecraft-infra-pack"
$McVersion        = "1.21.1"
$NeoForgeVersion  = "21.1.244"
$LwjglVersion     = "3.3.3"
$BootstrapUrl     = "https://github.com/packwiz/packwiz-installer-bootstrap/releases/latest/download/packwiz-installer-bootstrap.jar"
$PackwizPackUrl   = "https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/packwiz/pack.toml"
$PrismDownloadUrl = "https://prismlauncher.org/download/windows"
$PrismDirectUrl   = "https://github.com/PrismLauncher/PrismLauncher/releases/latest/download/PrismLauncher-Windows-Setup.exe"

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

# ---------------------------------------------------------------------------
# Step 1 — Show info dialog and open folder browser
# ---------------------------------------------------------------------------

function Get-InstallDirectory {
    $infoResult = Show-MessageBox `
        -Message "Welcome to the Minecraft Infra Pack Installer.`n`nIn the next step you will be asked to select an install location for the modpack instance files.`n`nRecommended: choose a folder inside your Prism Launcher 'instances' directory, or any convenient location." `
        -Title "Minecraft Infra Pack Installer - Select install location" `
        -Buttons OK `
        -Icon Information

    if ($infoResult -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }

    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description     = "Select where to install the Minecraft modpack instance"
    $dialog.ShowNewFolderButton = $true
    $dialog.RootFolder      = [System.Environment+SpecialFolder]::UserProfile

    $result = $dialog.ShowDialog()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }

    return $dialog.SelectedPath
}

# ---------------------------------------------------------------------------
# Step 2 — Locate or install Prism Launcher
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
        -Message "Prism Launcher does not appear to be installed on this machine.`n`nWould you like to download and install it automatically?`n`n(Clicking 'No' will open the download page in your browser instead.)" `
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
            -Message "Please install Prism Launcher and re-run this script." `
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
# Step 3 — Check Java 21+
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

    # Match "17.0.9", "21", "1.8.0_xxx" etc.
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

# ---------------------------------------------------------------------------
# Step 4 — Download packwiz-installer-bootstrap.jar
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
# Step 5 — Create Prism Launcher instance
# ---------------------------------------------------------------------------

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
# Main
# ---------------------------------------------------------------------------

function Main {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  Minecraft Infra Pack - Windows Installer  " -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""

    try {
        # 1. Folder picker
        Write-Step "Waiting for install directory selection..."
        $installDir = Get-InstallDirectory
        if (-not $installDir) {
            Write-Warn "Installation cancelled by user."
            exit 0
        }
        Write-OK "Install directory: $installDir"

        # 2. Prism Launcher
        Write-Step "Checking for Prism Launcher..."
        $prismExe = Find-PrismLauncher
        if (-not $prismExe) {
            Write-Warn "Prism Launcher not found — prompting for installation."
            $prismExe = Install-PrismLauncher
        }
        Write-OK "Prism Launcher found: $prismExe"

        # 3. Java check
        Write-Step "Checking Java version..."
        $javaFound, $javaVersion = Test-JavaVersion
        if (-not $javaFound) {
            $javaAnswer = Show-MessageBox `
                -Message "Java does not appear to be installed or is not on the PATH.`n`nMinecraft $McVersion requires Java 21 or newer.`n`nWould you like to open the Java 21 download page?" `
                -Title "Java Not Found" `
                -Buttons YesNo `
                -Icon Warning

            if ($javaAnswer -eq [System.Windows.Forms.DialogResult]::Yes) {
                Start-Process "https://adoptium.net/temurin/releases/?version=21"
            }

            $continueAnyway = Show-MessageBox `
                -Message "Continue installation without verifying Java?`n`nThe instance will be created but may not launch until Java 21+ is installed." `
                -Title "Continue Without Java?" `
                -Buttons YesNo `
                -Icon Question

            if ($continueAnyway -ne [System.Windows.Forms.DialogResult]::Yes) {
                exit 1
            }
        } elseif ($javaVersion -ne -1 -and $javaVersion -lt 21) {
            $javaAnswer = Show-MessageBox `
                -Message "Java $javaVersion detected, but Minecraft $McVersion requires Java 21 or newer.`n`nWould you like to open the Java 21 download page?" `
                -Title "Java Version Too Old" `
                -Buttons YesNo `
                -Icon Warning

            if ($javaAnswer -eq [System.Windows.Forms.DialogResult]::Yes) {
                Start-Process "https://adoptium.net/temurin/releases/?version=21"
            }

            $continueAnyway = Show-MessageBox `
                -Message "Continue installation with Java $javaVersion?`n`nThe instance will be created but may not launch until Java 21+ is configured." `
                -Title "Continue With Old Java?" `
                -Buttons YesNo `
                -Icon Question

            if ($continueAnyway -ne [System.Windows.Forms.DialogResult]::Yes) {
                exit 1
            }
        } else {
            if ($javaVersion -eq -1) {
                Write-OK "Java detected (version could not be parsed — verify it is 21+)."
            } else {
                Write-OK "Java $javaVersion detected."
            }
        }

        # 4. Create instance
        $instanceDir = New-PrismInstance -BaseDir $installDir

        # 5. Done
        Write-Host ""
        Write-Host "============================================" -ForegroundColor Green
        Write-Host "  Installation complete!                    " -ForegroundColor Green
        Write-Host "============================================" -ForegroundColor Green
        Write-Host ""

        Show-MessageBox `
            -Message "Installation complete!`n`nNext steps:`n`n1. Open Prism Launcher.`n2. Choose 'Add Instance' > 'Import from zip or folder'.`n   (Or simply copy the instance folder into your Prism 'instances' directory.)`n3. Launch the '$PackName' instance.`n4. packwiz will automatically download all mods on first launch.`n5. Enjoy the server!`n`nInstance location:`n$instanceDir" `
            -Title "Installation Complete" `
            -Icon Information | Out-Null

    } catch {
        Write-Fail "An unexpected error occurred: $_"
        Show-MessageBox `
            -Message "Installation failed with the following error:`n`n$_`n`nPlease check the console output for details." `
            -Title "Installation Failed" `
            -Icon Error | Out-Null
        exit 1
    }
}

Main
