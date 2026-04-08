[Setup]
AppId={{MB-CHAT-APP}
AppName=MB Chat
AppVersion=1.2.0
AppVerName=MB Chat v1.2.0
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
Source: "dist\MBChat.exe"; DestDir: "{app}"; Flags: ignoreversion

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
Type: dirifempty; Name: "{app}"

[Code]
var
  KeepHistoryPage: TInputOptionWizardPage;

procedure InitializeUninstallProgressForm();
begin
  // Mata o processo antes de desinstalar
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataPath: string;
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDataPath := ExpandConstant('{userappdata}\MBChat');
    if DirExists(AppDataPath) then
    begin
      if MsgBox('Deseja manter o historico de mensagens e configuracoes?' + #13#10 + #13#10 +
                'Pasta: ' + AppDataPath, mbConfirmation, MB_YESNO) = IDNO then
      begin
        DelTree(AppDataPath, True, True, True);
      end
      else
      begin
        // Remove apenas arquivos temporarios, mantém o banco
        DeleteFile(AppDataPath + '\MBChat_new.exe');
        DeleteFile(AppDataPath + '\update.bat');
        DeleteFile(AppDataPath + '\update.log');
      end;
    end;
  end;
end;
