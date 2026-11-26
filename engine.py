"""Local Real-ESRGAN inference and FFmpeg media I/O."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from fractions import Fraction
from threading import Event, Lock

import numpy as np
from PIL import Image, ImageOps

WEIGHTS = Path(__file__).with_name("realesr-general-x4v3.onnx")
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Cancelled(Exception):
    pass


class RenderCancel:
    """Cancel FFmpeg even if a worker is blocked on one of its pipes."""

    def __init__(self):
        self.event = Event()
        self.lock = Lock()
        self.processes = set()

    def clear(self):
        self.event.clear()

    def is_set(self):
        return self.event.is_set()

    def wait(self, timeout):
        return self.event.wait(timeout)

    def set(self):
        with self.lock:
            self.event.set()
            for process in self.processes:
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass

    @contextmanager
    def watch(self, process):
        with self.lock:
            self.processes.add(process)
        try:
            if self.is_set() and process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
            yield
        finally:
            with self.lock:
                self.processes.remove(process)


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled()


class Upscaler:
    def __init__(self, threads=None, tile=192):
        import cv2

        cv2.setNumThreads(threads or min(6, os.cpu_count() or 1))
        self.net = cv2.dnn.readNetFromONNX(np.frombuffer(WEIGHTS.read_bytes(), dtype=np.uint8))
        self.device = "CPU"
        self.tile = tile

    def batch_capacity(self, width, height):
        return 1

    def upscale_batch(self, frames, size, cancel, progress=None):
        return [self.upscale(frame, size, cancel, progress) for frame in frames]

    def upscale(self, source, size, cancel, progress=None):
        rgb = np.asarray(source.convert("RGB"))
        height, width = rgb.shape[:2]
        result = np.empty((height * 4, width * 4, 3), dtype=np.uint8)
        tile, pad = self.tile, 34
        total = ((height + tile - 1) // tile) * ((width + tile - 1) // tile)
        done = 0
        for y in range(0, height, tile):
            for x in range(0, width, tile):
                check_cancel(cancel)
                bottom, right = min(y + tile, height), min(x + tile, width)
                top_pad, left_pad = max(0, y - pad), max(0, x - pad)
                patch = rgb[top_pad:bottom + pad, left_pad:right + pad].astype(np.float32)
                patch /= 255
                self.net.setInput(np.ascontiguousarray(patch.transpose(2, 0, 1)[None]))
                patch_height, patch_width = patch.shape[:2]
                # PixelShuffle rearranges 48 output channels into RGB at 4×.
                residual = self.net.forward().reshape(3, 4, 4, patch_height, patch_width)
                residual = residual.transpose(3, 1, 4, 2, 0).reshape(
                    patch_height * 4, patch_width * 4, 3)
                start_y, start_x = 4 * (y - top_pad), 4 * (x - left_pad)
                cropped = residual[start_y:start_y + 4 * (bottom - y),
                                   start_x:start_x + 4 * (right - x)]
                baseline = patch[y - top_pad:bottom - top_pad, x - left_pad:right - left_pad]
                cropped += baseline.repeat(4, axis=0).repeat(4, axis=1)
                result[y*4:bottom*4, x*4:right*4] = np.rint(cropped.clip(0, 1) * 255)
                done += 1
                if progress:
                    progress(done / total, f"Image tile {done:,} of {total:,}")
        return finish_image(Image.fromarray(result), source, size)


def finish_image(image, source, size):
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    if "A" in source.getbands() or "transparency" in source.info:
        alpha = source.convert("RGBA").getchannel("A")
        image.putalpha(alpha.resize(size, Image.Resampling.LANCZOS))
    return image


def read_image(path):
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image)


def media_tool(name):
    suffix = ".exe" if os.name == "nt" else ""
    bundled = Path(__file__).parent / "media" / f"{name}{suffix}"
    return str(bundled) if bundled.is_file() else shutil.which(name)


def ffmpeg_args(*args):
    program = media_tool("ffmpeg")
    if not program:
        raise RuntimeError("FFmpeg is required for video. Add ffmpeg and ffprobe to PATH.")
    return [program, "-hide_banner", "-loglevel", "error", "-nostdin", *map(str, args)]


def run_media(args, cancel=None):
    if cancel is None:
        cancel = RenderCancel()
    check_cancel(cancel)
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=HIDDEN) as process:
        with cancel.watch(process):
            stdout, stderr = process.communicate()
        check_cancel(cancel)
        if process.returncode:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "Media read failed.")
        return stdout


def probe(path, cancel=None):
    tool = media_tool("ffprobe")
    if not tool:
        raise RuntimeError("FFprobe is required for video. Add it to PATH.")
    data = json.loads(run_media([
        tool, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ], cancel))
    video = next(
        (s for s in data["streams"] if s["codec_type"] == "video"
         and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    if not video:
        raise ValueError("This file has no video stream.")
    width, height = video["width"], video["height"]
    rotation = next((item["rotation"] for item in video.get("side_data_list", [])
                     if "rotation" in item), 0)
    if abs(round(rotation)) % 180 == 90:
        width, height = height, width
    rate = Fraction(30)
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = video.get(key)
        if value and value not in ("0/0", "0/1", "N/A"):
            rate = Fraction(value)
            break
    raw_duration = video.get("duration", data["format"].get("duration", "0"))
    duration = float(raw_duration) if raw_duration not in ("N/A", None) else 0.0
    frames = video.get("nb_frames", "")
    return width, height, rate, duration, video["index"], int(frames) if frames.isdecimal() else None


def video_frame(path, info, seconds, cancel=None):
    import io

    contents = run_media(ffmpeg_args(
        "-ss", max(0, seconds), "-i", path, "-map", f"0:{info[4]}",
        "-frames:v", 1, "-c:v", "png", "-f", "image2pipe", "pipe:1",
    ), cancel)
    if not contents:
        raise ValueError("No frame at this timestamp. Try an earlier time.")
    with Image.open(io.BytesIO(contents)) as image:
        return image.copy()


def export_video(model, source, target, info, size, cancel, progress):
    from contextlib import ExitStack

    width, height, fps, duration, index, source_frames = info
    decoder = ffmpeg_args(
        "-i", source, "-map", f"0:{index}", "-vf", f"fps={fps}",
        "-pix_fmt", "rgb24", "-threads:v", 1, "-f", "rawvideo", "pipe:1",
    )
    encoder = ffmpeg_args(
        "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{size[0]}x{size[1]}", "-framerate", fps,
        "-i", "pipe:0", "-i", source, "-map", "0:v:0", "-map", "1:a?",
        "-c:v", "libx264" if max(size) <= 4096 else "libx265",
        "-preset", "fast", "-crf", 17, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", target,
    )
    estimated = source_frames or (max(1, round(duration * fps)) if duration > 0 else None)
    bytes_per_frame = width * height * 3
    frames = 0
    with tempfile.TemporaryFile() as decoder_log, tempfile.TemporaryFile() as encoder_log, ExitStack() as tracked:
        reader = subprocess.Popen(decoder, stdout=subprocess.PIPE, stderr=decoder_log,
                                  creationflags=HIDDEN)
        writer = None
        try:
            tracked.enter_context(cancel.watch(reader))
            check_cancel(cancel)
            writer = subprocess.Popen(encoder, stdin=subprocess.PIPE, stderr=encoder_log,
                                      creationflags=HIDDEN)
            tracked.enter_context(cancel.watch(writer))
            while True:
                batch = []
                for _ in range(model.batch_capacity(width, height)):
                    check_cancel(cancel)
                    block = reader.stdout.read(bytes_per_frame)
                    if not block:
                        break
                    if len(block) != bytes_per_frame:
                        raise RuntimeError("FFmpeg returned an incomplete frame.")
                    batch.append(Image.frombytes("RGB", (width, height), block))
                if not batch:
                    break
                batch_start = frames

                def batch_progress(fraction, caption):
                    total = (batch_start + len(batch) * fraction) / estimated if estimated else 0
                    progress(min(0.98, total * 0.98),
                             f"Frames {batch_start+1:,}–{batch_start+len(batch):,} · {caption}")

                batch_progress(0, "Upscaling")
                for enhanced in model.upscale_batch(batch, size, cancel, batch_progress):
                    check_cancel(cancel)
                    writer.stdin.write(enhanced.tobytes())
                    frames += 1
                progress(min(0.98, frames / estimated * 0.98) if estimated else 0,
                         f"Processed {frames:,} frames")
            check_cancel(cancel)
            writer.stdin.close()
            progress(0.99, "Finalizing MP4")
            for process in (reader, writer):
                while process.poll() is None:
                    if cancel.wait(0.1):
                        raise Cancelled()
            if reader.returncode or writer.returncode or not frames:
                raise RuntimeError("Video export failed or contained no frames.")
        except (OSError, RuntimeError) as failure:
            check_cancel(cancel)
            logs = []
            for log in (decoder_log, encoder_log):
                log.seek(0)
                logs.append(log.read().decode(errors="replace").strip())
            raise RuntimeError("\n".join(filter(None, logs)) or str(failure)) from failure
        finally:
            for process in (reader, writer):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait()
            reader.stdout.close()
            if writer is not None:
                try:
                    writer.stdin.close()
                except OSError:
                    pass
