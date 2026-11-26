"""FrameLift Windows desktop application."""

import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
import tempfile
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from engine import Cancelled, IMAGES, RenderCancel, check_cancel, export_video, probe
from engine import read_image, video_frame
from gpu_engine import AUTO, CPU, ENSEMBLE, GPU, LocalUpscaler, runner_path
from hardware import MAX, MEDIUM, basics, budget, detect
from timing import Timeline
from topaz_cloud import TopazVideo

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    TkinterDnD = None


BG, PANEL, PREVIEW = "#eeedf1", "#ffffff", "#181a17"
INK, MUTED, ACCENT = "#171812", "#5d6056", "#d6ff32"
LOCAL, CLOUD = "Local · Real-ESRGAN", "Topaz Cloud · Proteus"
CREATOR = "rishirudracreations"
VERSION = "1.3.0"


def place_window(root):
    left, top, right, bottom = 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
    if os.name == "nt":
        from ctypes import byref, windll
        from ctypes.wintypes import RECT
        area = RECT()
        if windll.user32.SystemParametersInfoW(48, 0, byref(area), 0):
            left, top, right, bottom = area.left, area.top, area.right, area.bottom
    width = max(640, min(1120, right - left - 48))
    height = max(480, min(740, bottom - top - 72))
    x = left + max(0, (right - left - width) // 2)
    y = top + max(0, (bottom - top - height - 30) // 2)
    root.geometry(f"{width}x{height}{x:+d}{y:+d}")


class FrameLift:
    def __init__(self, root):
        self.root = root
        root.title("FrameLift")
        icon = Path(__file__).with_name("FrameLift.ico")
        if os.name == "nt" and icon.is_file():
            root.iconbitmap(default=str(icon))
        root.minsize(640, 480)
        place_window(root)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.source = self.info = self.model = self.result = self.result_settings = None
        self.cache = tempfile.TemporaryDirectory(prefix="framelift-")
        self.api_key = os.environ.get("TOPAZ_API_KEY", "")
        self.mode = "image"
        self.events = Queue()
        self.cancel = RenderCancel()
        self.busy = self.closing = False
        self.started = self.last_saved = None
        self.hardware = basics()
        self.gpu_available = runner_path() is not None
        self.photos = [None, None]
        self.images = [None, None]
        self.scale = tk.StringVar(value="2×")
        self.width = tk.StringVar(value="3840")
        self.timestamp = tk.StringVar(value="0")
        self.backend = tk.StringVar(value=LOCAL)
        self.processor = tk.StringVar(value=AUTO if self.gpu_available else CPU)
        self.profile = tk.StringVar(value=MEDIUM)
        self.backend_note = tk.StringVar()
        self.hardware_text = tk.StringVar(value="Detecting hardware…")
        self.timeline_text = tk.StringVar(value="")
        self.percent_text = tk.StringVar(value="")
        self.file_text = tk.StringVar(value="No media selected")
        self.dimensions = tk.StringVar(value="Choose an image or video to begin.")
        self.status = tk.StringVar(value="Ready")
        self.build()
        root.bind("<Escape>", lambda event: self.stop())
        root.bind("<Control-o>", lambda event: self.open_button.invoke())
        root.bind("<Control-s>", lambda event: self.download_button.invoke())
        if hasattr(root, "TkdndVersion"):
            root.drop_target_register(DND_FILES)
            root.dnd_bind("<<DropEnter>>", self.drag_enter)
            root.dnd_bind("<<DropLeave>>", lambda event: self.drag_highlight(False))
            root.dnd_bind("<<Drop>>", self.drop_file)
        Thread(target=self.scan_hardware, daemon=True).start()
        root.after(75, self.poll)
        if len(sys.argv) > 1:
            root.after_idle(lambda: self.load_file(Path(sys.argv[1])))

    def label(self, parent, value, size=11, color=INK, background=BG, bold=False):
        options = {"textvariable": value} if isinstance(value, tk.Variable) else {"text": value}
        return tk.Label(parent, **options, bg=background, fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"), anchor="w")

    def build(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", padding=(13, 9), background=PANEL, foreground=INK,
                        bordercolor="#dbdce0", font=("Segoe UI", 10, "bold"))
        style.map("TButton", background=[("active", "#e7e8df")],
                  foreground=[("disabled", "#777a72")])
        style.configure("Accent.TButton", background=ACCENT, foreground=INK, bordercolor=ACCENT)
        style.map("Accent.TButton", background=[("active", "#e3ff75"), ("disabled", "#e3e5de")])
        style.configure("Dark.TButton", background="#282a22", foreground="#ffffff", bordercolor="#414437")
        style.map("Dark.TButton", background=[("active", "#3d4232")])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#dbded3",
                        bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)
        container = tk.Frame(self.root, bg=BG, padx=18, pady=14)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1, minsize=74)
        top = tk.Frame(container, bg="#171912", padx=16, pady=8)
        top.grid(row=0, column=0, sticky="ew")
        brand = tk.Frame(top, bg="#171912")
        brand.pack(side="left")
        self.label(brand, "FrameLift", 22, ACCENT, "#171912", bold=True).pack(fill="x")
        self.label(brand, f"Created by {CREATOR}", 9, "#d0d4c4", "#171912").pack(fill="x")
        ttk.Button(top, text="About", style="Dark.TButton", command=self.about).pack(side="right")
        self.open_button = ttk.Button(top, text="Open image…", style="Dark.TButton", command=self.choose_file)
        self.open_button.pack(side="right", padx=(0, 8))

        tabs = tk.Frame(container, bg=BG)
        tabs.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        self.image_tab = ttk.Button(tabs, text="Image upscale", command=lambda: self.set_mode("image"))
        self.video_tab = ttk.Button(tabs, text="Video upscale", command=lambda: self.set_mode("video"))
        self.image_tab.pack(side="left", padx=(0, 6))
        self.video_tab.pack(side="left")
        ttk.Button(tabs, text="System", command=self.show_system).pack(side="right")

        selected = tk.Frame(container, bg=PANEL, padx=12, pady=7)
        selected.grid(row=2, column=0, sticky="ew", pady=(0, 9))
        file_label = self.label(selected, self.file_text, 11, background=PANEL, bold=True)
        file_label.configure(width=1)
        file_label.pack(fill="x")
        details = self.label(selected, self.dimensions, 9, MUTED, PANEL)
        details.configure(width=1)
        details.pack(fill="x")
        info = self.label(selected, self.hardware_text, 9, MUTED, PANEL)
        info.configure(width=1)
        info.pack(fill="x")

        body = tk.Frame(container, bg=BG)
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        controls = tk.Frame(body, bg=PANEL)
        controls.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        settings_view = tk.Canvas(controls, width=206, height=1, bg=PANEL, highlightthickness=0)
        settings_view.pack(side="left", fill="y")
        scrollbar = ttk.Scrollbar(controls, orient="vertical", command=settings_view.yview)
        scrollbar.pack(side="right", fill="y")
        settings_view.configure(yscrollcommand=scrollbar.set)
        settings = tk.Frame(settings_view, bg=PANEL, padx=13, pady=10)
        settings_window = settings_view.create_window(0, 0, window=settings, anchor="nw", width=206)

        def resize_settings(event):
            settings_view.configure(scrollregion=(0, 0, event.width, event.height))

        def scroll_settings(event):
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            while widget is not None:
                if widget is settings_view or widget is settings:
                    settings_view.yview_scroll(-1 if event.delta > 0 else 1, "units")
                    return "break"
                widget = getattr(widget, "master", None)
            return None

        settings.bind("<Configure>", resize_settings)
        settings_view.bind("<Configure>", lambda event: settings_view.itemconfigure(
            settings_window, width=event.width))
        self.root.bind("<MouseWheel>", scroll_settings, add="+")
        self.label(settings, "Output settings", 11, background=PANEL, bold=True).pack(fill="x", pady=(0, 6))
        self.label(settings, "Engine", 10, MUTED, PANEL).pack(fill="x")
        self.backend_input = ttk.Combobox(settings, width=21, state="readonly",
                                          textvariable=self.backend)
        self.backend_input.pack(fill="x", pady=(2, 5))
        self.label(settings, "Processor", 10, MUTED, PANEL).pack(fill="x")
        self.processor_input = ttk.Combobox(settings, width=21, state="readonly",
                                            values=(AUTO, GPU, ENSEMBLE, CPU) if self.gpu_available else (CPU,),
                                            textvariable=self.processor)
        self.processor_input.pack(fill="x", pady=(2, 5))
        self.label(settings, "Performance", 10, MUTED, PANEL).pack(fill="x")
        self.profile_input = ttk.Combobox(settings, width=21, state="readonly", values=(MEDIUM, MAX),
                                          textvariable=self.profile)
        self.profile_input.pack(fill="x", pady=(2, 5))
        self.label(settings, "Scale", 10, MUTED, PANEL).pack(fill="x")
        self.scale_input = ttk.Combobox(settings, width=9, state="readonly",
                                        values=("2×", "4×", "Custom"), textvariable=self.scale)
        self.scale_input.pack(fill="x", pady=(2, 5))
        self.custom_fields = tk.Frame(settings, bg=PANEL)
        self.label(self.custom_fields, "Custom width (px)", 10, MUTED, PANEL).pack(fill="x")
        self.custom_input = ttk.Entry(self.custom_fields, width=7, textvariable=self.width)
        self.custom_input.pack(fill="x", pady=(2, 5))
        self.time_fields = tk.Frame(settings, bg=PANEL)
        self.label(self.time_fields, "Video preview (seconds)", 10, MUTED, PANEL).pack(fill="x")
        self.time_input = ttk.Entry(self.time_fields, width=7, textvariable=self.timestamp)
        self.time_input.pack(fill="x", pady=(2, 5))
        self.note = self.label(settings, self.backend_note, 9, MUTED, PANEL)
        self.note.configure(wraplength=175, justify="left")
        self.note.pack(fill="x", pady=(4, 0))

        comparison = tk.Frame(body, bg=BG)
        comparison.grid(row=0, column=1, sticky="nsew")
        comparison.rowconfigure(0, weight=1)
        self.views = []
        for column, title in enumerate(("Original", "Upscaled")):
            comparison.columnconfigure(column, weight=1, uniform="preview")
            panel = tk.Frame(comparison, bg=PANEL)
            panel.grid(row=0, column=column, sticky="nsew", padx=(0, 5) if not column else (5, 0))
            self.label(panel, title, 11, background=PANEL, bold=True).pack(fill="x", padx=13, pady=8)
            canvas = tk.Canvas(panel, bg=PREVIEW, relief="flat", highlightthickness=0)
            canvas.pack(fill="both", expand=True, padx=1, pady=(0, 1))
            canvas.bind("<Configure>", lambda event, i=column: self.draw(i))
            self.views.append(canvas)

        bar = tk.Frame(container, bg=PANEL, padx=11, pady=9)
        bar.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        bar.columnconfigure(0, weight=1)
        status_label = self.label(bar, self.status, 10, MUTED, PANEL)
        status_label.configure(width=1)
        status_label.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.download_button = ttk.Button(bar, text="Download PNG", command=self.download)
        self.download_button.grid(row=0, column=4, padx=(6, 0))
        self.upscale_button = ttk.Button(bar, text="Upscale", style="Accent.TButton",
                                         command=self.upscale)
        self.upscale_button.grid(row=0, column=3, padx=(6, 0))
        self.cancel_button = ttk.Button(bar, text="Cancel", command=self.stop)
        self.cancel_button.grid(row=0, column=2, padx=(6, 0))
        self.preview_button = ttk.Button(bar, text="Preview", command=self.preview)
        self.preview_button.grid(row=0, column=1)
        meter = tk.Frame(container, bg=BG)
        meter.grid(row=5, column=0, sticky="ew", pady=(5, 0))
        meter.columnconfigure(0, weight=1)
        time_label = self.label(meter, self.timeline_text, 9, MUTED)
        time_label.configure(width=1)
        time_label.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        self.label(meter, self.percent_text, 10, INK, bold=True).grid(row=0, column=1, sticky="e", padx=8)
        self.folder_button = ttk.Button(meter, text="Show in folder", command=self.show_saved)
        self.folder_button.grid(row=0, column=2)
        self.progress = ttk.Progressbar(meter, maximum=1)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        for variable in (self.scale, self.width, self.backend, self.processor, self.profile):
            variable.trace_add("write", self.update_settings)
        self.update_settings()

    def draw(self, index):
        canvas, source = self.views[index], self.images[index]
        width, height = canvas.winfo_width(), canvas.winfo_height()
        canvas.delete("all")
        if source is None:
            fallback = "Open or drop a file" if hasattr(self.root, "TkdndVersion") else "Open an image or video"
            canvas.create_text(width / 2, height / 2,
                               text=fallback if index == 0 and self.source is None
                               else "Generate a comparison preview",
                               fill="#d2d5cb", font=("Segoe UI", 11))
            return
        factor = min(max(1, width - 18) / source.width, max(1, height - 18) / source.height)
        size = (max(1, round(source.width * factor)), max(1, round(source.height * factor)))
        resample = Image.Resampling.BICUBIC if factor > 1 else Image.Resampling.LANCZOS
        display = source.resize(size, resample)
        self.photos[index] = ImageTk.PhotoImage(display)
        canvas.create_image(width / 2, height / 2, image=self.photos[index])

    def choose_file(self):
        formats = ("Images", " ".join("*" + ext for ext in sorted(IMAGES))) if self.mode == "image" else (
            "Videos", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.mpeg *.mts *.ts")
        name = filedialog.askopenfilename(filetypes=[formats, ("All files", "*")])
        if name:
            self.load_file(Path(name))

    def about(self):
        messagebox.showinfo("About FrameLift", f"FrameLift {VERSION}\nCreated by {CREATOR}",
                            parent=self.root)

    def scan_hardware(self):
        try:
            result = detect()
        except (OSError, ValueError):
            result = basics()
        self.events.put(("hardware", result))

    def show_system(self):
        resources = budget(self.hardware, self.profile.get())
        gpu_line = (
            f"Vulkan: runtime available. Compatibility checked when a GPU job starts.\n"
            f"GPU tile: {resources.gpu_tile}px · up to {resources.batch_frames} frames per batch."
            if self.gpu_available else "Vulkan: no runner found. Local processing uses the CPU."
        )
        messagebox.showinfo("System & performance",
                            f"{self.hardware.summary()}\n\n"
                            f"{self.profile.get()} profile · {resources.cpu_threads} CPU render threads.\n{gpu_line}",
                            parent=self.root)

    def show_saved(self):
        if not self.last_saved:
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer.exe", "/select,", str(self.last_saved)])
            else:
                command = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([command, str(self.last_saved.parent)])
        except OSError as error:
            messagebox.showerror("Open output folder", str(error), parent=self.root)

    def drag_highlight(self, active):
        for canvas in self.views:
            canvas.configure(highlightthickness=2 if active else 0, highlightbackground=ACCENT)

    def drag_enter(self, event):
        if self.busy:
            return "refuse_drop"
        self.drag_highlight(True)
        return "copy"

    def drop_file(self, event):
        self.drag_highlight(False)
        paths = self.root.tk.splitlist(event.data)
        if paths and not self.busy:
            self.load_file(Path(paths[0]))
        return "copy" if paths and not self.busy else "refuse_drop"

    def load_file(self, path):
        try:
            is_image = path.suffix.lower() in IMAGES
            original = read_image(path) if is_image else None
            info = original.size if is_image else probe(path)
            if original:
                original.thumbnail((850, 600), Image.Resampling.LANCZOS)
            self.clear_result()
            self.mode = "image" if is_image else "video"
            self.source, self.info, self.is_image = path, info, is_image
            if is_image:
                self.backend.set(LOCAL)
            self.file_text.set(path.name)
            self.images = [original, None]
            self.timestamp.set("0")
            self.status.set("Ready")
            self.reset_meter()
            self.update_settings()
            self.draw(0)
            self.draw(1)
        except Exception as failure:
            messagebox.showerror("Could not open media", str(failure), parent=self.root)

    def set_mode(self, mode):
        if mode == self.mode or self.busy:
            return
        self.mode = mode
        self.source = self.info = None
        self.images = [None, None]
        self.clear_result()
        self.file_text.set("No media selected")
        self.dimensions.set("Open or drop a video to begin." if mode == "video"
                            else "Open or drop an image to begin.")
        self.status.set("Ready")
        self.reset_meter()
        self.backend.set(LOCAL)
        self.update_settings()
        self.draw(0)
        self.draw(1)

    def clear_result(self):
        if self.result:
            self.result.unlink(missing_ok=True)
            self.result = None
            self.result_settings = None

    def output_size(self):
        width, height = self.info[:2]
        if self.scale.get() == "Custom":
            target_width = int(self.width.get())
            if target_width <= width:
                raise ValueError("Enter a custom width larger than the source width.")
            target_height = round(height * target_width / width)
        else:
            factor = 2 if self.scale.get() == "2×" else 4
            target_width, target_height = width * factor, height * factor
        if not self.is_image:
            multiple = 4 if self.backend.get() == CLOUD else 2
            target_width += -target_width % multiple
            target_height += -target_height % multiple
            if max(target_width, target_height) > 8192:
                raise ValueError("Video output supports up to 8,192 pixels per side.")
        elif target_width * target_height > 150_000_000:
            raise ValueError("Image output supports up to 150 megapixels.")
        if self.backend.get() == LOCAL and width * height * 16 > 150_000_000:
            raise ValueError("Source is too large for this local model's 4× working buffer.")
        return target_width, target_height

    def render_settings(self, size):
        backend = self.backend.get()
        return (backend, size, self.processor.get(), self.profile.get()) if backend == LOCAL else (backend, size)

    def update_settings(self, *_):
        ready = bool(self.source) and not self.busy
        video = self.mode == "video"
        mode = self.mode
        cloud = self.backend.get() == CLOUD
        self.open_button.configure(text=f"Open {mode}…", state="disabled" if self.busy else "normal")
        for tab, value in ((self.image_tab, "image"), (self.video_tab, "video")):
            tab.configure(style="Accent.TButton" if mode == value else "TButton",
                          state="disabled" if self.busy else "normal")
        self.backend_input.configure(values=(LOCAL, CLOUD) if video else (LOCAL,),
                                     state="readonly" if video and not self.busy else "disabled")
        self.processor_input.configure(state="disabled" if cloud or self.busy or not self.gpu_available else "readonly")
        self.profile_input.configure(state="disabled" if cloud or self.busy else "readonly")
        self.folder_button.configure(state="normal" if self.last_saved else "disabled")
        note = "Processes on this PC. No upload."
        if cloud:
            note = "Uploads to Topaz after you approve the credit estimate."
        elif self.processor.get() == ENSEMBLE:
            note = "Combines eight GPU passes. Use preview to compare."
        self.backend_note.set(note)
        if video:
            self.time_fields.pack(fill="x", before=self.note)
        else:
            self.time_fields.pack_forget()
        if self.scale.get() == "Custom":
            self.custom_fields.pack(fill="x", before=self.time_fields if video else self.note)
        else:
            self.custom_fields.pack_forget()
        self.scale_input.configure(state="disabled" if self.busy else "readonly")
        self.custom_input.configure(state="normal" if ready and self.scale.get() == "Custom" else "disabled")
        self.time_input.configure(state="normal" if ready and video else "disabled")
        self.cancel_button.configure(state="normal" if self.busy and not self.cancel.is_set() else "disabled")
        valid = ready
        if self.source:
            width, height = self.info[:2]
            extra = "" if self.is_image else f"  ·  {float(self.info[2]):.5g} fps"
            try:
                output_width, output_height = self.output_size()
                extra += f"    →    {output_width:,} × {output_height:,} output"
            except ValueError as failure:
                valid = False
                extra += f"    ·    {failure}"
            self.dimensions.set(f"{width:,} × {height:,}{extra}")
        cached = valid and self.result_settings == self.render_settings(self.output_size())
        self.preview_button.configure(state="normal" if valid and (not cloud or cached) else "disabled")
        self.upscale_button.configure(state="normal" if valid else "disabled")
        self.download_button.configure(text="Download MP4" if video else "Download PNG",
                                       state="normal" if self.result and not self.busy else "disabled")

    def start(self, job, *, local_model=False, caption="Preparing…"):
        processor = self.processor.get()
        profile = self.profile.get()
        hardware = self.hardware
        self.busy = True
        self.cancel.clear()
        self.reset_meter()
        self.started = Timeline()
        self.status.set(caption)
        self.update_settings()

        def run():
            try:
                if local_model and (self.model is None or self.model.processor != processor
                                    or self.model.profile != profile or self.model.hardware != hardware):
                    self.model = LocalUpscaler(processor, hardware, profile)
                check_cancel(self.cancel)
                self.events.put(("result", job()))
            except Cancelled:
                self.events.put(("cancelled", None))
            except Exception as failure:
                self.events.put(("error", str(failure)))
        Thread(target=run, daemon=True).start()

    def report(self, fraction, caption):
        self.events.put(("progress", (fraction, f"{caption}  ·  {self.model.device}")))

    def progress_update(self, fraction, caption):
        self.events.put(("progress", (fraction, caption)))

    def reset_meter(self):
        self.started = None
        self.progress["value"] = 0
        self.percent_text.set("")
        self.timeline_text.set("")

    def refresh_meter(self):
        timer = self.started
        if not timer or not self.busy:
            return
        timer.visible += (timer.fraction - timer.visible) * 0.35
        self.progress["value"] = timer.visible
        self.percent_text.set(f"{int(timer.fraction * 100)}%")
        state = "Cancelling" if self.cancel.is_set() else ""
        if not state and self.status.get().startswith("Topaz render:"):
            state = "Waiting for Topaz"
        self.timeline_text.set(timer.line(state))

    def preview(self):
        try:
            timestamp = 0 if self.is_image else float(self.timestamp.get())
            if not 0 <= timestamp < float("inf"):
                raise ValueError("Enter a nonnegative preview time in seconds.")
            width, height = self.output_size()
        except ValueError as failure:
            messagebox.showerror("Preview settings", str(failure), parent=self.root)
            return

        cached = self.result if self.result_settings == self.render_settings((width, height)) else None

        def render_preview():
            frame = read_image(self.source) if self.is_image else video_frame(
                self.source, self.info, timestamp, self.cancel)
            if cached:
                after = read_image(cached) if self.is_image else video_frame(
                    cached, probe(cached, self.cancel), timestamp, self.cancel)
                for original in (frame, after):
                    original.thumbnail((1000, 720), Image.Resampling.LANCZOS)
                return "preview", (frame, after), "Comparing the finished render"
            crop_width, crop_height = min(360, frame.width), min(260, frame.height)
            left, top = (frame.width - crop_width) // 2, (frame.height - crop_height) // 2
            before = frame.crop((left, top, left + crop_width, top + crop_height))
            size = (round(crop_width * width / self.info[0]), round(crop_height * height / self.info[1]))
            after = self.model.upscale(before, size, self.cancel, self.report)
            before = before.resize(size, Image.Resampling.BICUBIC)
            return "preview", (before, after), f"Center crop comparison  ·  {self.model.device}"

        self.start(render_preview, local_model=cached is None, caption="Generating preview…")

    def upscale(self):
        size = self.output_size()
        if self.backend.get() == CLOUD:
            if not self.api_key:
                key = simpledialog.askstring("Topaz API key",
                    "Enter your Topaz API key. It stays in this session.", show="•", parent=self.root)
                if not key or not key.strip():
                    return
                self.api_key = key.strip()
            client = TopazVideo(self.api_key)
            self.start(lambda: ("quote", client, client.quote(self.source, self.info, size), size),
                       caption="Getting Topaz credit estimate…")
        else:
            self.render(size)

    def render(self, size, client=None, quote=None):
        settings = self.render_settings(size)
        suffix = ".png" if self.is_image else ".mp4"

        def write_result():
            with tempfile.NamedTemporaryFile(suffix=suffix, dir=self.cache.name, delete=False) as handle:
                path = Path(handle.name)
            try:
                if self.is_image:
                    self.model.upscale(read_image(self.source), size, self.cancel, self.report).save(path)
                elif client:
                    client.render(quote, self.source, path, self.cancel, self.progress_update, size)
                else:
                    export_video(self.model, self.source, path, self.info, size,
                                 self.cancel, self.report)
                check_cancel(self.cancel)
                thumbs = None
                try:
                    if self.is_image:
                        thumbs = (read_image(self.source), read_image(path))
                    else:
                        thumbs = (
                            video_frame(self.source, self.info, 0, self.cancel),
                            video_frame(path, probe(path, self.cancel), 0, self.cancel),
                        )
                    for thumb in thumbs:
                        thumb.thumbnail((1000, 720), Image.Resampling.LANCZOS)
                except (OSError, ValueError, RuntimeError):
                    thumbs = None
                check_cancel(self.cancel)
                device = "Topaz Cloud · Proteus" if client else self.model.device
                return "render", path, settings, thumbs, device
            except BaseException:
                path.unlink(missing_ok=True)
                raise

        self.start(write_result, local_model=client is None,
                   caption="Connecting to Topaz…" if client else "Preparing local upscale…")

    def download(self):
        suffix = ".png" if self.is_image else ".mp4"
        name = filedialog.asksaveasfilename(
            initialdir=str(self.source.parent), initialfile=self.source.stem + "_upscaled" + suffix,
            defaultextension=suffix, filetypes=[("PNG image" if self.is_image else "MP4 video", "*" + suffix)])
        if not name:
            return
        destination = Path(name)
        if destination.suffix.lower() != suffix or destination.resolve() == self.source.resolve():
            messagebox.showerror("Choose another filename",
                                 f"Use a different file from the input and the {suffix} extension.",
                                 parent=self.root)
            return

        def write_export():
            fd, temporary = tempfile.mkstemp(suffix=suffix, prefix=".framelift-", dir=destination.parent)
            os.close(fd)
            try:
                with self.result.open("rb") as source, open(temporary, "wb") as output:
                    while block := source.read(4_194_304):
                        check_cancel(self.cancel)
                        output.write(block)
                check_cancel(self.cancel)
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return "saved", destination

        self.start(write_export, caption="Saving the upscaled file…")

    def poll(self):
        try:
            while True:
                event, result = self.events.get_nowait()
                if event == "hardware":
                    self.hardware = result
                    self.hardware_text.set(result.summary())
                    continue
                if event == "progress":
                    if self.cancel.is_set():
                        continue
                    fraction, caption = result
                    if self.started:
                        self.started.advance(fraction)
                        self.started.finalized = caption.startswith(("Finalizing MP4", "Receiving upscale"))
                    self.status.set(caption)
                    continue
                self.busy = False
                if self.closing:
                    self.cache.cleanup()
                    self.root.destroy()
                    return
                self.update_settings()
                if event == "result":
                    action, *parts = result
                    if action == "quote":
                        client, quote, size = parts
                        low, high = quote[1]
                        cost = str(low) if low == high else f"{low}–{high}"
                        proceed = not self.cancel.is_set() and messagebox.askyesno(
                            "Topaz Cloud", f"Estimated cost: {cost} Topaz API credits.\n\n"
                            "Upload this video to Topaz and start the render?", parent=self.root)
                        if proceed:
                            self.render(size, client, quote)
                        else:
                            self.reset_meter()
                            self.status.set("Cloud render skipped")
                        continue
                    self.progress["value"] = 1
                    self.percent_text.set("100%")
                    if self.started:
                        self.timeline_text.set(self.started.line("Completed"))
                    if action == "preview":
                        self.images, caption = parts
                        self.draw(0)
                        self.draw(1)
                        self.status.set(caption)
                    elif action == "render":
                        self.clear_result()
                        self.result, self.result_settings, thumbs, device = parts
                        self.images = thumbs or [self.images[0], None]
                        self.draw(0)
                        self.draw(1)
                        width, height = self.result_settings[1]
                        self.status.set(f"{width:,} × {height:,} ready  ·  {device}")
                        self.update_settings()
                    else:
                        self.last_saved = parts[0]
                        self.status.set(f"Saved {parts[0].name}")
                        self.update_settings()
                else:
                    self.progress["value"] = 0
                    self.percent_text.set("")
                    self.status.set("Cancelled" if event == "cancelled" else "Processing failed")
                    if self.started:
                        self.timeline_text.set(self.started.line(self.status.get()))
                    if event == "error":
                        if self.backend.get() == CLOUD and ("HTTP 401" in result or "HTTP 403" in result):
                            self.api_key = ""
                        messagebox.showerror("FrameLift", result, parent=self.root)
        except Empty:
            pass
        self.refresh_meter()
        self.root.after(75, self.poll)

    def close(self):
        if self.busy:
            self.closing = True
            self.stop()
        else:
            self.cache.cleanup()
            self.root.destroy()

    def stop(self):
        if self.busy and not self.cancel.is_set():
            self.status.set("Cancelling before closing…" if self.closing else "Cancelling…")
            self.cancel.set()
            self.cancel_button.configure(state="disabled")


if __name__ == "__main__":
    try:
        root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    except RuntimeError:
        failed_root = tk._default_root
        if failed_root is not None:
            failed_root.destroy()
        root = tk.Tk()
    FrameLift(root)
    root.mainloop()
