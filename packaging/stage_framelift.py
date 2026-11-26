from pathlib import Path
import shutil
import sys

from PIL import Image, ImageDraw

source = Path(".").resolve()
stage = Path("work/release/FrameLift").resolve()
stage.mkdir(parents=True, exist_ok=True)
skip_caches = shutil.ignore_patterns("__pycache__", "*.pyc")

icon = Image.new("RGBA", (256, 256))
draw = ImageDraw.Draw(icon)
draw.rounded_rectangle((8, 8, 248, 248), radius=56, fill="#171912")
draw.rounded_rectangle((53, 179, 203, 200), radius=10, fill="#d6ff32")
draw.polygon([(114, 154), (114, 98), (85, 127), (66, 109), (128, 48),
              (190, 109), (171, 127), (142, 98), (142, 154)], fill="#d6ff32")
icon.save(stage / "FrameLift.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])

for name in ("app.py", "engine.py", "gpu_engine.py", "topaz_cloud.py", "hardware.py", "timing.py",
             "realesr-general-x4v3.onnx", "Real-ESRGAN-LICENSE.txt", "README.txt"):
    shutil.copy2(source / name, stage / name)
for name in ("vulkan", "tkinterdnd2"):
    shutil.copytree(source / name, stage / name, dirs_exist_ok=True, ignore=skip_caches)

runtime = stage / "runtime"
shutil.copytree("work/framelift-pyembed", runtime, dirs_exist_ok=True)
(runtime / "python314._pth").write_text(
    "python314.zip\n.\nLib/site-packages\n..\n", encoding="ascii")
python = Path(sys.base_prefix)
for name in ("_tkinter.pyd", "tcl90.dll", "tcl9tk90.dll", "zlib1.dll"):
    shutil.copy2(python / "DLLs" / name, runtime / name)
shutil.copytree(python / "tcl", runtime / "tcl", dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("*.lib", "*.sh", "nmake"))
# The embeddable stdlib omits tkinter. Use the matching CPython version.
shutil.copytree(python / "Lib" / "tkinter", runtime / "tkinter",
                dirs_exist_ok=True, ignore=skip_caches)

site = python / "Lib" / "site-packages"
vendor_site = runtime / "Lib" / "site-packages"
for name in ("cv2", "numpy", "numpy.libs", "PIL"):
    shutil.copytree(site / name, vendor_site / name, dirs_exist_ok=True, ignore=skip_caches)
for pattern in ("opencv*.dist-info", "numpy-*.dist-info", "pillow-*.dist-info"):
    for metadata in site.glob(pattern):
        shutil.copytree(metadata, vendor_site / metadata.name, dirs_exist_ok=True, ignore=skip_caches)

media = stage / "media"
media.mkdir(exist_ok=True)
ffmpeg = next(Path("work/framelift-ffmpeg").rglob("ffmpeg.exe")).parent
for name in ("ffmpeg.exe", "ffprobe.exe"):
    shutil.copy2(ffmpeg / name, media / name)
for name in ("LICENSE", "README.txt"):
    shutil.copy2(ffmpeg.parent / name, media / name)
(media / "SOURCE.txt").write_text(
    "FFmpeg 9.1 Windows essentials build by Gyan Doshi (GPL).\n"
    "Build and included library information: https://www.gyan.dev/ffmpeg/builds/\n"
    "Binary release and build documentation: https://github.com/GyanD/codexffmpeg/releases/tag/9.1\n"
    "FFmpeg source release: https://ffmpeg.org/releases/ffmpeg-9.1.tar.xz\n",
    encoding="ascii",
)
stage.joinpath("Open FrameLift.cmd").write_text(
    '@echo off\nstart "" "%~dp0runtime\\pythonw.exe" -B "%~dp0app.py" %*\n', encoding="ascii")
stage.joinpath("Install FrameLift.cmd").write_text(
    '@echo off\nstart "" "%~dp0runtime\\pythonw.exe" -B "%~dp0setup_framelift.py"\n', encoding="ascii")
shutil.copy2("packaging/setup_framelift.py", stage)
print(stage)
