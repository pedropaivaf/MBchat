@echo off
title MB Chat - Teste de VPN Local (Simulador)
echo =======================================================
echo      MB Chat - Teste de VPN Local (Simulador)
echo =======================================================
echo.
echo Este script ira iniciar duas instancias do MB Chat no mesmo PC
echo simulando dois dispositivos em redes diferentes (com IPs distintos):
echo.
echo 1. Instancia LOCAL (Escritorio/Anchor) no IP 127.0.0.1
echo 2. Instancia REMOTE (VPN Externa) no IP 127.0.0.2
echo.
echo Iniciando limpeza de bancos de dados de teste antigos...
del /f /q "%APPDATA%\.mbchat\mbchat_local.db" 2>nul
del /f /q "%APPDATA%\.mbchat\mbchat_remote.db" 2>nul
echo Limpeza concluida!
echo.
echo Iniciando as duas instancias...
start python gui.py --instance local --bind-ip 127.0.0.1
start python gui.py --instance remote --bind-ip 127.0.0.2
echo.
echo =======================================================
echo Instrucoes de Teste:
echo =======================================================
echo 1. Na janela do "User_remote" (instancia da VPN):
echo    - Vá em Preferencias (no menu ou icone de engrenagem) > Rede
echo    - Ative a opção "Conectar fora da LAN (VPN)"
echo    - Adicione o IP "127.0.0.1" (IP do User_local) à lista de IPs manuais e salve.
echo.
echo 2. Os dois usuarios ("local" e "remote") deverao se descobrir mutuamente!
echo.
echo 3. Abra o chat entre eles e envie mensagens ou arquivos:
echo    - Como 127.0.0.2 nao consegue falar diretamente com a LAN real (aqui simulada),
echo      o MB Chat usara o mecanismo de fallback/relay encaminhando a mensagem via Anchor!
echo.
echo Pressione qualquer tecla para fechar este prompt de instrucoes...
pause > nul
