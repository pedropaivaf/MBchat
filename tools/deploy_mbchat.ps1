# Deploy MBChat installer em massa via SMB + schtasks remoto.
#
# Funciona em ambiente de DOMINIO com conta de administrador que tenha acesso
# ao share C$ de cada PC alvo. NAO depende de WinRM (que pode estar bloqueado
# em alguns ambientes). Usa schtasks /s para criar uma tarefa agendada remota
# rodando como SYSTEM, garantindo elevacao para o installer Inno Setup.
#
# Pre-requisitos:
#   1. Estar em uma conta de administrador de dominio (ou ter credencial)
#   2. Acesso SMB \\PC\C$ para cada PC alvo (firewall, share C$ ativo)
#   3. Servico "Schedule" rodando nos PCs (default em todo Windows Pro)
#   4. Arquivo MBChat_Setup.exe local ja gerado (rodar build.py antes)
#
# Como usar:
#
#   # 1. Gerar o installer localmente (apos commit do release):
#   python build.py --version 1.8.26 --release
#
#   # 2. Editar tools\pcs.txt e listar os 30 PCs (1 por linha)
#
#   # 3. Rodar o deploy:
#   .\tools\deploy_mbchat.ps1 `
#       -InstallerPath ".\dist\MBChat_Setup.exe" `
#       -PcListFile ".\tools\pcs.txt"
#
#   # OU com credencial diferente:
#   $cred = Get-Credential
#   .\tools\deploy_mbchat.ps1 -InstallerPath "..." -PcListFile "..." -Credential $cred
#
#   # OU testar sem instalar:
#   .\tools\deploy_mbchat.ps1 -InstallerPath "..." -PcListFile "..." -DryRun

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$InstallerPath,

    [Parameter(Mandatory=$true)]
    [string]$PcListFile,

    [PSCredential]$Credential,

    [switch]$DryRun,

    [int]$InstallTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# === Validacao ===
if (-not (Test-Path $InstallerPath)) {
    Write-Error "Installer nao encontrado: $InstallerPath"
    exit 1
}
if (-not (Test-Path $PcListFile)) {
    Write-Error "Lista de PCs nao encontrada: $PcListFile"
    exit 1
}

$InstallerPath = (Resolve-Path $InstallerPath).Path
$installerSize = (Get-Item $InstallerPath).Length
Write-Host ""
Write-Host "Installer: $InstallerPath ($([math]::Round($installerSize/1MB,1)) MB)" -ForegroundColor Cyan
Write-Host "Lista PCs: $PcListFile" -ForegroundColor Cyan

# Le lista de PCs (1 por linha, ignora vazias e comentarios #)
$pcs = Get-Content $PcListFile | Where-Object { $_ -and $_.Trim() -notmatch '^#' } | ForEach-Object { $_.Trim() }
Write-Host "PCs alvo: $($pcs.Count)" -ForegroundColor Cyan

if ($DryRun) { Write-Host "MODO DRY-RUN - nao vai instalar nada" -ForegroundColor Yellow }
Write-Host ""

# === Constantes do deploy ===
$REMOTE_DST = "C:\Windows\Temp\MBChat_Setup.exe"
$REMOTE_LOG = "C:\Windows\Temp\MBChat_Setup.log"
$TASK_NAME  = "MBChat_Deploy_$(Get-Date -Format 'yyyyMMddHHmmss')"

# Flags Inno Setup para install 100% silencioso e nao-interativo
# /CLOSEAPPLICATIONS - fecha MBChat antes (alem do CloseApplications=force no installer.iss)
# /SUPPRESSMSGBOXES - se aparecer qualquer dialog (uninstall confirma data), assume default
# /NORESTART - nunca reinicia o Windows mesmo se installer pedir
# /LOG - log local no PC alvo para debug
$INSTALL_FLAGS = "/VERYSILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /NORESTART /LOG=`"$REMOTE_LOG`""

# === Helpers ===
function Test-RemoteShare {
    param([string]$Pc, [PSCredential]$Cred)
    $share = "\\$Pc\C$"
    try {
        if ($Cred) {
            $name = "MBDep_$([guid]::NewGuid().ToString('N').Substring(0,8))"
            $null = New-PSDrive -Name $name -PSProvider FileSystem -Root $share -Credential $Cred -ErrorAction Stop
            $ok = Test-Path "${name}:\Windows"
            Remove-PSDrive -Name $name -ErrorAction SilentlyContinue
            return $ok
        } else {
            return Test-Path "$share\Windows"
        }
    } catch { return $false }
}

function Invoke-RemoteInstall {
    param([string]$Pc)
    # Cria task SYSTEM com Start-Time no passado, dispara via /run, depois deleta.
    $startTime = "00:00"
    $cmd = "cmd /c $REMOTE_DST $INSTALL_FLAGS"

    $null = & schtasks /create /s $Pc /tn $TASK_NAME `
        /tr $cmd /sc once /st $startTime `
        /ru "SYSTEM" /rl HIGHEST /f 2>&1
    if ($LASTEXITCODE -ne 0) { throw "schtasks /create falhou (exit $LASTEXITCODE)" }

    $null = & schtasks /run /s $Pc /tn $TASK_NAME 2>&1
    if ($LASTEXITCODE -ne 0) { throw "schtasks /run falhou (exit $LASTEXITCODE)" }

    # Aguarda a task voltar para Ready (terminou)
    $waited = 0
    $done = $false
    while ($waited -lt $InstallTimeoutSeconds) {
        Start-Sleep -Seconds 5
        $waited += 5
        try {
            $out = & schtasks /query /s $Pc /tn $TASK_NAME /fo LIST /v 2>&1 | Out-String
            if ($out -match "Status:\s+Ready|Em execução:\s+Não|Running:\s+No") {
                $done = $true; break
            }
        } catch {}
    }

    # Limpa task
    $null = & schtasks /delete /s $Pc /tn $TASK_NAME /f 2>&1

    if (-not $done) { throw "timeout aguardando install ($InstallTimeoutSeconds s)" }
}

# === Loop principal ===
$results = New-Object System.Collections.ArrayList

foreach ($pc in $pcs) {
    Write-Host "===> $pc" -ForegroundColor Cyan -NoNewline
    $r = [ordered]@{
        PC = $pc
        Ping = $false
        Share = $false
        Copy = $false
        Install = $false
        Version = $null
        Error = $null
    }

    # 1. Ping
    if (-not (Test-Connection -ComputerName $pc -Count 2 -Quiet -ErrorAction SilentlyContinue)) {
        Write-Host " [OFFLINE]" -ForegroundColor Red
        $r.Error = "ping falhou"
        $null = $results.Add([pscustomobject]$r)
        continue
    }
    $r.Ping = $true

    # 2. Share C$
    if (-not (Test-RemoteShare -Pc $pc -Cred $Credential)) {
        Write-Host " [SEM C$]" -ForegroundColor Red
        $r.Error = "sem acesso ao C$ (firewall ou credencial)"
        $null = $results.Add([pscustomobject]$r)
        continue
    }
    $r.Share = $true

    if ($DryRun) {
        Write-Host " [DRY-RUN OK]" -ForegroundColor Green
        $r.Install = "DRY-RUN"
        $null = $results.Add([pscustomobject]$r)
        continue
    }

    # 3. Copy installer
    $remotePath = "\\$pc\C$\Windows\Temp\MBChat_Setup.exe"
    try {
        Copy-Item -Path $InstallerPath -Destination $remotePath -Force -ErrorAction Stop
        $r.Copy = $true
    } catch {
        Write-Host " [COPY FAIL]" -ForegroundColor Red
        $r.Error = "copy falhou: $_"
        $null = $results.Add([pscustomobject]$r)
        continue
    }

    # 4. Run installer remoto via schtasks
    try {
        Invoke-RemoteInstall -Pc $pc
        $r.Install = $true
    } catch {
        Write-Host " [INSTALL FAIL]" -ForegroundColor Red
        $r.Error = "$_"
        Remove-Item -Path $remotePath -Force -ErrorAction SilentlyContinue
        $null = $results.Add([pscustomobject]$r)
        continue
    }

    # 5. Verifica versao instalada
    try {
        $exe = "\\$pc\C$\Program Files\MBChat\MBChat.exe"
        if (Test-Path $exe) {
            $r.Version = (Get-Item $exe).VersionInfo.FileVersion
        }
    } catch {}

    # 6. Cleanup installer
    Remove-Item -Path $remotePath -Force -ErrorAction SilentlyContinue

    Write-Host " [OK v$($r.Version)]" -ForegroundColor Green
    $null = $results.Add([pscustomobject]$r)
}

# === Relatorio final ===
Write-Host ""
Write-Host "============ RESUMO ============" -ForegroundColor Yellow
$results | Format-Table -AutoSize

$total = $results.Count
$ok = ($results | Where-Object { $_.Install -eq $true }).Count
$failed = $total - $ok

Write-Host ""
Write-Host "Total: $total" -ForegroundColor White
Write-Host "Sucesso: $ok" -ForegroundColor Green
Write-Host "Falhas: $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })

$report = "deploy_report_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
$results | Export-Csv -Path $report -NoTypeInformation -Encoding UTF8
Write-Host ""
Write-Host "Relatorio salvo: $report" -ForegroundColor Cyan

# Lista PCs que falharam (para retry/manual)
if ($failed -gt 0) {
    Write-Host ""
    Write-Host "PCs com falha (revisar manualmente):" -ForegroundColor Red
    $results | Where-Object { $_.Install -ne $true } | ForEach-Object {
        Write-Host "  - $($_.PC): $($_.Error)" -ForegroundColor Red
    }
}
