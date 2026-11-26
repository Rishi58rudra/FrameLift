Unicode true
!include "MUI2.nsh"
!include "x64.nsh"

Name "FrameLift"
Caption "FrameLift Setup"
BrandingText "rishirudracreations"
OutFile "..\dist\FrameLift-Setup-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\FrameLift"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
VIProductVersion "1.3.0.0"
VIAddVersionKey "ProductName" "FrameLift"
VIAddVersionKey "CompanyName" "rishirudracreations"
VIAddVersionKey "FileDescription" "FrameLift Setup"
VIAddVersionKey "FileVersion" "1.3.0.0"

!define MUI_ICON "..\work\release\FrameLift\FrameLift.ico"
!define MUI_UNICON "..\work\release\FrameLift\FrameLift.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION OpenFrameLift
!define MUI_FINISHPAGE_RUN_TEXT "Launch FrameLift"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\FrameLift"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "FrameLift requires 64-bit Windows."
    Abort
  ${EndIf}
FunctionEnd

Function OpenFrameLift
  Exec '"$INSTDIR\runtime\pythonw.exe" -B "$INSTDIR\app.py"'
FunctionEnd

Section "FrameLift"
  SetOutPath "$INSTDIR"
  File /r "..\work\release\FrameLift\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\FrameLift.lnk" "$INSTDIR\runtime\pythonw.exe" '-B "$INSTDIR\app.py"' "$INSTDIR\FrameLift.ico"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "FrameLift"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "rishirudracreations"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "1.3.0"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\FrameLift.ico"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\FrameLift.lnk"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  !include "..\work\framelift-uninstall.nsh"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
