#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif

#define MyAppName "StockDailyApp"
#define MyAppDisplayName "A股每日股票评分系统"
#define MyAppExeName "StockDailyApp.exe"

[Setup]
AppId={{6F3B4204-1B33-4D15-A1F8-4C681E18A9B7}
AppName={#MyAppDisplayName}
AppVersion={#MyAppVersion}
AppPublisher=StockDailyApp
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppDisplayName}
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir=..\installer_output
OutputBaseFilename=StockDailyApp_Setup_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayName={#MyAppDisplayName}
#ifexist "..\resources\icons\stock_daily_app.ico"
SetupIconFile=..\resources\icons\stock_daily_app.ico
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
Name: "{localappdata}\StockDailyApp\database"
Name: "{localappdata}\StockDailyApp\outputs"
Name: "{localappdata}\StockDailyApp\logs"
Name: "{localappdata}\StockDailyApp\cache"
Name: "{localappdata}\StockDailyApp\runtime"
Name: "{localappdata}\StockDailyApp\config"
Name: "{localappdata}\StockDailyApp\models"

[Files]
Source: "..\dist\StockDailyApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppDisplayName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppDisplayName}"; Flags: nowait postinstall skipifsilent
