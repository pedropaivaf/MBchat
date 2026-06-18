[Setup]
AppId={{MB-CHAT-APP}
AppName=MB Chat
AppVersion=1.8.29
AppVerName=MB Chat v1.8.29
AppPublisher=MB Contabilidade
DefaultDirName={autopf}\MBChat
DefaultGroupName=MB Chat
UninstallDisplayIcon={app}\MBChat.exe
UninstallDisplayName=MB Chat
OutputDir=dist
OutputBaseFilename=MBChat_Setup
SetupIconFile=assets\mbchat.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
CloseApplications=force
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"
Name: "autostart"; Description: "Iniciar MB Chat com o Windows"

[InstallDelete]
; EXEs soltos de versoes antigas (PyInstaller --onefile, builds manuais, desktop)
Type: files; Name: "{userdesktop}\MBChat.exe"
Type: files; Name: "{commondesktop}\MBChat.exe"
Type: files; Name: "{userappdata}\MBChat\MBChat.exe"
Type: files; Name: "{userappdata}\MBChat\MBChat_new.exe"
Type: files; Name: "{userappdata}\MBChat_new.exe"
Type: files; Name: "{localappdata}\Programs\MBChat.exe"
; Pasta inteira do install per-user antigo (LocalAppData)
Type: filesandordirs; Name: "{localappdata}\Programs\MBChat\_internal"
Type: filesandordirs; Name: "{localappdata}\Programs\MBChat"
; _internal solto em qualquer lugar
Type: filesandordirs; Name: "{userappdata}\MBChat\_internal"
Type: filesandordirs; Name: "{userdesktop}\_internal"
Type: filesandordirs; Name: "{commondesktop}\_internal"
; _internal do install atual (Program Files) — apaga ANTES de copiar para garantir
; pasta limpa sem DLLs/pyd orfas de versoes antigas. Roda apos UninstallPreviousVersion
; e antes de [Files]. O processo ja foi morto em CurStepChanged(ssInstall).
Type: filesandordirs; Name: "{app}\_internal"
; Resquicios de update (zip, staging, scripts PS, exes parciais) — NAO mexer no DB (.mbchat)
Type: filesandordirs; Name: "{userappdata}\MBChat\update_staging"
Type: files; Name: "{userappdata}\MBChat\MBChat_update.zip"
Type: files; Name: "{userappdata}\MBChat\update.ps1"
Type: files; Name: "{userappdata}\MBChat\update_pending.txt"
Type: files; Name: "{userappdata}\MBChat\MBChat_old.exe"
Type: files; Name: "{userappdata}\MBChat\MBChat_backup.exe"
Type: files; Name: "{userappdata}\MBChat\update.bat"
; Atalhos antigos em lugares variados (lnk sem grupo MB Chat)
Type: files; Name: "{userdesktop}\MB Chat.lnk"
Type: files; Name: "{userdesktop}\MBChat.lnk"
Type: files; Name: "{commondesktop}\MBChat.lnk"
Type: files; Name: "{userstartup}\MBChat.lnk"

[Files]
Source: "dist\MBChat\MBChat.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\MBChat\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MB Chat"; Filename: "{app}\MBChat.exe"
Name: "{group}\Desinstalar MB Chat"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MB Chat"; Filename: "{app}\MBChat.exe"; Tasks: desktopicon
Name: "{userstartup}\MB Chat"; Filename: "{app}\MBChat.exe"; Parameters: "--silent"; Tasks: autostart

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""MBChat TCP In"""; Flags: runhidden; StatusMsg: "Configurando firewall..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""MBChat"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""MBChat TCP In"" dir=in action=allow protocol=TCP localport=50101,50102 profile=any"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""MBChat TCP In Dynamic"" dir=in action=allow protocol=TCP localport=50060-50130 profile=any"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""MBChat UDP In"" dir=in action=allow protocol=UDP localport=50100 profile=any"; Flags: runhidden
Filename: "{app}\MBChat.exe"; Description: "Abrir MB Chat"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im MBChat.exe"; Flags: runhidden; RunOnceId: "KillApp"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""MBChat TCP In"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""MBChat TCP In Dynamic"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""MBChat UDP In"""; Flags: runhidden

[UninstallDelete]
Type: files; Name: "{app}\MBChat.exe"
Type: files; Name: "{app}\update.bat"
Type: files; Name: "{app}\update.log"
Type: files; Name: "{app}\mbchat.log"
Type: files; Name: "{userstartup}\MB Chat.lnk"
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]
// Mata MBChat.exe em todos os lugares (taskkill robusto) e roda o uninstaller da versao
// anterior em modo silencioso, garantindo que nao sobre nada antes de instalar a nova.
// Roda em ssInstall (antes dos arquivos serem copiados), ignora erros para nao bloquear
// a instalacao se nao houver versao anterior.
function GetUninstallerPath(): string;
var
  Key1, Key2, Path: string;
begin
  Result := '';
  // Inno Setup AppId formato no registro: {AppId}_is1
  Key1 := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{MB-CHAT-APP}_is1';
  Key2 := 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{MB-CHAT-APP}_is1';

  if RegQueryStringValue(HKEY_LOCAL_MACHINE, Key1, 'UninstallString', Path) then
    Result := Path
  else if RegQueryStringValue(HKEY_LOCAL_MACHINE, Key2, 'UninstallString', Path) then
    Result := Path
  else if RegQueryStringValue(HKEY_CURRENT_USER, Key1, 'UninstallString', Path) then
    Result := Path;

  // Remove aspas se vier com elas (o Inno salva entre aspas no registro)
  if (Length(Result) >= 2) and (Result[1] = '"') then
    Result := Copy(Result, 2, Length(Result) - 2);
end;

procedure KillMBChatProcesses();
var
  ResultCode: Integer;
begin
  // Mata MBChat.exe em todos os lugares conhecidos. Ignora exit code (1=nao tinha processo).
  Exec(ExpandConstant('{cmd}'), '/c taskkill /f /im MBChat.exe', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(800);
end;

procedure UninstallPreviousVersion();
var
  UninstallerPath: string;
  ResultCode: Integer;
begin
  UninstallerPath := GetUninstallerPath();
  if (UninstallerPath = '') or (not FileExists(UninstallerPath)) then
  begin
    // Entrada de registro orfa (aponta para unins000.exe inexistente): limpa para
    // nao deixar cruft que confunde reinstalacoes futuras. No-op se nao existir.
    RegDeleteKeyIncludingSubkeys(HKEY_LOCAL_MACHINE,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{MB-CHAT-APP}_is1');
    RegDeleteKeyIncludingSubkeys(HKEY_LOCAL_MACHINE,
      'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{MB-CHAT-APP}_is1');
    RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{MB-CHAT-APP}_is1');
    Exit;
  end;

  // Roda uninstaller anterior 100% silencioso. /NORESTART nunca reinicia,
  // /SUPPRESSMSGBOXES suprime o dialog "manter historico?" (assume manter).
  Exec(UninstallerPath,
    '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /KEEPDATA',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    KillMBChatProcesses();
    UninstallPreviousVersion();
    // Mata de novo apos uninstall (caso o uninstaller tenha relancado algo)
    KillMBChatProcesses();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CachePath, DataPath: string;
  Choice: Integer;
  KeepData, IsSilent: Boolean;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Durante o uninstall a funcao correta e UninstallSilent(). WizardSilent()
    // so existe no Setup e dispara "Cannot call WizardSilent function during
    // Uninstall", abortando a procedure antes da limpeza/pergunta de dados.
    IsSilent := UninstallSilent();

    RegDeleteValue(HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Run', 'MBChat');

    DeleteFile(ExpandConstant('{userstartup}\MB Chat.lnk'));

    // CachePath = %APPDATA%\MBChat   (sem ponto) — zip, scripts PS, staging do updater
    // DataPath  = %APPDATA%\.mbchat  (com ponto) — banco SQLite, historico, settings
    // Documents\MBFiles (arquivos recebidos) NUNCA e tocado em nenhuma situacao.
    CachePath := ExpandConstant('{userappdata}\MBChat');
    DataPath  := ExpandConstant('{userappdata}\.mbchat');

    // Blindagem: qualquer erro aqui nao pode abortar a procedure deixando a
    // limpeza/pergunta de dados pela metade (uninstall ja removeu os binarios).
    try
    if DirExists(CachePath) or DirExists(DataPath) then
    begin
      // Quando rodado em modo silencioso pelo novo installer (/SUPPRESSMSGBOXES),
      // assume manter dados — sem dialog.
      KeepData := True;
      if not IsSilent then
      begin
        Choice := MsgBox(
          'O que deseja fazer com seus dados?' + #13#10 + #13#10 +
          'SIM = Manter historico de mensagens, configuracoes e banco de dados' + #13#10 +
          '      (apenas arquivos temporarios de atualizacao serao removidos)' + #13#10 + #13#10 +
          'NAO = Remover TUDO: historico, configuracoes e banco de dados' + #13#10 +
          '      (a pasta de arquivos recebidos Documents\MBFiles nao sera tocada)' + #13#10 + #13#10 +
          'Pasta de dados: ' + DataPath,
          mbConfirmation, MB_YESNO);
        KeepData := (Choice = IDYES);
      end;

      if KeepData then
      begin
        // Mantem DataPath (.mbchat) intacto — DB, historico e settings preservados.
        // Limpa apenas arquivos temporarios de cache em CachePath (MBChat).
        if DirExists(CachePath) then
        begin
          DeleteFile(CachePath + '\MBChat_new.exe');
          DeleteFile(CachePath + '\MBChat_update.zip');
          DeleteFile(CachePath + '\update.bat');
          DeleteFile(CachePath + '\update.ps1');
          DeleteFile(CachePath + '\update.log');
          DeleteFile(CachePath + '\update_pending.txt');
          DeleteFile(CachePath + '\mbchat.log');
          DelTree(CachePath + '\update_staging', True, True, True);
        end;
      end
      else
      begin
        // Remove tudo: cache do updater + banco + historico + settings
        if DirExists(CachePath) then
          DelTree(CachePath, True, True, True);
        if DirExists(DataPath) then
          DelTree(DataPath, True, True, True);
      end;
    end;
    except
      // Engole qualquer erro — nao travar a desinstalacao com popup.
    end;
  end;
end;
