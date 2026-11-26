"""Install the fully bundled FrameLift app for the current Windows user."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tkinter as tk
from tkinter import messagebox
import winreg

SOURCE = Path(__file__).resolve().parent
PUBLISHER = "rishirudracreations"
VERSION = "1.3.0"
REGISTRY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FrameLift"

SHORTCUT_SCRIPT = r"""
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:FRAMELIFT_SHORTCUT)
$link.TargetPath = Join-Path $env:FRAMELIFT_HOME 'runtime\pythonw.exe'
$link.Arguments = '-B "' + (Join-Path $env:FRAMELIFT_HOME 'app.py') + '"'
$link.WorkingDirectory = $env:FRAMELIFT_HOME
$link.IconLocation = (Join-Path $env:FRAMELIFT_HOME 'FrameLift.ico') + ',0'
$link.Description = 'FrameLift by rishirudracreations'
$link.Save()
"""

UNINSTALL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$answer = [System.Windows.Forms.MessageBox]::Show(
  'Remove FrameLift? Your exported images and videos are kept.',
  'Uninstall FrameLift', 'YesNo', 'Question')
if ($answer -ne 'Yes') { exit }

$base = [IO.Path]::GetFullPath($PSScriptRoot)
$prefix = $base.TrimEnd('\') + '\'
$manifestPath = Join-Path $base 'install-files.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$folders = [Collections.Generic.HashSet[string]]::new()
try {
    foreach ($link in Get-ChildItem -LiteralPath (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs') -Filter 'FrameLift.lnk') {
        $shell = New-Object -ComObject WScript.Shell
        if ($shell.CreateShortcut($link.FullName).TargetPath -ieq (Join-Path $base 'runtime\pythonw.exe')) {
            Remove-Item -LiteralPath $link.FullName
        }
    }
    foreach ($relative in $manifest) {
        $path = [IO.Path]::GetFullPath((Join-Path $base $relative))
        if (-not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { continue }
        if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path }
        $parent = Split-Path -Path $path
        while ($parent.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            $null = $folders.Add($parent)
            $parent = Split-Path -Path $parent
        }
    }
    foreach ($folder in $folders | Sort-Object { -$_.Length }) {
        if ((Test-Path -LiteralPath $folder -PathType Container) -and
            -not (Get-ChildItem -LiteralPath $folder -Force | Select-Object -First 1)) {
            [IO.Directory]::Delete($folder)
        }
    }
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FrameLift'
    if ((Get-ItemProperty -LiteralPath $key -Name InstallLocation -ErrorAction SilentlyContinue).InstallLocation -ieq $base) {
        Remove-Item -LiteralPath $key
    }
    Remove-Item -LiteralPath $manifestPath
    Remove-Item -LiteralPath (Join-Path $base 'Uninstall FrameLift.cmd')
    Remove-Item -LiteralPath $PSCommandPath
    if (-not (Get-ChildItem -LiteralPath $base -Force | Select-Object -First 1)) {
        [IO.Directory]::Delete($base)
    }
    [void][System.Windows.Forms.MessageBox]::Show('FrameLift was removed.', 'Uninstall FrameLift')
} catch {
    [void][System.Windows.Forms.MessageBox]::Show(
        "Could not remove all files. Close FrameLift and run uninstall again.`n`n$($_.Exception.Message)",
        'Uninstall FrameLift')
}
"""


def install(destination, shortcut, registry=REGISTRY):
    if SOURCE == destination.resolve():
        raise ValueError("FrameLift is already running from its installation folder.")
    entries = sorted(path.relative_to(SOURCE) for path in SOURCE.rglob("*") if path.is_file())
    entries = [path for path in entries if "__pycache__" not in path.parts
               and path.name not in {"Install FrameLift.cmd", "setup_framelift.py"}]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="FrameLift-setup-", dir=destination.parent) as staged:
        payload = Path(staged) / "FrameLift"
        for relative in entries:
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / relative, target)
        (payload / "install-files.json").write_text(
            json.dumps([str(path) for path in entries]), encoding="utf-8")
        (payload / "Uninstall FrameLift.ps1").write_text(UNINSTALL_SCRIPT, encoding="utf-8")
        (payload / "Uninstall FrameLift.cmd").write_text(
            '@echo off\ncd /d "%TEMP%"\npowershell.exe -NoProfile -File "%~dp0Uninstall FrameLift.ps1"\n',
            encoding="ascii")
        if destination.exists():
            for entry in payload.rglob("*"):
                if entry.is_file():
                    target = destination / entry.relative_to(payload)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(entry, target)
        else:
            payload.replace(destination)
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SHORTCUT_SCRIPT],
        env={**os.environ, "FRAMELIFT_HOME": str(destination), "FRAMELIFT_SHORTCUT": str(shortcut)},
        check=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry) as key:
        settings = {
            "DisplayName": "FrameLift", "Publisher": PUBLISHER, "DisplayVersion": VERSION,
            "InstallLocation": str(destination), "DisplayIcon": str(destination / "FrameLift.ico"),
            "UninstallString": f'"{os.environ["ComSpec"]}" /d /c ""{destination / "Uninstall FrameLift.cmd"}""',
        }
        for name, value in settings.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for option in ("NoModify", "NoRepair"):
            winreg.SetValueEx(key, option, 0, winreg.REG_DWORD, 1)


def main():
    root = tk.Tk()
    root.withdraw()
    destination = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "FrameLift"
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "FrameLift.lnk"
    answer = messagebox.askyesno(
        "FrameLift Setup", f"Install FrameLift {VERSION} by {PUBLISHER}?\n\n"
        f"{destination}\n\nA FrameLift shortcut will appear in the Start menu.", parent=root)
    if answer:
        try:
            install(destination, shortcut)
        except (OSError, ValueError, subprocess.SubprocessError) as failure:
            messagebox.showerror("FrameLift Setup", str(failure), parent=root)
        else:
            messagebox.showinfo("FrameLift Setup", "Installed. Open FrameLift from Start.", parent=root)
    root.destroy()


if __name__ == "__main__":
    main()
