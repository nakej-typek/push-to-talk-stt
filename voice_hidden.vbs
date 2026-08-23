' Spustí voice.py skrytě a připisuje stdout+stderr do voice.log.
' Volá se z Task Scheduleru (the scheduled task), ne ze session.
Dim dir
Set WshShell = CreateObject("WScript.Shell")
dir = Replace(WScript.ScriptFullName, "\voice_hidden.vbs", "")
WshShell.CurrentDirectory = dir
WshShell.Run "cmd /c py """ & dir & "\voice.py"" >> """ & dir & "\voice.log"" 2>&1", 0, False
