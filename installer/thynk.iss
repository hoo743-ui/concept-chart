; THYNK 윈도우 설치 마법사 (Inno Setup 6). installer/build.py가 BuildDir·OutDir·AppVersion을 넘겨 컴파일한다.
; 보안 프로그램이 의심하지 않게: 관리자 권한을 요구하지 않고(사용자 폴더에 설치), 실행 파일을 새로 만들거나 포장하지 않으며(서명된 python.org 파이썬을 그대로),
; 시작 프로그램은 레지스트리가 아니라 '시작프로그램' 폴더의 바로 가기로, AI 받기는 사용자가 고를 때만 ollama.com 공식 설치 파일을 받아 그 설치 화면을 그대로 띄운다.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B1E2F4A-6C2E-4C1B-9C55-7A1D0F3E2B71}
AppName=THYNK
AppVersion={#AppVersion}
AppVerName=THYNK {#AppVersion}
AppPublisher=THYNK
VersionInfoDescription=THYNK 설치 — 공부한 대화를 개념 노트로
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\THYNK
DefaultGroupName=THYNK
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile={#BuildDir}\thynk.ico
UninstallDisplayIcon={app}\thynk.ico
UninstallDisplayName=THYNK
InfoBeforeFile={#BuildDir}\NOTICE.txt
OutputDir={#OutDir}
OutputBaseFilename=THYNK-설치-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 THYNK 아이콘 만들기"
Name: "autostart"; Description: "윈도우를 켤 때 THYNK 기록 받기 켜기 (약 50MB 사용, 브라우저 확장이 답변을 보낼 곳)"; Flags: unchecked
Name: "claudecode"; Description: "Claude Code 대화 자동 수집 연결 (Claude Code를 쓰는 경우)"; Flags: unchecked
Name: "ai"; Description: "쉬운 설명 AI 받기 — Ollama + qwen3:4b, 약 6GB, 인터넷에서 받음 (나중에 해도 됩니다)"; Flags: unchecked

[Files]
Source: "{#BuildDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BuildDir}\thynk\*"; DestDir: "{app}\thynk"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BuildDir}\thynk.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\NOTICE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\THYNK"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\thynk\launcher.pyw"""; WorkingDir: "{app}\thynk"; IconFilename: "{app}\thynk.ico"
Name: "{autodesktop}\THYNK"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\thynk\launcher.pyw"""; WorkingDir: "{app}\thynk"; IconFilename: "{app}\thynk.ico"; Tasks: desktopicon
Name: "{userstartup}\THYNK 기록 받기"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\thynk\launcher.pyw"" --background"; WorkingDir: "{app}\thynk"; IconFilename: "{app}\thynk.ico"; Tasks: autostart

[Run]
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\thynk\kit\install_concept_hook.py"""; WorkingDir: "{app}\thynk"; StatusMsg: "Claude Code 연결 중…"; Flags: runhidden waituntilterminated; Tasks: claudecode
Filename: "{tmp}\OllamaSetup.exe"; StatusMsg: "Ollama 공식 설치 화면을 여는 중…"; Flags: waituntilterminated skipifdoesntexist; Tasks: ai
Filename: "{cmd}"; Parameters: "/c title THYNK AI 모델 받기 && echo 쉬운 설명 AI 모델(qwen3:4b, 약 2.5GB)을 받습니다. 끝나면 이 창은 닫혀요. && ""{localappdata}\Programs\Ollama\ollama.exe"" pull qwen3:4b"; StatusMsg: "AI 모델 받는 중…"; Flags: waituntilterminated skipifdoesntexist; Tasks: ai; Check: OllamaInstalled
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\thynk\launcher.pyw"""; WorkingDir: "{app}\thynk"; Description: "THYNK 열기"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\thynk\kit\install_concept_hook.py"" --uninstall"; WorkingDir: "{app}\thynk"; Flags: runhidden; RunOnceId: "unhook"; Tasks: claudecode
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -Command ""Get-Process | Where-Object {{ $_.Path -like '{app}\*' } | Stop-Process -Force"""; Flags: runhidden; RunOnceId: "stopapp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\thynk"
Type: files; Name: "{app}\autostart.flag"

[Code]
var
  DownloadPage: TDownloadWizardPage;

function OllamaInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('AI 받기', 'ollama.com에서 공식 설치 파일을 받는 중이에요 (약 1.9GB).', nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and WizardIsTaskSelected('ai') and not OllamaInstalled then begin
    DownloadPage.Clear;
    DownloadPage.Add('https://ollama.com/download/OllamaSetup.exe', 'OllamaSetup.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        if DownloadPage.AbortedByUser then
          Log('AI 받기 취소')
        else
          SuppressibleMsgBox('AI 설치 파일을 받지 못했어요. THYNK는 AI 없이 설치되고, 나중에 다시 받을 수 있어요.' + #13#10 + GetExceptionMessage, mbError, MB_OK, IDOK);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) then begin
    if WizardIsTaskSelected('autostart') then
      SaveStringToFile(ExpandConstant('{app}\autostart.flag'), 'on', False)
    else
      DeleteFile(ExpandConstant('{app}\autostart.flag'));
  end;
end;
