; ============================================================================
;  X (Twitter) 媒体下载器 —— Windows 安装包脚本 (Inno Setup 6)
;  编译：  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer\XMediaDownloader.iss
;  产物：  dist\XMediaDownloader-Setup-v1.1.0.exe
; ============================================================================

#define AppName "X 媒体下载器"
#define AppNameEn "X Media Downloader"
#define AppVersion "1.1.0"
#define AppExe "XMediaDownloader.exe"
#define RepoUrl "https://github.com/trumanisbest/x-media-downloader"

[Setup]
AppId={{B7C2F1A4-3D5E-4A6B-9C8D-2E1F0A3B5C7D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=trumanisbest
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}
AppUpdatesURL={#RepoUrl}/releases
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=trumanisbest
VersionInfoDescription=X (Twitter) 媒体下载器 · 下载博主图片与视频
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

; 装到当前用户目录，免管理员权限；也可由用户在向导里改
DefaultDirName={localappdata}\Programs\XMediaDownloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; 图标
SetupIconFile=..\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

OutputDir=..\..\dist
OutputBaseFilename=XMediaDownloader-Setup-v{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no
LicenseFile=..\..\LICENSE.txt

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[CustomMessages]
chinesesimplified.CreateDesktopIcon=创建桌面快捷方式
chinesesimplified.LaunchAfterInstall=安装完成后立即启动 {#AppName}
chinesesimplified.InstalledTo=已安装到：
chinesesimplified.UninstallProgram=卸载 {#AppName}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "附加任务:"; Flags: checkedonce
Name: "launchapp"; Description: "{cm:LaunchAfterInstall}"; GroupDescription: "附加任务:"; Flags: checkedonce

[Files]
; 整个桌面版目录（主程序 + 内置引擎 + 运行库），保持相对结构
Source: "..\..\dist\XMediaDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; 下载内容默认放这里（用户可在程序里改）
Name: "{app}\downloads"; Permissions: users-modify

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\使用说明.txt"; Filename: "{app}\使用说明.txt"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchAfterInstall}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;