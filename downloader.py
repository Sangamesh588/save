import os
import re
import time
import uuid
import shutil
import logging
import threading
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, Tuple
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("downloader")

# Serverless & Read-only Filesystem compatibility (Vercel / AWS Lambda / Containers)
# On Vercel, /var/task is read-only, only /tmp is writable
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or not os.access(os.path.dirname(os.path.abspath(__file__)), os.W_OK):
    DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "save_downloads")
else:
    DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

try:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
except Exception as e:
    logger.warning(f"Could not create primary DOWNLOAD_DIR: {e}. Falling back to system temp.")
    DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "save_downloads")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Concurrency & Traffic Control: ThreadPool for heavy FFmpeg/download workers
MAX_CONCURRENT_DOWNLOADS = 8
DOWNLOAD_POOL = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS, thread_name_prefix="DownloadWorker")

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()

# In-Memory Cache for Media Metadata (URL -> (timestamp, data))
INFO_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
INFO_CACHE_LOCK = threading.Lock()
INFO_CACHE_TTL = 900  # 15 minutes

# Safe FFmpeg detection (avoids read-only unpacking crashes on Vercel)
FFMPEG_PATH = None
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception as e:
    logger.warning(f"imageio_ffmpeg lookup failed ({e}), checking system PATH...")
    FFMPEG_PATH = shutil.which("ffmpeg")


def cleanup_old_jobs(max_age_seconds: int = 1800):
    """Background worker to clean up finished or stalled jobs and RAM caches."""
    while True:
        try:
            time.sleep(180)
            now = time.time()
            to_delete = []

            # Clean expired jobs
            with JOBS_LOCK:
                for job_id, job in list(JOBS.items()):
                    if now - job.get("created_at", now) > max_age_seconds:
                        to_delete.append(job_id)

            for job_id in to_delete:
                with JOBS_LOCK:
                    JOBS.pop(job_id, None)
                job_folder = os.path.join(DOWNLOAD_DIR, job_id)
                if os.path.exists(job_folder):
                    shutil.rmtree(job_folder, ignore_errors=True)
                logger.info(f"Cleaned up expired job: {job_id}")

            # Clean expired metadata cache
            with INFO_CACHE_LOCK:
                expired_urls = [
                    url for url, (ts, _) in INFO_CACHE.items()
                    if now - ts > INFO_CACHE_TTL
                ]
                for url in expired_urls:
                    INFO_CACHE.pop(url, None)

        except Exception as e:
            logger.error(f"Error in cleanup thread: {e}")


# Only start background infinite loop if not in Serverless (Vercel freezes background loops)
if not os.environ.get("VERCEL") and not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    cleanup_thread = threading.Thread(target=cleanup_old_jobs, daemon=True)
    cleanup_thread.start()


def check_disk_space_ok(min_free_bytes: int = 500 * 1024 * 1024) -> bool:
    """Returns False if available server disk space is critically low."""
    try:
        usage = shutil.disk_usage(DOWNLOAD_DIR)
        return usage.free >= min_free_bytes
    except Exception:
        return True


def get_base_ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    }
    if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
        opts["ffmpeg_location"] = FFMPEG_PATH
    return opts


def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "instagram.com" in url_lower:
        return "instagram"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower:
        return "facebook"
    elif "tiktok.com" in url_lower:
        return "tiktok"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    elif "soundcloud.com" in url_lower:
        return "soundcloud"
    elif "reddit.com" in url_lower:
        return "reddit"
    elif "pinterest.com" in url_lower or "pin.it" in url_lower:
        return "pinterest"
    elif "vimeo.com" in url_lower:
        return "vimeo"
    return "generic"


def get_youtube_embed_id(url: str) -> Optional[str]:
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
        r"shorts\/([0-9A-Za-z_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def format_bytes(size: Optional[int]) -> str:
    if not size or size <= 0:
        return "Auto"
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "Unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def extract_media_info(url: str) -> Dict[str, Any]:
    """Extracts platform, title, duration, thumbnail, quality options, and subtitles with high-speed memory caching."""
    now = time.time()
    with INFO_CACHE_LOCK:
        if url in INFO_CACHE:
            ts, cached_data = INFO_CACHE[url]
            if now - ts < INFO_CACHE_TTL:
                logger.info("Serving media info from memory cache.")
                return cached_data

    opts = get_base_ydl_opts()
    opts["extract_flat"] = False

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("Could not retrieve media details from this link.")

        if "entries" in info and info["entries"]:
            info = info["entries"][0]

    title = info.get("title") or "Media Download"
    duration = info.get("duration")
    thumbnail = info.get("thumbnail") or ""
    uploader = info.get("uploader") or info.get("channel") or info.get("creator") or "Unknown"
    platform = detect_platform(url)
    yt_id = get_youtube_embed_id(url) if platform == "youtube" else None

    # Get highest quality thumbnail
    thumbnails = info.get("thumbnails") or []
    best_thumbnail = thumbnail
    if yt_id:
        best_thumbnail = f"https://i.ytimg.com/vi/{yt_id}/maxresdefault.jpg"
    elif thumbnails:
        valid_thumbs = [t.get("url") for t in thumbnails if t.get("url")]
        if valid_thumbs:
            best_thumbnail = valid_thumbs[-1]

    # Process formats
    formats = info.get("formats") or []
    video_qualities = {}

    target_resolutions = [
        (2160, "4K (2160p)"),
        (1440, "2K (1440p)"),
        (1080, "Full HD (1080p)"),
        (720, "HD (720p)"),
        (480, "Standard (480p)"),
        (360, "Low (360p)"),
    ]

    has_any_video = False
    for f in formats:
        vcodec = f.get("vcodec", "none")
        height = f.get("height")
        if vcodec != "none" and height:
            has_any_video = True
            for target_h, label in target_resolutions:
                if height >= target_h * 0.9 and height <= target_h * 1.15:
                    if target_h not in video_qualities:
                        filesize = f.get("filesize") or f.get("filesize_approx")
                        video_qualities[target_h] = {
                            "height": target_h,
                            "label": label,
                            "ext": "mp4",
                            "filesize": format_bytes(filesize),
                            "format_id": f.get("format_id"),
                        }

    sorted_video_options = []
    sorted_video_options.append({
        "height": 0,
        "label": "Best Quality (Max)",
        "ext": "mp4",
        "filesize": "Auto",
        "format_id": "bestvideo+bestaudio/best",
        "recommended": True,
    })

    for target_h, _ in target_resolutions:
        if target_h in video_qualities:
            sorted_video_options.append(video_qualities[target_h])

    audio_options = [
        {"format": "mp3", "quality": "320", "label": "MP3 - 320 kbps (High Fidelity + Album Art)", "recommended": True},
        {"format": "mp3", "quality": "256", "label": "MP3 - 256 kbps (High Quality + Album Art)"},
        {"format": "mp3", "quality": "192", "label": "MP3 - 192 kbps (Standard + Album Art)"},
        {"format": "mp3", "quality": "128", "label": "MP3 - 128 kbps (Compact)"},
        {"format": "m4a", "quality": "best", "label": "M4A / AAC (Apple Native Audio)"},
        {"format": "wav", "quality": "lossless", "label": "WAV (Uncompressed Audio)"},
    ]

    subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}
    has_subtitles = bool(subs or auto_subs)

    result_data = {
        "title": title,
        "thumbnail": thumbnail,
        "best_thumbnail": best_thumbnail,
        "uploader": uploader,
        "duration": format_duration(duration),
        "duration_seconds": duration or 0,
        "platform": platform,
        "webpage_url": info.get("webpage_url") or url,
        "youtube_id": yt_id,
        "video_options": sorted_video_options,
        "audio_options": audio_options,
        "has_video": has_any_video or len(formats) > 0,
        "has_subtitles": has_subtitles,
    }

    # Save to memory cache
    with INFO_CACHE_LOCK:
        INFO_CACHE[url] = (now, result_data)

    return result_data


def apply_ffmpeg_trim(input_file: str, start_time: str, end_time: str) -> str:
    """Uses FFmpeg to cut an exact snippet from start_time to end_time."""
    if not FFMPEG_PATH:
        return input_file

    dir_name = os.path.dirname(input_file)
    base_name, ext = os.path.splitext(os.path.basename(input_file))
    clean_start = start_time.replace(":", "_")
    clean_end = end_time.replace(":", "_") if end_time else "end"
    output_file = os.path.join(dir_name, f"{base_name} [Clip {clean_start}-{clean_end}]{ext}")

    cmd = [FFMPEG_PATH, "-y", "-ss", start_time]
    if end_time:
        cmd.extend(["-to", end_time])
    cmd.extend(["-i", input_file, "-c", "copy", output_file])

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        cmd_transcode = [FFMPEG_PATH, "-y", "-ss", start_time]
        if end_time:
            cmd_transcode.extend(["-to", end_time])
        cmd_transcode.extend(["-i", input_file, "-c:v", "libx264", "-c:a", "aac", output_file])
        subprocess.run(cmd_transcode, check=True)

    return output_file


def download_media_job(job_id: str, url: str, media_type: str, quality: str, audio_format: str, start_time: Optional[str] = None, end_time: Optional[str] = None):
    """Executes media download, embedding ID3 metadata/album art for audio, and applying trimming if requested."""
    job_folder = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_folder, exist_ok=True)

    with JOBS_LOCK:
        JOBS[job_id]["status"] = "downloading"
        JOBS[job_id]["progress"] = 0
        JOBS[job_id]["speed"] = ""
        JOBS[job_id]["eta"] = ""

    def progress_hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            percent = int((downloaded / total * 100)) if total > 0 else 50
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()

            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["progress"] = min(percent, 88)
                    JOBS[job_id]["speed"] = speed
                    JOBS[job_id]["eta"] = eta
                    JOBS[job_id]["status_text"] = f"Downloading stream ({percent}%)..."

        elif d.get("status") == "finished":
            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["status"] = "processing"
                    JOBS[job_id]["progress"] = 92
                    JOBS[job_id]["status_text"] = "Encoding & verifying media with FFmpeg..."

    out_template = os.path.join(job_folder, "%(title).80s [%(id)s].%(ext)s")
    opts = get_base_ydl_opts()
    opts["outtmpl"] = out_template
    opts["progress_hooks"] = [progress_hook]

    try:
        if media_type == "audio":
            codec = audio_format.lower()
            if codec not in ["mp3", "m4a", "wav", "flac", "aac", "opus"]:
                codec = "mp3"

            opts["format"] = "bestaudio/best"
            postprocessors = []

            if FFMPEG_PATH:
                opts["writethumbnail"] = True
                postprocessors.append({
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": codec,
                })
                postprocessors.append({
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                })
                if codec == "mp3":
                    bitrate = quality if quality in ["320", "256", "192", "128"] else "320"
                    postprocessors[0]["preferredquality"] = bitrate
                    postprocessors.append({
                        "key": "EmbedThumbnail",
                        "already_have_thumbnail": False,
                    })

            if postprocessors:
                opts["postprocessors"] = postprocessors

        else:
            if quality and quality != "0" and quality.isdigit():
                h = int(quality)
                opts["format"] = (
                    f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                    f"bestvideo[height<={h}]+bestaudio/"
                    f"best[height<={h}]/best"
                )
            else:
                opts["format"] = (
                    "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                    "bestvideo+bestaudio/"
                    "best"
                )

            if FFMPEG_PATH:
                opts["merge_output_format"] = "mp4"
                opts["postprocessor_args"] = {
                    "merger": ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
                }

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
            files = [
                f for f in os.listdir(job_folder)
                if not f.endswith(".part") and not f.endswith(".ytdl") and not f.endswith(".jpg") and not f.endswith(".webp") and not f.endswith(".png")
            ]
            if not files:
                raise RuntimeError("Download completed but media file was not found.")

            target_file = files[0]
            full_path = os.path.join(job_folder, target_file)

            if start_time and start_time.strip() and FFMPEG_PATH:
                with JOBS_LOCK:
                    if job_id in JOBS:
                        JOBS[job_id]["status_text"] = "Trimming clip precisely with FFmpeg..."
                        JOBS[job_id]["progress"] = 96

                trimmed_path = apply_ffmpeg_trim(full_path, start_time.strip(), (end_time or "").strip())
                if os.path.exists(trimmed_path):
                    full_path = trimmed_path
                    target_file = os.path.basename(trimmed_path)

            file_size = os.path.getsize(full_path)

            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["status"] = "ready"
                    JOBS[job_id]["progress"] = 100
                    JOBS[job_id]["status_text"] = "Ready! You can watch or save it now."
                    JOBS[job_id]["filename"] = target_file
                    JOBS[job_id]["filepath"] = full_path
                    JOBS[job_id]["filesize_formatted"] = format_bytes(file_size)
                    JOBS[job_id]["media_type"] = media_type

    except Exception as e:
        logger.error(f"Download failed for job {job_id}: {e}", exc_info=True)
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = str(e)


def start_download_job(
    url: str,
    media_type: str = "video",
    quality: str = "0",
    audio_format: str = "mp3",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
) -> str:
    if not check_disk_space_ok():
        raise RuntimeError("Server storage is temporarily full. Please wait a few minutes while disk cleanup runs.")

    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "url": url,
            "media_type": media_type,
            "quality": quality,
            "audio_format": audio_format,
            "start_time": start_time,
            "end_time": end_time,
            "status": "queued",
            "progress": 0,
            "status_text": "Queued in download pool...",
            "created_at": time.time(),
        }

    # If in Serverless mode (Vercel), run synchronously or in pool
    DOWNLOAD_POOL.submit(
        download_media_job,
        job_id, url, media_type, quality, audio_format, start_time, end_time
    )
    return job_id


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


def download_subtitles_content(url: str, as_plain_text: bool = False) -> Tuple[str, str]:
    """Downloads subtitles and converts to either clean .srt or plain .txt transcript reliably."""
    temp_dir = os.path.join(DOWNLOAD_DIR, f"subs_{uuid.uuid4().hex[:8]}")
    os.makedirs(temp_dir, exist_ok=True)
    out_template = os.path.join(temp_dir, "%(title).60s.%(ext)s")

    probe_opts = get_base_ydl_opts()
    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        subs = info.get("subtitles") or {}
        auto_subs = info.get("automatic_captions") or {}
        available_langs = list(subs.keys()) + list(auto_subs.keys())

    if not available_langs:
        raise ValueError("No subtitles or captions are available for this specific video.")

    target_lang = "en"
    if "en" not in available_langs:
        for k in available_langs:
            if k.startswith("en"):
                target_lang = k
                break
        else:
            target_lang = available_langs[0]

    opts = get_base_ydl_opts()
    opts["outtmpl"] = out_template
    opts["skip_download"] = True
    opts["writesubtitles"] = True
    opts["writeautomaticsub"] = True
    opts["subtitleslangs"] = [target_lang]
    opts["subtitlesformat"] = "srt/best"
    opts["ignoreerrors"] = True
    if FFMPEG_PATH:
        opts["postprocessors"] = [{"key": "FFmpegSubtitlesConvertor", "format": "srt"}]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)

        sub_files = [f for f in os.listdir(temp_dir) if f.endswith((".srt", ".vtt", ".txt"))]
        if not sub_files:
            raise ValueError(f"Could not download subtitles for language '{target_lang}'.")

        sub_path = os.path.join(temp_dir, sub_files[0])
        with open(sub_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        base_title = os.path.splitext(sub_files[0])[0]

        if as_plain_text:
            clean_text = re.sub(r"\d+\r?\n\d{2}:\d{2}:\d{2}[,\.]\d{3} --> \d{2}:\d{2}:\d{2}[,\.]\d{3}\r?\n", "", content)
            clean_text = re.sub(r"WEBVTT\r?\n", "", clean_text)
            clean_text = re.sub(r"<\/?c[^>]*>", "", clean_text)
            clean_text = re.sub(r"\n{2,}", "\n", clean_text).strip()
            return f"{base_title}.txt", clean_text
        else:
            return f"{base_title}.srt", content

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
