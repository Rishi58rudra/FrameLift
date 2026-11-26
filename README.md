# FrameLift

FrameLift is a desktop image and video upscaler created by **rishirudracreations**. It runs Real-ESRGAN locally on the CPU or a compatible Vulkan GPU. Topaz Cloud Proteus is available as an optional video engine for users with their own Topaz API key.

## Downloads

Get the installer and portable builds from [Releases](https://github.com/Rishi58rudra/FrameLift/releases/latest).

| Platform | Download | Start |
|---|---|---|
| Windows x64 (recommended) | `FrameLift-Windows-x64.zip` | Extract the whole ZIP. Run `Install FrameLift.cmd` and launch FrameLift from Start, or run `Open FrameLift.cmd` for portable use. Python and FFmpeg are included. |
| Alternative Windows EXE | `FrameLift-Setup-x64.exe` | Windows Application Control may block this unsigned installer with **Unknown publisher**. Use the ZIP install if that happens. |
| macOS / Linux | `FrameLift-macOS-Linux.zip` | Extract the ZIP and follow its README. Python with Tk and FFmpeg are required. |

## Use FrameLift

1. Open or drop an image or video into the window.
2. Choose 2×, 4× or a custom width. Use **System** to view detected hardware. **Medium** leaves more capacity for other apps and **Max** assigns more resources to local processing.
3. Click **Preview** to compare, or **Upscale** to process the file. The progress bar shows elapsed time and an ETA once enough work has completed.
4. Click **Download PNG** or **Download MP4** to save the output, then **Show in folder** to find it.

Topaz Cloud uploads a video only after you confirm the credit estimate. Enter your key in the app or supply `TOPAZ_API_KEY` in the environment. Local processing needs neither a key nor an upload.

## Run from source

Use Python 3.10 or newer with Tk. Install the dependencies in `requirements.txt` in a virtual environment. For video, install FFmpeg and FFprobe and add them to PATH.

```console
python -m pip install -r requirements.txt
python app.py
```

Windows includes a Vulkan runner under `vulkan/`. On macOS or Linux, install a compatible Real-ESRGAN ncnn Vulkan runner on PATH to enable GPU processing. CPU mode works without it. See [packaging instructions](packaging/README.md) to build Windows downloads.

## Verification

Windows image and video exports, GPU processing on a GeForce GT 740, Medium and Max profiles, progress timing and cancellation were exercised. The unsigned installer was built, but Application Control blocked its launch on the test PC. The portable app launched there. Linux hardware detection was exercised in WSL. Full Linux and macOS GUI rendering and live Topaz API rendering remain unverified.
