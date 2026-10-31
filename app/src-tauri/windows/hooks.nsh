; Game Night installer additions (Jayden's choice, 2026-10-31): a Windows Firewall rule that blocks anything from
; outside this PC reaching Game Night's own copy of RetroArch. RetroArch listens on every network address (its
; remote-control port and Couch Play's host port; measured), but Game Night only ever talks to it from this PC,
; and friends come in through Game Night's relay, so nothing from the network needs to reach it. A block rule
; wins over any "Allow" someone clicked on Windows' firewall question. Traffic inside this PC is never blocked.
; Windows asks for admin permission only when the rule is missing or points at an old folder.

!define GN_FW_RULE "Game Night: keep RetroArch off the network"

!macro GN_FW_HAS_RULE result
  ; netsh lists the rule with its program path when it exists.
  nsExec::ExecToStack '"$SYSDIR\netsh.exe" advfirewall firewall show rule name="${GN_FW_RULE}" verbose'
  Pop $R8
  Pop $R9
  ${StrLoc} ${result} "$R9" "$INSTDIR\player\retroarch.exe" ">"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  !insertmacro GN_FW_HAS_RULE $R7
  ${If} $R7 == ""
    ; Missing (or for another folder): replace it, as admin. Saying no just leaves things as they were.
    ExecShellWait "runas" "$SYSDIR\cmd.exe" '/c ""$SYSDIR\netsh.exe" advfirewall firewall delete rule name="${GN_FW_RULE}" & "$SYSDIR\netsh.exe" advfirewall firewall add rule name="${GN_FW_RULE}" dir=in action=block program="$INSTDIR\player\retroarch.exe" enable=yes profile=any"' SW_HIDE
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Removing Game Night (not updating it): take the rule away too.
  nsExec::Exec '"$SYSDIR\netsh.exe" advfirewall firewall show rule name="${GN_FW_RULE}"'
  Pop $R8
  ${If} $UpdateMode <> 1
  ${AndIf} $R8 == 0
    ExecShellWait "runas" "$SYSDIR\cmd.exe" '/c ""$SYSDIR\netsh.exe" advfirewall firewall delete rule name="${GN_FW_RULE}""' SW_HIDE
  ${EndIf}
!macroend
