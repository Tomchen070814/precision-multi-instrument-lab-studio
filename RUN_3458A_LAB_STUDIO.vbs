Option Explicit
Dim shell, fso, root, app, installedApp
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
installedApp = shell.ExpandEnvironmentStrings( _
    "%LOCALAPPDATA%\Programs\Precision Multi-Instrument Lab Studio\" & _
    "Precision-Multi-Instrument-Lab-Studio.exe")
app = installedApp

If Not fso.FileExists(app) Then
    app = fso.BuildPath(root, "dist\Precision-Multi-Instrument-Lab-Studio.exe")
End If

If fso.FileExists(app) Then
    shell.Run Chr(34) & app & Chr(34), 1, False
Else
    MsgBox "Run INSTALL_ONCE_WINDOWS.bat once. After installation, use the " & _
        "desktop shortcut.", 48, "Precision Multi-Instrument Lab Studio"
End If
