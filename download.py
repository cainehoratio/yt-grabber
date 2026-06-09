import sys
import os
import shutil
import yt_dlp

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def find_ffmpeg_dir():
    """Return the directory of an ffmpeg on PATH, or None to let yt-dlp search."""
    on_path = shutil.which("ffmpeg")
    return os.path.dirname(on_path) if on_path else None


def download(url: str, fmt: str) -> None:
    if fmt == "mp3":
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
    elif fmt == "mp4":
        opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
        }
    else:
        print(f"Unknown format '{fmt}'. Use mp3 or mp4.")
        sys.exit(1)

    ffmpeg_dir = find_ffmpeg_dir()
    if ffmpeg_dir:
        opts["ffmpeg_location"] = ffmpeg_dir

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "video")
        print(f"\nDone! Saved: downloads/{title}.{fmt}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python download.py <youtube_url> [mp3|mp4]")
        print("       Format defaults to mp4 if not specified.")
        sys.exit(0)

    url = sys.argv[1]
    fmt = sys.argv[2].lower() if len(sys.argv) >= 3 else "mp4"
    download(url, fmt)


if __name__ == "__main__":
    main()
