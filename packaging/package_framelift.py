from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import sys

root = Path("work/release/FrameLift")
entries = sorted(root.rglob("*"))
dist = Path("dist")
dist.mkdir(exist_ok=True)
if sys.argv[1] == "manifest":
    lines = []
    for entry in entries:
        if entry.is_file():
            lines.append(f'Delete "$INSTDIR\\{entry.relative_to(root)}"')
    folders = sorted((entry for entry in entries if entry.is_dir()),
                     key=lambda entry: -len(entry.parts))
    for entry in folders:
        lines.append(f'RMDir "$INSTDIR\\{entry.relative_to(root)}"')
    Path("work/framelift-uninstall.nsh").write_text("\n".join(lines) + "\n", encoding="utf-8")
elif sys.argv[1] == "cross":
    source = Path(".")
    with ZipFile(dist / "FrameLift-macOS-Linux.zip", "w", compression=ZIP_DEFLATED) as package:
        for name in ("app.py", "engine.py", "gpu_engine.py", "topaz_cloud.py", "hardware.py", "timing.py",
                     "README.txt", "launch.sh", "requirements.txt", "realesr-general-x4v3.onnx",
                     "Real-ESRGAN-LICENSE.txt"):
            package.write(source / name, Path("FrameLift") / name)
        for path in (source / "vulkan").rglob("*"):
            if path.is_file() and path.suffix != ".exe":
                package.write(path, Path("FrameLift") / path.relative_to(source))
else:
    with ZipFile(dist / "FrameLift-Windows-x64.zip", "w",
                 compression=ZIP_DEFLATED, compresslevel=3) as package:
        for entry in entries:
            if entry.is_file():
                package.write(entry, Path("FrameLift") / entry.relative_to(root))
