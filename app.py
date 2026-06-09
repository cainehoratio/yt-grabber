import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import shutil
import os
import yt_dlp

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _find_ffmpeg():
    """Locate ffmpeg: prefer one on PATH, else fall back to a local winget install.
    Returns (dir, exe) — dir may be None if ffmpeg is on PATH (yt-dlp finds it itself)."""
    on_path = shutil.which("ffmpeg")
    if on_path:
        return os.path.dirname(on_path), on_path
    # Fallback: typical Gyan.FFmpeg winget location for the current user
    guess = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
    )
    if os.path.isdir(guess):
        for root, _dirs, files in os.walk(guess):
            if "ffmpeg.exe" in files:
                return root, os.path.join(root, "ffmpeg.exe")
    return None, "ffmpeg"  # last resort: hope it's resolvable


FFMPEG_DIR, FFMPEG_EXE = _find_ffmpeg()


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_seconds(s: int) -> str:
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def parse_time(t: str) -> float | None:
    t = t.strip()
    if not t:
        return None
    parts = t.split(":")
    try:
        parts = [float(p) for p in parts]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except ValueError:
        pass
    raise ValueError(f"Invalid time '{t}' — use mm:ss or hh:mm:ss")


def fetch_duration(url: str) -> int | None:
    opts = {"quiet": True, "skip_download": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("duration")
    except Exception:
        return None


def trim_file(src: str, dst: str, start: float, end: float) -> None:
    """Trim src to [start, end] seconds and save as dst using stream copy (fast).
    -ss before -i uses input seeking so the clip starts on a keyframe — no frozen frames."""
    duration = end - start
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-ss", str(start),
        "-i", src,
        "-t", str(duration),
        "-c:v", "libx264",   # re-encode video for perfect sync
        "-c:a", "aac",       # re-encode audio for perfect sync
        "-preset", "fast",
        dst,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace"))


# ── Download worker ───────────────────────────────────────────────────────────

def download(url: str, fmt: str, start: float | None, end: float | None,
             on_progress, on_status, on_done, on_error):

    stream_index = [0]

    def progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("_speed_str", "").strip()
            pct = (downloaded / total * 100) if total else 0
            label = "Downloading audio..." if stream_index[0] > 0 else "Downloading video..."
            on_progress(pct, f"{label}  {speed}")
        elif d["status"] == "finished":
            stream_index[0] += 1

    def postprocessor_hook(d):
        if d["status"] == "started":
            pp = d.get("postprocessor", "")
            if "Merger" in pp:
                on_status("Merging video and audio...")
            elif "FFmpegExtractAudio" in pp:
                on_status("Converting to MP3...")

    if fmt == "mp3":
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
        }
    else:
        opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
        }

    if FFMPEG_DIR:
        opts["ffmpeg_location"] = FFMPEG_DIR

    try:
        on_status("Fetching video info...")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
            ext = "mp3" if fmt == "mp3" else "mp4"
            full_path = os.path.join(OUTPUT_DIR, f"{title}.{ext}")

        # Trim with FFmpeg if a clip was requested
        if start is not None or end is not None:
            on_status("Trimming clip...")
            s = start if start is not None else 0
            e = end   if end   is not None else float("inf")
            trimmed_path = os.path.join(OUTPUT_DIR, f"{title}_clip.{ext}")
            trim_file(full_path, trimmed_path, s, e)
            os.replace(trimmed_path, full_path)

        on_done(title, ext)

    except Exception as exc:
        on_error(str(exc))


# ── GUI ───────────────────────────────────────────────────────────────────────

def _entry(parent, var, width=18):
    return tk.Entry(
        parent, textvariable=var, width=width,
        font=("Segoe UI", 11), bg="#1c1c1c", fg="#ffffff",
        insertbackground="#ffffff", relief="flat", bd=8,
    )


BG        = "#111111"
BG2       = "#1c1c1c"
BORDER    = "#2e2e2e"
FG        = "#ffffff"
FG_MUTED  = "#666666"
ACCENT    = "#c8f75e"   # lime green from metavoros.com


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YT Grabber")
        self.resizable(False, False)
        self.configure(bg=BG)
        icon = os.path.join(os.path.dirname(__file__), "icon.ico")
        if os.path.exists(icon):
            self.iconbitmap(icon)
        self._video_duration = None
        self._fetch_timer = None

        # Custom progress bar style
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Green.Horizontal.TProgressbar",
                        troughcolor=BG2, background=ACCENT,
                        bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)
        self._build_ui()

    def _label(self, parent, text, small=False, muted=False):
        return tk.Label(
            parent, text=text,
            font=("Segoe UI", 9 if small else 10),
            bg=parent.cget("bg") if isinstance(parent, tk.Frame) else BG,
            fg=FG_MUTED if (small or muted) else FG,
        )

    def _build_ui(self):
        # ── Header ───────────────────────────────────────────
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=28, pady=(24, 4))

        tk.Label(header, text="M", font=("Segoe UI", 15, "bold"),
                 bg=BG, fg=FG).pack(side="left")
        tk.Label(header, text="V", font=("Segoe UI", 15, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")

        tk.Label(self, text="YT Grabber",
                 font=("Segoe UI", 22, "bold"), bg=BG, fg=FG).pack(anchor="w", padx=28, pady=(0, 20))

        # ── URL ──────────────────────────────────────────────
        self._label(self, "PASTE YOUTUBE LINK", small=True).pack(anchor="w", padx=28)
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", self._on_url_change)

        url_frame = tk.Frame(self, bg=BG2, highlightbackground=BORDER,
                             highlightthickness=1)
        url_frame.pack(fill="x", padx=28, pady=(4, 16))
        tk.Entry(url_frame, textvariable=self.url_var, font=("Segoe UI", 11),
                 bg=BG2, fg=FG, insertbackground=FG, relief="flat",
                 bd=10).pack(fill="x", ipady=6)

        # ── Format ───────────────────────────────────────────
        self._label(self, "FORMAT", small=True).pack(anchor="w", padx=28)
        self.fmt_var = tk.StringVar(value="mp4")
        fmt_frame = tk.Frame(self, bg=BG)
        fmt_frame.pack(anchor="w", padx=24, pady=(4, 16))
        for label, val in [("MP4 (Video)", "mp4"), ("MP3 (Audio)", "mp3")]:
            tk.Radiobutton(
                fmt_frame, text=label, variable=self.fmt_var, value=val,
                font=("Segoe UI", 10), bg=BG, fg=FG,
                selectcolor=BG2, activebackground=BG, activeforeground=ACCENT,
            ).pack(side="left", padx=(0, 16))

        # ── Divider ───────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=28, pady=(0, 14))

        # ── Clip ─────────────────────────────────────────────
        self.clip_label_var = tk.StringVar(value="CLIP (OPTIONAL)")
        tk.Label(self, textvariable=self.clip_label_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", padx=28)

        time_frame = tk.Frame(self, bg=BG)
        time_frame.pack(anchor="w", padx=28, pady=(6, 4))

        for label_text, var_name in [("Start", "start_var"), ("End", "end_var")]:
            tk.Label(time_frame, text=label_text, font=("Segoe UI", 10),
                     bg=BG, fg=FG_MUTED).pack(side="left")
            var = tk.StringVar()
            setattr(self, var_name, var)
            f = tk.Frame(time_frame, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
            f.pack(side="left", padx=(6, 20))
            tk.Entry(f, textvariable=var, width=7, font=("Segoe UI", 11),
                     bg=BG2, fg=FG, insertbackground=FG, relief="flat", bd=6).pack(ipady=4)

        self._label(self, "mm:ss  or  hh:mm:ss", small=True).pack(anchor="w", padx=28)

        # ── Button ───────────────────────────────────────────
        self.btn = tk.Button(
            self, text="Download  →", command=self._start_download,
            font=("Segoe UI", 11, "bold"), bg=ACCENT, fg="#111111",
            activebackground="#b0e040", activeforeground="#111111",
            relief="flat", cursor="hand2", padx=24, pady=10, bd=0,
        )
        self.btn.pack(pady=16)

        # ── Progress ─────────────────────────────────────────
        self.progress = ttk.Progressbar(self, length=440, mode="determinate",
                                        style="Green.Horizontal.TProgressbar")
        self.progress.pack(padx=28, pady=(0, 6))

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self, textvariable=self.status_var, font=("Segoe UI", 9),
                 bg=BG, fg=FG_MUTED, wraplength=440).pack(padx=28, pady=(0, 24))

    # ── URL / duration ────────────────────────────────────────

    def _on_url_change(self, *_):
        url = self.url_var.get().strip()
        if self._fetch_timer:
            self.after_cancel(self._fetch_timer)
        if "youtube.com" in url or "youtu.be" in url:
            self.clip_label_var.set("FETCHING VIDEO LENGTH...")
            self._fetch_timer = self.after(800, lambda: self._load_duration(url))
        else:
            self._video_duration = None
            self.start_var.set("")
            self.end_var.set("")
            self.clip_label_var.set("CLIP (OPTIONAL)")

    def _load_duration(self, url):
        threading.Thread(target=self._fetch_and_set, args=(url,), daemon=True).start()

    def _fetch_and_set(self, url):
        duration = fetch_duration(url)
        if duration:
            self.after(0, lambda: self._set_timestamps(duration))
        else:
            self.after(0, lambda: self.clip_label_var.set("Clip — edit if you only want part of the video:"))

    def _set_timestamps(self, duration: int):
        self._video_duration = duration
        self.start_var.set("0:00")
        self.end_var.set(fmt_seconds(duration))
        self.clip_label_var.set("CLIP (OPTIONAL)")

    # ── Download ──────────────────────────────────────────────

    def _start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No link", "Please paste a YouTube link first.")
            return

        try:
            start = parse_time(self.start_var.get())
            end   = parse_time(self.end_var.get())
        except ValueError as e:
            messagebox.showerror("Invalid time", str(e))
            return

        if start is not None and end is not None and end <= start:
            messagebox.showerror("Invalid range", "End time must be after start time.")
            return

        # Full video — no trimming needed
        is_full = (
            (start is None or start == 0.0) and
            (end is None or (self._video_duration and abs(end - self._video_duration) < 2))
        )
        if is_full:
            start = None
            end = None

        self.btn.config(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("Starting...")

        threading.Thread(
            target=download,
            args=(url, self.fmt_var.get(), start, end,
                  self._on_progress, self._on_status, self._on_done, self._on_error),
            daemon=True,
        ).start()

    def _on_progress(self, pct, label):
        self.after(0, lambda p=pct, l=label: (
            setattr(self.progress, "__class__", self.progress.__class__) or
            self._update_bar(p, l)
        ))

    def _update_bar(self, pct, label):
        self.progress["value"] = pct
        self.status_var.set(label)

    def _on_status(self, msg):
        self.after(0, lambda m=msg: self.status_var.set(m))

    def _on_done(self, title, ext):
        self.after(0, lambda: self._finish(title, ext))

    def _finish(self, title, ext):
        self.progress["value"] = 100
        self.status_var.set(f"✓  Saved:  {title}.{ext}")
        self.btn.config(state="normal")
        self.url_var.set("")
        self._video_duration = None
        self.start_var.set("")
        self.end_var.set("")
        self.clip_label_var.set("CLIP (OPTIONAL)")

    def _on_error(self, msg):
        self.after(0, lambda: self._show_error(msg))

    def _show_error(self, msg):
        self.progress["value"] = 0
        self.status_var.set("Something went wrong.")
        self.btn.config(state="normal")
        messagebox.showerror("Download failed", msg)


if __name__ == "__main__":
    app = App()
    app.mainloop()
