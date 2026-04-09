[Setup]
AppId={{MB-CHAT-APP}
AppName=MB Chat
AppVersion=1.4.19
AppVerName=MB Chat v1.4.19
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
PrivilegesRequired=lowest
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

[Files]
Source: "dist\MBChat\MBChat.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\MBChat\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MB Chat"; Filename: "{app}\MBChat.exe"
Name: "{group}\Desinstalar MB Chat"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MB Chat"; Filename: "{app}\MBChat.exe"; Tasks: desktopicon
Name: "{userstartup}\MB Chat"; Filename: "{app}\MBChat.exe"; Parameters: "--silent"; Tasks: autostart

[Run]
Filename: "{app}\MBChat.exe"; Description: "Abrir MB Chat"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im MBChat.exe"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: files; Name: "{app}\MBChat.exe"
Type: files; Name: "{app}\update.bat"
Type: files; Name: "{app}\update.log"
Type: files; Name: "{app}\mbchat.log"
Type: files; Name: "{userstartup}\MB Chat.lnk"
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataPath: string;
  Choice: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Run', 'MBChat');

    DeleteFile(ExpandConstant('{userstartup}\MB Chat.lnk'));

    AppDataPath := ExpandConstant('{userappdata}\MBChat');
    if DirExists(AppDataPath) then
    begin
      Choice := MsgBox(
        'O que deseja fazer com seus dados?' + #13#10 + #13#10 +
        'SIM = Manter historico de mensagens (remove apenas arquivos temporarios)' + #13#10 +
        'NAO = Remover TUDO (historico, configuracoes, banco de dados)' + #13#10 + #13#10 +
        'Pasta: ' + AppDataPath,
        mbConfirmation, MB_YESNO);

      if Choice = IDNO then
      begin
        DelTree(AppDataPath, True, True, True);
      end
      else
      begin
        DeleteFile(AppDataPath + '\MBChat_new.exe');
        DeleteFile(AppDataPath + '\update.bat');
        DeleteFile(AppDataPath + '\update.log');
        DeleteFile(AppDataPath + '\mbchat.log');
      end;
    end;
  end;
end;
