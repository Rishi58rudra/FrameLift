@echo off
setlocal
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
where python >nul 2>&1
if errorlevel 1 (
    echo Install Python for Windows and add it to PATH, then open FrameLift again.
    pause
    exit /b 1
)
python -c "import tkinter, PIL, cv2, numpy" >nul 2>&1
if errorlevel 1 (
    echo Installing the local image-processing dependencies...
    python -m pip install Pillow opencv-python numpy
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
python app.py %*
if errorlevel 1 pause
