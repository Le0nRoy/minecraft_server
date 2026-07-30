param(
    [Parameter(Mandatory=$true)]
    [string]$InstanceDir
)

Add-Type -AssemblyName System.Windows.Forms

function Show-MsgBox {
    param(
        [string]$Message,
        [string]$Title = "Удаление Minecraft Infra Pack",
        [System.Windows.Forms.MessageBoxButtons]$Buttons = [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]$Icon = [System.Windows.Forms.MessageBoxIcon]::Information
    )
    return [System.Windows.Forms.MessageBox]::Show($Message, $Title, $Buttons, $Icon)
}

Write-Host ""
Write-Host "=== Удаление Minecraft Infra Pack ===" -ForegroundColor Cyan
Write-Host ""

$confirm = Show-MsgBox `
    -Message "Удалить модпак Minecraft Infra Pack?`n`nБудет удалена вся папка:`n$InstanceDir`n`n(включая сохранения миров, конфиги и все моды)" `
    -Title "Подтверждение удаления" -Buttons YesNo -Icon Warning
if ($confirm -ne [System.Windows.Forms.DialogResult]::Yes) {
    Write-Host "Отменено пользователем."
    Read-Host "Нажмите Enter для выхода"
    exit 0
}

function Find-TemurinUninstallers {
    $paths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $found = @()
    foreach ($p in $paths) {
        Get-ItemProperty -Path $p -ErrorAction SilentlyContinue | Where-Object {
            $_.DisplayName -match "Temurin" -and $_.DisplayName -match "21"
        } | ForEach-Object { $found += $_ }
    }
    return $found
}

$javaEntries = Find-TemurinUninstallers
if ($javaEntries.Count -gt 0) {
    $names = ($javaEntries | ForEach-Object { $_.DisplayName }) -join "`n"
    $javaAnswer = Show-MsgBox `
        -Message "Найдена Java 21 (Eclipse Temurin), установленная вместе с этим модпаком:`n`n$names`n`nУдалить также Java 21?`n`nВыберите 'Нет', если Java используется другими программами на этом компьютере." `
        -Title "Удалить Java 21?" -Buttons YesNo -Icon Question

    if ($javaAnswer -eq [System.Windows.Forms.DialogResult]::Yes) {
        foreach ($entry in $javaEntries) {
            Write-Host "Удаление: $($entry.DisplayName)..." -ForegroundColor Cyan
            if ($entry.UninstallString -match "msiexec") {
                Start-Process -FilePath "msiexec.exe" -ArgumentList @("/x", $entry.PSChildName, "/quiet", "/norestart") -Wait
            } else {
                Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $entry.UninstallString, "/quiet") -Wait
            }
        }
        Write-Host "Java 21 удалена." -ForegroundColor Green
    } else {
        Write-Host "Java оставлена без изменений."
    }
} else {
    Write-Host "Java 21 (Temurin), связанная с этим установщиком, не найдена - пропускаем."
}

Write-Host ""
Write-Host "Удаление папки модпака: $InstanceDir" -ForegroundColor Cyan
Start-Sleep -Seconds 1
try {
    Remove-Item -LiteralPath $InstanceDir -Recurse -Force -ErrorAction Stop
    Write-Host "Модпак успешно удалён." -ForegroundColor Green

    # Self-cleanup: remove the uninstaller files themselves too. Safe at this
    # point -- this script is running from a temp copy (see the .bat that
    # launched it), so the originals in the instances folder aren't open by
    # anything and can be deleted like any other file.
    $instancesDir = Split-Path -Parent $InstanceDir
    Remove-Item -LiteralPath (Join-Path $instancesDir "uninstall-infra-modpack.bat") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $instancesDir "uninstall-infra-modpack.ps1") -Force -ErrorAction SilentlyContinue

    Show-MsgBox -Message "Модпак успешно удалён." -Title "Готово" -Icon Information | Out-Null
} catch {
    Write-Host "Ошибка при удалении: $_" -ForegroundColor Red
    Show-MsgBox `
        -Message "Не удалось полностью удалить папку модпака:`n$_`n`nПопробуйте удалить вручную:`n$InstanceDir" `
        -Title "Ошибка" -Icon Error | Out-Null
}

Write-Host ""
Write-Host "Нажмите Enter для выхода..." -ForegroundColor Gray
Read-Host | Out-Null