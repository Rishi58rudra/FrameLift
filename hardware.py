"""Read workstation capabilities and select conservative local render budgets."""

from dataclasses import dataclass
import json
import os
import platform
import shutil
import subprocess

MEDIUM = "Medium"
MAX = "Max"
GIB = 1024**3


@dataclass(frozen=True)
class Hardware:
    system: str
    machine: str
    threads: int
    ram: int = 0
    gpu: str = ""
    vram: int = 0

    def summary(self):
        parts = [f"{self.system} {self.machine}", f"{self.threads} CPU threads"]
        if self.ram:
            parts.append(f"{self.ram / GIB:.0f} GB RAM")
        if self.gpu:
            parts.append(self.gpu + (f" · {self.vram / GIB:.0f} GB VRAM" if self.vram else ""))
        return "  |  ".join(parts)


@dataclass(frozen=True)
class Budget:
    cpu_threads: int
    cpu_tile: int
    gpu_tile: int
    gpu_io: int
    batch_frames: int
    batch_bytes: int


def basics():
    usable = getattr(os, "process_cpu_count", os.cpu_count)()
    return Hardware(platform.system(), platform.machine(), max(1, usable or 1))


def command(*args, timeout=5):
    path = shutil.which(args[0])
    if not path:
        return ""
    try:
        result = subprocess.run([path, *args[1:]], capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.decode("utf-8", errors="replace").strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def memory(system):
    if system == "Windows":
        import ctypes
        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_uint64) for name in
                ("total", "available", "page", "page_available", "virtual", "virtual_available", "extended")
            ]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        return status.total if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0
    if system == "Darwin":
        value = command("sysctl", "-n", "hw.memsize")
        return int(value) if value.isdecimal() else 0
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return 0


def graphics(system):
    lines = command("nvidia-smi", "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits").splitlines()
    cards = []
    for line in lines:
        name, separator, amount = line.strip().rpartition(",")
        if separator and amount.strip().isdecimal():
            cards.append((int(amount.strip()) * 1024**2, name.strip()))
    if cards:
        amount, name = max(cards)
        return name, amount
    if system == "Windows":
        listing = command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                          "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                          timeout=6)
        return " / ".join(listing.splitlines()[:2]), 0
    if system == "Darwin":
        listing = command("system_profiler", "SPDisplaysDataType", "-json")
        try:
            adapters = json.loads(listing or "{}").get("SPDisplaysDataType", [])
            return " / ".join(a.get("_name", "") for a in adapters[:2]).strip(" /"), 0
        except (ValueError, AttributeError):
            return "", 0
    listing = command("lspci")
    adapters = [line.split(": ", 1)[-1] for line in listing.splitlines()
                if any(kind in line for kind in ("VGA compatible", "3D controller", "Display controller"))]
    return " / ".join(adapters[:2]), 0


def detect():
    base = basics()
    gpu, vram = graphics(base.system)
    return Hardware(base.system, base.machine, base.threads, memory(base.system), gpu, vram)


def budget(hardware, profile):
    threads = hardware.threads
    if profile == MEDIUM:
        return Budget(max(1, min(6, (threads + 1) // 2)), 160, 96, 1, 4, 64 * 1024**2)
    cpu_threads = max(1, threads - (threads >= 4))
    cpu_tile = 256 if hardware.ram >= 12 * GIB else 192
    # Keep older cards and unknown adapters on the proven 128-pixel tile.
    gpu_tile = 256 if hardware.vram >= 8 * GIB else 192 if hardware.vram >= 6 * GIB else 128
    batch_bytes = min(384 * 1024**2, max(96 * 1024**2, (hardware.ram or 4 * GIB) // 32))
    return Budget(cpu_threads, cpu_tile, gpu_tile, max(1, min(3, threads // 2)), 12, batch_bytes)
