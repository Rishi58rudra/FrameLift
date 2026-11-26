# Windows packaging

The installer targets Windows x64 and installs for the current user. It bundles the embedded Python runtime, Tk, the Python packages, FFmpeg, model files and the Vulkan runner.

Run the commands below from the repository root on Windows. Use a working x64 Python 3.14.7 installation with Tcl/Tk and install `requirements.txt`. Install the [NSIS compiler](https://nsis.sourceforge.io/Download), then prepare:

- `work/framelift-pyembed/` with the contents of the [Python 3.14.7 embeddable x64 ZIP](https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip).
- `work/framelift-ffmpeg/` with the extracted Windows 9.1 essentials build from [Gyan's FFmpeg releases](https://github.com/GyanD/codexffmpeg/releases/tag/9.1). Keep its license and README files.

```powershell
python packaging/stage_framelift.py
python packaging/package_framelift.py manifest
makensis packaging/FrameLift.nsi
python packaging/package_framelift.py zip
python packaging/package_framelift.py cross
```

Find the distributables in `dist/`. NSIS builds an unsigned installer unless you configure signing separately. Source and notices for bundled third-party components are identified in the package.
