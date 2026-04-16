# Lista detalhes das regras de firewall relacionadas ao MBChat
Write-Host "=== REGRAS MBCHAT (detalhado) ===" -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName "*mbchat*" | ForEach-Object {
    $r = $_
    $app = ($r | Get-NetFirewallApplicationFilter).Program
    $port = ($r | Get-NetFirewallPortFilter)
    [PSCustomObject]@{
        Name  = $r.DisplayName
        Act   = $r.Action
        Dir   = $r.Direction
        Prog  = $app
        Proto = $port.Protocol
        Port  = $port.LocalPort
    }
} | Format-Table -AutoSize -Wrap

Write-Host "`n=== PORTAS UDP 50100-50120 ===" -ForegroundColor Cyan
Get-NetUDPEndpoint | Where-Object { $_.LocalPort -in 50100,50110,50120 } | ForEach-Object {
    $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Port    = $_.LocalPort
        Addr    = $_.LocalAddress
        PID     = $_.OwningProcess
        Process = $p.Name
    }
} | Format-Table -AutoSize

Write-Host "`n=== TCP LISTENERS 50101/50102/50199 ===" -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort 50101,50102,50199 -ErrorAction SilentlyContinue |
    Where-Object State -eq Listen | ForEach-Object {
    $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Port    = $_.LocalPort
        Addr    = $_.LocalAddress
        PID     = $_.OwningProcess
        Process = $p.Name
    }
} | Format-Table -AutoSize

Write-Host "`n=== IGMP GROUPS (multicast 239.255.100.200) ===" -ForegroundColor Cyan
netsh interface ipv4 show joins | Select-String "239.255.100.200"

Write-Host "`n=== PROCESSOS MBCHAT ===" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='MBChat.exe'" |
    Select-Object ProcessId, ExecutablePath | Format-Table -AutoSize
