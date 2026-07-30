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
        $entries = @(Get-ItemProperty -Path $p -ErrorAction SilentlyContinue)
        $withName = @($entries | Where-Object { $_.PSObject.Properties.Name -contains "DisplayName" -and $_.DisplayName })
        # Named $javaMatches, not $matches - "$matches"/"$Matches" is a
        # PowerShell automatic variable that the -match operator itself
        # writes to, which is exactly the kind of thing worth not
        # shadowing even if it happens to work out here.
        $javaMatches = @($withName | Where-Object { $_.DisplayName -match "Temurin" -and $_.DisplayName -match "21" })
        foreach ($m in $javaMatches) { $found += $m }
    }
    # The comma operator forces this to be emitted as a single array object
    # instead of PowerShell unwrapping a one-element array into a bare
    # scalar on the pipeline - without it, when exactly one Java install is
    # found, the caller's `$javaEntries.Count` check silently misbehaves.
    return ,$found
}

$javaEntries = Find-TemurinUninstallers
if ($javaEntries.Count -gt 0) {
    $names = ($javaEntries | ForEach-Object { $_.DisplayName }) -join "`n"
    $javaAnswer = Show-MsgBox `
        -Message "Найдена Java 21 (Eclipse Temurin), установленная вместе с этим модпаком:`n`n$names`n`nУдалить также Java 21?`n`nВыберите 'Нет', если Java используется другими программами на этом компьютере." `
        -Title "Удалить Java 21?" -Buttons YesNo -Icon Question

    if ($javaAnswer -eq [System.Windows.Forms.DialogResult]::Yes) {
        $allRemoved = $true
        foreach ($entry in $javaEntries) {
            Write-Host "Удаление: $($entry.DisplayName)..." -ForegroundColor Cyan
            # This is a per-machine MSI install (HKLM, ALLUSERS=1) - removing
            # it needs the same elevation the installer requests when
            # installing it (-Verb RunAs), or msiexec silently fails under a
            # non-admin token and nothing actually gets removed.
            if ($entry.UninstallString -match "msiexec") {
                $proc = Start-Process -FilePath "msiexec.exe" -ArgumentList @("/x", $entry.PSChildName, "/quiet", "/norestart") -Verb RunAs -PassThru -Wait
            } else {
                $proc = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $entry.UninstallString, "/quiet") -Verb RunAs -PassThru -Wait
            }
            if ($proc.ExitCode -ne 0) {
                $allRemoved = $false
                Write-Host "  [FAIL] Код возврата: $($proc.ExitCode)" -ForegroundColor Red
            }
        }
        if ($allRemoved) {
            Write-Host "Java 21 удалена." -ForegroundColor Green
        } else {
            Write-Host "Не удалось полностью удалить Java (см. код возврата выше). Возможно, был отклонён запрос на права администратора (UAC)." -ForegroundColor Red
        }
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
