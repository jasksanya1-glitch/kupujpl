' Run a .ps1 fully hidden (no console flash). Args: full path to ps1, then extra args.
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count < 1 Then
  WScript.Quit 1
End If
ps1 = WScript.Arguments(0)
extra = ""
Dim i
For i = 1 To WScript.Arguments.Count - 1
  extra = extra & " " & WScript.Arguments(i)
Next
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """" & extra
sh.Run cmd, 0, False
