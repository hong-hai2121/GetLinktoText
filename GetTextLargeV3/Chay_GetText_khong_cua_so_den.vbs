' ── Launcher khong hien cua so den cho GetTextLargeV3 (chay tren MAY NAY) ──
Dim fso, sh, here, pyw, target
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
here   = fso.GetParentFolderName(WScript.ScriptFullName)
pyw    = fso.BuildPath(here, "..\venv\Scripts\pythonw.exe")
target = fso.BuildPath(here, "run_lnk.pyw")
If Not fso.FileExists(pyw) Then
  MsgBox "Khong tim thay venv:" & vbCrLf & pyw, vbCritical, "GetTextLargeV3"
  WScript.Quit 1
End If
sh.CurrentDirectory = here
sh.Run """" & pyw & """ """ & target & """", 0, False
