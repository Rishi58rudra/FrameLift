"""Vulkan runner for FrameLift's local Real-ESRGAN weights."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile

from PIL import Image

from engine import Cancelled, HIDDEN, Upscaler, check_cancel, finish_image, read_image
from hardware import MAX, basics, budget

AUTO = "Auto · GPU preferred"
GPU = "GPU · Vulkan"
ENSEMBLE = "GPU · Detail ensemble"
CPU = "CPU"
VULKAN = Path(__file__).with_name("vulkan")
DEVICE = re.compile(r"^\[\d+ (.+?)\]\s+queueC=", re.MULTILINE)
FAILURE = re.compile(r"^.*\b(?:failed|error|invalid|unsupported)\b.*$", re.I | re.MULTILINE)
TILE_PROGRESS = re.compile(r"^(\d+(?:\.\d+)?)%\s*$")


def runner_path():
    command = "realesrgan-ncnn-vulkan.exe" if os.name == "nt" else "realesrgan-ncnn-vulkan"
    bundled = VULKAN / command
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return bundled
    external = shutil.which(command)
    return Path(external) if external else None


class GpuError(RuntimeError):
    pass


class LocalUpscaler:
    def __init__(self, processor, hardware=None, profile=MAX):
        self.processor = processor
        self.profile = profile
        self.hardware = hardware or basics()
        self.resources = budget(self.hardware, profile)
        self.vulkan = processor != CPU
        self.cpu = None
        self.device = "Vulkan GPU" if self.vulkan else "CPU"

    def batch_capacity(self, width, height):
        # Keep batches bounded by the model's native 4× RGB frame size.
        return max(1, min(self.resources.batch_frames,
                          self.resources.batch_bytes // (width * height * 16 * 3))) if self.vulkan else 1

    def upscale(self, source, size, cancel, progress=None):
        return self.upscale_batch([source], size, cancel, progress)[0]

    def upscale_batch(self, sources, size, cancel, progress=None):
        if self.vulkan:
            try:
                return self.upscale_vulkan(sources, size, cancel, progress)
            except GpuError as failure:
                if self.processor != AUTO:
                    raise
                self.device = "CPU (GPU unavailable)"
                self.vulkan = False
                if progress:
                    progress(0, f"{failure} Using CPU.")
        if self.cpu is None:
            self.cpu = Upscaler(self.resources.cpu_threads, self.resources.cpu_tile)
        return [self.cpu.upscale(source, size, cancel, progress) for source in sources]

    def upscale_vulkan(self, sources, size, cancel, progress):
        runner = runner_path()
        if runner is None:
            raise GpuError("Vulkan engine is missing.")
        with tempfile.TemporaryDirectory(prefix="framelift-gpu-") as scratch:
            folder = Path(scratch)
            incoming, outgoing = folder / "in", folder / "out"
            incoming.mkdir()
            outgoing.mkdir()
            for index, source in enumerate(sources):
                check_cancel(cancel)
                source.convert("RGB").save(incoming / f"{index:04d}.png", compress_level=0)

            ensemble = self.processor == ENSEMBLE
            args = [
                str(runner), "-i", str(incoming), "-o", str(outgoing), "-f", "png",
                "-m", str(VULKAN / "models"), "-n", "realesrgan-framelift-x4",
                "-s", "4", "-t", str(min(80, self.resources.gpu_tile)
                                    if ensemble else self.resources.gpu_tile),
                "-j", f"{self.resources.gpu_io}:1:{self.resources.gpu_io}",
            ]
            if ensemble:
                args.append("-x")
            if progress:
                progress(0, "Running local GPU inference")
            log_path = folder / "runner.log"
            with log_path.open("wb") as log, log_path.open("r", encoding="utf-8", errors="replace") as live:
                try:
                    process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                               creationflags=HIDDEN)
                except OSError as failure:
                    raise GpuError("Vulkan engine could not start.") from failure
                try:
                    index = 0
                    last = -1
                    while process.poll() is None:
                        if cancel.wait(0.12):
                            raise Cancelled()
                        if progress:
                            for line in live.readlines():
                                match = TILE_PROGRESS.fullmatch(line.rstrip())
                                if match:
                                    tile = float(match[1])
                                    if tile <= last:
                                        index += 1
                                    last = tile
                                    fraction = (index + tile / 100) / len(sources)
                                    progress(min(0.98, fraction), "Running local GPU inference")
                    check_cancel(cancel)
                    output = log_path.read_text(encoding="utf-8", errors="replace")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

            device = DEVICE.search(output)
            error = FAILURE.search(output)
            if process.returncode or error or not device:
                reason = error.group().strip() if error else "No working Vulkan device reported."
                raise GpuError(f"GPU render failed. {reason}")
            name = device[1]
            if any(word in name.lower() for word in ("llvmpipe", "swiftshader", "software", "lavapipe")):
                raise GpuError("Vulkan is using a software device.")
            self.device = f"GPU · {name}"
            images = []
            for index, source in enumerate(sources):
                check_cancel(cancel)
                try:
                    result = read_image(outgoing / f"{index:04d}.png")
                except OSError as failure:
                    raise GpuError("Vulkan did not produce a readable frame.") from failure
                if result.size != (4 * source.width, 4 * source.height):
                    raise GpuError("Vulkan returned an unexpected frame size.")
                images.append(finish_image(result, source, size))
                if progress:
                    progress((index + 1) / len(sources), "GPU inference complete")
            return images
