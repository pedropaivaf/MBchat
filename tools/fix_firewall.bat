@echo off
REM MBChat - Corrige regras de firewall inbound para UDP/TCP
REM Uso: clique direito -> "Executar como administrador"
REM Resolve o bug onde o PC aparece online para os outros mas nao ve ninguem

echo ============================================
echo  MB Chat - Correcao de Firewall
echo ============================================
echo.

REM Verifica se esta rodando como admin
net session >nul 2>&1
if errorlevel 1 (
    echo ERRO: este script precisa ser executado como Administrador.
    echo.
    echo Clique com botao direito no arquivo e escolha
    echo "Executar como administrador".
    echo.
    pause
    exit /b 1
)

echo Removendo regras antigas...
netsh advfirewall firewall delete rule name="MBChat" >nul 2>&1
netsh advfirewall firewall delete rule name="MBChat UDP In" >nul 2>&1
netsh advfirewall firewall delete rule name="MBChat TCP In" >nul 2>&1
netsh advfirewall firewall delete rule name="MBChat UDP Out" >nul 2>&1
netsh advfirewall firewall delete rule name="MBChat TCP Out" >nul 2>&1

echo Criando novas regras de entrada (inbound)...
netsh advfirewall firewall add rule name="MBChat UDP In" dir=in action=allow protocol=UDP localport=50100,50110,50120 profile=any
netsh advfirewall firewall add rule name="MBChat TCP In" dir=in action=allow protocol=TCP localport=50101,50102,50199 profile=any

echo Criando novas regras de saida (outbound)...
netsh advfirewall firewall add rule name="MBChat UDP Out" dir=out action=allow protocol=UDP localport=50100,50110,50120 profile=any
netsh advfirewall firewall add rule name="MBChat TCP Out" dir=out action=allow protocol=TCP localport=50101,50102,50199 profile=any

echo.
echo Regras criadas com sucesso.
echo.
echo Reiniciando o MBChat...
taskkill /F /IM MBChat.exe >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%LOCALAPPDATA%\Programs\MBChat\MBChat.exe" (
    start "" "%LOCALAPPDATA%\Programs\MBChat\MBChat.exe"
) else if exist "C:\Program Files\MBChat\MBChat.exe" (
    start "" "C:\Program Files\MBChat\MBChat.exe"
) else if exist "%ProgramFiles%\MBChat\MBChat.exe" (
    start "" "%ProgramFiles%\MBChat\MBChat.exe"
) else (
    echo MBChat.exe nao encontrado nas pastas padrao.
    echo Abra manualmente pelo menu iniciar.
)

echo.
echo ============================================
echo  Pronto! Feche esta janela.
echo ============================================
echo.
pause
