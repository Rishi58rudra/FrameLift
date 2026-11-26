FrameLift for Windows
=====================
Version 1.3.0
Created by rishirudracreations

For Windows x64, run FrameLift-Setup-x64.exe and launch FrameLift
from Start. The setup is unsigned and Windows may restrict it.
For the portable ZIP, extract the whole archive first. Double-click
Open FrameLift.cmd to run it portably. Double-click Install
FrameLift.cmd to install for the current Windows user, then
launch FrameLift from Start. The ZIP includes Python, the AI
weights and FFmpeg. The separate source folder uses the system
Python and FFmpeg.

For the macOS/Linux package, use Python 3.10 or newer with Tk and
install the Python packages from requirements.txt in a virtual
environment. Install FFmpeg and FFprobe for video, then run
sh launch.sh inside the extracted folder. Install an ncnn Vulkan
runner for your OS and architecture on PATH to enable GPU options.
CPU mode also works without the Vulkan runner. TkinterDnD2 enables
drag-and-drop where its native plugin supports the operating system.

Pick Image upscale or Video upscale,
then open a file or drop it into the window. Choose 2×, 4× or a custom
output width and click Upscale. Click Download PNG or Download MP4
when the result is ready, then choose where to save it. Download
saves the finished result without rendering it again. Save the
result before closing the app or opening another source.

Compare preview compares a center crop for a local preview, or the
finished output when available. For video, enter the timestamp in
seconds. Topaz Cloud comparison is available after a completed render.

Local engine
------------
Real-ESRGAN works without uploading media. The Processor menu offers:

  Auto: tries Vulkan first and falls back to the CPU if needed.
  GPU: uses the Vulkan device, or shows an error if unavailable.
  GPU Detail ensemble: combines eight passes with rotations and flips.
    Compare a preview to see if the longer render helps your source.
  CPU: uses the same model weights through OpenCV.

The System button shows what FrameLift detects. Medium reserves
more CPU capacity and uses smaller GPU batches. Max uses more CPU
threads, larger GPU batches and, on GPUs with more VRAM, larger
tiles. The settings apply to local jobs. Topaz Cloud uses its own
resources. Displayed ETA is an estimate calculated during a job.

GPU mode uses bounded tiles and batches video frames when they fit.
The render status shows the selected device or the CPU fallback.
Vulkan requires a working graphics driver and Microsoft's x64 Visual
C++ runtime. Cloud processing runs on Topaz's machines.

Video requires FFmpeg and FFprobe on PATH. The Windows launcher uses Python,
Tk, Pillow, NumPy and OpenCV, and installs missing image-processing
dependencies when needed. Drag-and-drop is bundled for x64 Windows.

The model's native scale is 4×. Other output sizes are resized from
that result. Local images export as 8-bit PNG with alpha if present.
Local videos export as SDR 8-bit MP4 with AAC audio, a constant frame
rate, and a limit of 8,192 pixels per side. Render time depends on
source dimensions, frame count, processor, and ensemble mode. Local
video enhancement processes individual frames.

Topaz Cloud for video
---------------------
Under Video upscale, choose Topaz Cloud · Proteus. Enter your own
API key when prompted, or set TOPAZ_API_KEY before opening the app.
FrameLift uses the key in memory for this session. Create a key at
https://account.topazlabs.com/manage-api

Click Upscale to get a free credit estimate. Approve the
estimate to upload the source and start a render that uses credits.
Cloud output dimensions round up to multiples of four. Save the
completed MP4 using Download MP4. If you cancel a cloud job that has
already started, Topaz may refund only part of the reserved credits.

Topaz API pricing: https://www.topazlabs.com/api
Topaz Video API: https://developer.topazlabs.com/getting-started/video-quickstart
Real-ESRGAN model: https://github.com/xinntao/Real-ESRGAN
Vulkan runner: https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan
