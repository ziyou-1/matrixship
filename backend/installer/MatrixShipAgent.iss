; Inno Setup script for the MatrixShip local client (双击安装 -> 向导 -> 桌面图标直接用).
; Build: compile the PyInstaller onedir first (build_matrix_agent.ps1), then run:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" MatrixShipAgent.iss
; Output: ..\dist\installer\MatrixShipAgent-Setup.exe
;
; No code-signing cert: users get a Windows SmartScreen prompt on first run
; (更多信息 -> 仍要运行). The install itself needs no admin (installs to LocalAppData).

#define MyAppName "矩阵星舰本地客户端"
#define MyAppExeName "MatrixShipAgent.exe"
#define MyAppPublisher "MatrixShip"
#define MyAppVersion "1.1.16"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\MatrixShipAgent\app
DisableProgramGroupPage=yes
DisableDirPage=no
OutputDir=..\dist\installer
OutputBaseFilename=MatrixShipAgent-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\_internal\assets\app.ico

[Languages]
Name: "cn"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce
Name: "autostart"; Description: "开机自动启动(已配对后静默运行)"; GroupDescription: "启动选项:"; Flags: checkedonce

[Files]
; PyInstaller onedir output (build_matrix_agent.ps1 produces backend\dist\MatrixShipAgent\)
Source: "..\dist\MatrixShipAgent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\app.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\app.ico"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\app.ico"; Tasks: autostart

[Run]
; Launch right after install — the client window (full UI) opens; user logs in there.
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动客户端"; Flags: nowait postinstall skipifsilent
