Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
python = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(python) Then
    If fso.FolderExists(root & "\vendor") Then
        python = "pythonw.exe"
    Else
        MsgBox "Run Setup SpokenSlate.cmd first.", vbExclamation, "SpokenSlate"
        WScript.Quit 1
    End If
End If
command = """" & python & """ """ & root & "\app.py"""
shell.Run command, 0, False
