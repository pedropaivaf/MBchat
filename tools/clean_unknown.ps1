# Limpa contatos "[Desconhecido]" do banco SQLite de todos os PCs via SMB + schtasks.
#
# Pre-requisitos: mesmos do deploy_mbchat.ps1 (admin de dominio, SMB C$, servico Schedule)
# Nao precisa de Python instalado nos PCs — usa sqlite3.exe standalone copiado localmente.
#
# ANTES DE RODAR:
#   1. Baixar sqlite3.exe de https://www.sqlite.org/download.html (sqlite-tools-win-x64-*.zip)
#      e colocar em tools\sqlite3.exe
#   OU deixar o script baixar automaticamente (precisa de internet no PC admin)
#
# Como usar:
#   .\tools\clean_unknown.ps1 -PcListFile ".\tools\pcs.txt"
#   .\tools\clean_unknown.ps1 -PcListFile ".\tools\pcs.txt" -DryRun

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$PcListFile,

    [PSCredential]$Credential,

    [switch]$DryRun,

    [string]$Sqlite3Path = "$PSScriptRoot\sqlite3.exe"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# === Garante sqlite3.exe ===
if (-not (Test-Path $Sqlite3Path)) {
    Write-Host "sqlite3.exe nao encontrado em $Sqlite3Path. Tentando baixar..." -ForegroundColor Yellow
    try {
        $zipUrl = "https://www.sqlite.org/2024/sqlite-tools-win-x64-3460100.zip"
        $zipTmp = "$env:TEMP\sqlite_tools.zip"
        $extractTmp = "$env:TEMP\sqlite_tools"
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipTmp -UseBasicParsing
        Expand-Archive -Path $zipTmp -DestinationPath $extractTmp -Force
        $found = Get-ChildItem $extractTmp -Recurse -Filter "sqlite3.exe" | Select-Object -First 1
        if (-not $found) { throw "sqlite3.exe nao encontrado no zip" }
        Copy-Item $found.FullName $Sqlite3Path
        Write-Host "sqlite3.exe baixado para $Sqlite3Path" -ForegroundColor Green
    } catch {
        Write-Error "Nao foi possivel obter sqlite3.exe: $_`nBaixe manualmente de https://sqlite.org/download.html e coloque em tools\sqlite3.exe"
        exit 1
    }
}
$Sqlite3Path = (Resolve-Path $Sqlite3Path).Path

if (-not (Test-Path $PcListFile)) {
    Write-Error "Lista de PCs nao encontrada: $PcListFile"
    exit 1
}

$pcs = Get-Content $PcListFile | Where-Object { $_ -and $_.Trim() -notmatch '^#' } | ForEach-Object { ($_ -split '#')[0].Trim() } | Where-Object { $_ }
Write-Host ""
Write-Host "sqlite3.exe: $Sqlite3Path" -ForegroundColor Cyan
Write-Host "PCs alvo: $($pcs.Count)" -ForegroundColor Cyan
if ($DryRun) { Write-Host "MODO DRY-RUN - nao vai alterar nada" -ForegroundColor Yellow }
Write-Host ""

$TASK_NAME = "MBChat_CleanUnknown_$(Get-Date -Format 'yyyyMMddHHmmss')"
$REMOTE_SQLITE = "C:\Windows\Temp\sqlite3_mbchat.exe"
$REMOTE_SCRIPT = "C:\Windows\Temp\mbchat_clean.ps1"

# Script PowerShell que roda no PC remoto como SYSTEM
# Busca todos os bancos em C:\Users\*\AppData\Roaming\.mbchat\mbchat.db e limpa
$CLEANUP_PS = @'
$ErrorActionPreference = "SilentlyContinue"
$log = "C:\Windows\Temp\mbchat_clean.log"
"$(Get-Date) iniciando limpeza" | Out-File $log

$sq = "C:\Windows\Temp\sqlite3_mbchat.exe"
$dbs = Get-ChildItem "C:\Users\*\AppData\Roaming\.mbchat\mbchat.db" -ErrorAction SilentlyContinue

if (-not $dbs) {
    "$(Get-Date) nenhum banco encontrado" | Out-File $log -Append
    exit 0
}

foreach ($db in $dbs) {
    $path = $db.FullName
    "$(Get-Date) limpando: $path" | Out-File $log -Append
    # Remove mensagens de peers sem nome resolvivel (causa dos [Desconhecido] no historico)
    $sql1 = "DELETE FROM messages WHERE (CASE WHEN is_sent=1 THEN to_user ELSE from_user END) NOT IN (SELECT user_id FROM contacts WHERE display_name != '' AND display_name IS NOT NULL) AND (CASE WHEN is_sent=1 THEN to_user ELSE from_user END) NOT IN (SELECT uid FROM group_members WHERE display_name != '' AND display_name IS NOT NULL);"
    # Remove contatos com nome vazio/desconhecido (defensivo)
    $sql2 = "DELETE FROM contacts WHERE display_name = '' OR display_name = 'Desconhecido' OR display_name LIKE '[Desconhecido]%' OR display_name = 'Unknown';"
    $result = (& $sq $path $sql1 2>&1) + (& $sq $path $sql2 2>&1)
    "$(Get-Date) resultado: $result (exit $LASTEXITCODE)" | Out-File $log -Append
}

"$(Get-Date) concluido" | Out-File $log -Append
'@

$results = New-Object System.Collections.ArrayList

foreach ($pc in $pcs) {
    Write-Host "===> $pc" -ForegroundColor Cyan -NoNewline
    $r = [ordered]@{
        PC      = $pc
        Online  = $false
        Share   = $false
        Done    = $false
        Error   = $null
    }

    # Testa porta 445
    $smb_ok = $false
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $ar = $tcp.BeginConnect($pc, 445, $null, $null)
        $waited = $ar.AsyncWaitHandle.WaitOne(2000, $false)
        if ($waited -and $tcp.Connected) { $smb_ok = $true }
        $tcp.Close()
    } catch {}
    if (-not $smb_ok) {
        Write-Host " [OFFLINE]" -ForegroundColor Red
        $r.Error = "porta 445 inacessivel"
        $null = $results.Add([pscustomobject]$r)
        continue
    }
    $r.Online = $true

    # Testa C$
    $sharePath = "\\$pc\C$"
    $shareOk = $false
    try {
        if ($Credential) {
            $name = "MBClean_$([guid]::NewGuid().ToString('N').Substring(0,8))"
            $null = New-PSDrive -Name $name -PSProvider FileSystem -Root $sharePath -Credential $Credential -ErrorAction Stop
            $shareOk = Test-Path "${name}:\Windows"
            Remove-PSDrive -Name $name -ErrorAction SilentlyContinue
        } else {
            $shareOk = Test-Path "$sharePath\Windows"
        }
    } catch {}
    if (-not $shareOk) {
        Write-Host " [SEM C$]" -ForegroundColor Red
        $r.Error = "sem acesso ao C$"
        $null = $results.Add([pscustomobject]$r)
        continue
    }
    $r.Share = $true

    if ($DryRun) {
        Write-Host " [DRY-RUN OK]" -ForegroundColor Green
        $r.Done = "DRY-RUN"
        $null = $results.Add([pscustomobject]$r)
        continue
    }

    # Copia sqlite3.exe para o PC remoto
    try {
        Copy-Item -Path $Sqlite3Path -Destination "\\$pc\C$\Windows\Temp\sqlite3_mbchat.exe" -Force -ErrorAction Stop
    } catch {
        Write-Host " [COPY FAIL]" -ForegroundColor Red
        $r.Error = "copy sqlite3 falhou: $_"
        $null = $results.Add([pscustomobject]$r)
        continue
    }

    # Copia script de limpeza
    try {
        $CLEANUP_PS | Out-File -FilePath "\\$pc\C$\Windows\Temp\mbchat_clean.ps1" -Encoding UTF8 -Force
    } catch {
        Write-Host " [COPY FAIL]" -ForegroundColor Red
        $r.Error = "copy script falhou: $_"
        $null = $results.Add([pscustomobject]$r)
        continue
    }

    # Roda via schtasks como SYSTEM
    try {
        $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $REMOTE_SCRIPT"
        $null = & schtasks /create /s $pc /tn $TASK_NAME /tr $cmd /sc once /st "00:00" /ru "SYSTEM" /rl HIGHEST /f 2>&1
        if ($LASTEXITCODE -ne 0) { throw "schtasks /create falhou" }
        $null = & schtasks /run /s $pc /tn $TASK_NAME 2>&1
        if ($LASTEXITCODE -ne 0) { throw "schtasks /run falhou" }

        # Aguarda terminar (max 30s)
        $waited = 0
        $done = $false
        while ($waited -lt 30) {
            Start-Sleep -Seconds 3; $waited += 3
            $out = & schtasks /query /s $pc /tn $TASK_NAME /fo LIST /v 2>&1 | Out-String
            if ($out -match "Status:\s+Ready|Em execução:\s+Não|Running:\s+No") { $done = $true; break }
        }
        $null = & schtasks /delete /s $pc /tn $TASK_NAME /f 2>&1

        if (-not $done) { throw "timeout aguardando script (30s)" }
        $r.Done = $true
        Write-Host " [OK]" -ForegroundColor Green
    } catch {
        Write-Host " [FAIL]" -ForegroundColor Red
        $r.Error = "$_"
    }

    # Cleanup remoto
    Remove-Item "\\$pc\C$\Windows\Temp\sqlite3_mbchat.exe" -Force -ErrorAction SilentlyContinue
    Remove-Item "\\$pc\C$\Windows\Temp\mbchat_clean.ps1"  -Force -ErrorAction SilentlyContinue

    $null = $results.Add([pscustomobject]$r)
}

# === Resumo ===
Write-Host ""
Write-Host "============ RESUMO ============" -ForegroundColor Yellow
$results | Format-Table -AutoSize

$ok     = ($results | Where-Object { $_.Done -eq $true }).Count
$failed = ($results | Where-Object { $_.Done -ne $true -and $_.Done -ne "DRY-RUN" }).Count

Write-Host "Sucesso: $ok" -ForegroundColor Green
Write-Host "Falhas/Offline: $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })
Write-Host ""
Write-Host "NOTA: O banco so e alterado quando o MBChat esta FECHADO no PC." -ForegroundColor Yellow
Write-Host "      Se o app estava aberto, feche e reabra para os nomes sumirem." -ForegroundColor Yellow

$report = "clean_report_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
$results | Export-Csv -Path $report -NoTypeInformation -Encoding UTF8
Write-Host "Relatorio: $report" -ForegroundColor Cyan
