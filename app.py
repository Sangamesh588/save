import os
import io
import mimetypes
import logging
import requests
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from downloader import (
    extract_media_info,
    start_download_job,
    get_job_status,
    download_subtitles_content,
    FFMPEG_PATH,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("app")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
CORS(app)

# ============================================================
# Traffic Control & Rate Limiting (Protects from abuse & DDoS)
# ============================================================
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["120 per minute"],
    storage_uri="memory://",
)


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "success": False,
        "error": "Rate limit reached. Please wait a moment before sending more requests."
    }), 429


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    return send_file(os.path.join(app.static_folder, "manifest.json"), mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    response = send_file(os.path.join(app.static_folder, "sw.js"), mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/api/platforms", methods=["GET"])
def platforms():
    return jsonify({
        "platforms": [
            {"id": "youtube", "name": "YouTube"},
            {"id": "instagram", "name": "Instagram"},
            {"id": "facebook", "name": "Facebook"},
            {"id": "tiktok", "name": "TikTok"},
            {"id": "twitter", "name": "X / Twitter"},
            {"id": "soundcloud", "name": "SoundCloud"},
            {"id": "reddit", "name": "Reddit"},
            {"id": "pinterest", "name": "Pinterest"}
        ]
    })


@app.route("/api/info", methods=["POST"])
@limiter.limit("30 per minute")
def fetch_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"success": False, "error": "Please enter a valid link."}), 400

    try:
        info = extract_media_info(url)
        return jsonify({"success": True, "data": info})
    except Exception as e:
        logger.error(f"Error fetching info for {url}: {e}", exc_info=True)
        err_msg = str(e)
        if "Unsupported URL" in err_msg:
            err_msg = "This URL or platform is not supported, or the link is private."
        elif "Video unavailable" in err_msg:
            err_msg = "The video is unavailable, private, or age-restricted."
        return jsonify({"success": False, "error": err_msg}), 400


@app.route("/api/download", methods=["POST"])
@limiter.limit("10 per minute")
def start_download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    media_type = data.get("type", "video")
    quality = str(data.get("quality", "0"))
    audio_format = data.get("audio_format", "mp3")
    start_time = data.get("start_time")
    end_time = data.get("end_time")

    if not url:
        return jsonify({"success": False, "error": "URL is required"}), 400

    try:
        job_id = start_download_job(
            url=url,
            media_type=media_type,
            quality=quality,
            audio_format=audio_format,
            start_time=start_time,
            end_time=end_time
        )
        return jsonify({"success": True, "job_id": job_id})
    except Exception as e:
        logger.error(f"Download trigger failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/progress/<job_id>", methods=["GET"])
def check_progress(job_id):
    job = get_job_status(job_id)
    if not job:
        return jsonify({"success": False, "error": "Download job not found or expired"}), 404

    return jsonify({"success": True, "job": job})


@app.route("/api/stream/<job_id>", methods=["GET"])
def stream_media(job_id):
    """Allows in-browser video and audio playback with seeking support."""
    job = get_job_status(job_id)
    if not job or job.get("status") != "ready":
        return jsonify({"error": "Media is not ready for playback"}), 404

    filepath = job.get("filepath")
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "Media file not found on disk"}), 404

    mimetype, _ = mimetypes.guess_type(filepath)
    if not mimetype:
        mimetype = "video/mp4" if job.get("media_type") == "video" else "audio/mpeg"

    return send_file(
        filepath,
        mimetype=mimetype,
        as_attachment=False,
        conditional=True
    )


@app.route("/api/file/<job_id>", methods=["GET"])
def download_file(job_id):
    """Sends the media file as an attachment to save directly onto the user's computer."""
    job = get_job_status(job_id)
    if not job or job.get("status") != "ready":
        return jsonify({"error": "File is not ready or has expired"}), 404

    filepath = job.get("filepath")
    filename = job.get("filename", "download.mp4")

    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    mimetype, _ = mimetypes.guess_type(filepath)
    if not mimetype:
        mimetype = "video/mp4" if job.get("media_type") == "video" else "audio/mpeg"

    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
        mimetype=mimetype
    )


@app.route("/api/thumbnail", methods=["GET"])
@limiter.limit("20 per minute")
def download_thumbnail():
    """Proxies and downloads the highest resolution thumbnail image."""
    thumb_url = request.args.get("url")
    title = request.args.get("title", "thumbnail")
    if not thumb_url:
        return jsonify({"error": "Thumbnail URL is required"}), 400

    try:
        r = requests.get(thumb_url, timeout=10)
        if r.status_code != 200:
            return jsonify({"error": "Could not download thumbnail"}), 400

        clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()[:50]
        return send_file(
            io.BytesIO(r.content),
            mimetype="image/jpeg",
            as_attachment=True,
            download_name=f"{clean_title}_HD_Thumbnail.jpg"
        )
    except Exception as e:
        logger.error(f"Thumbnail download failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/subtitles", methods=["POST"])
@limiter.limit("15 per minute")
def get_subtitles():
    """Downloads subtitles either as .srt or clean plain text (.txt)."""
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    format_type = data.get("format", "srt")

    if not url:
        return jsonify({"success": False, "error": "URL is required"}), 400

    try:
        as_txt = (format_type == "txt")
        filename, content = download_subtitles_content(url, as_plain_text=as_txt)
        return send_file(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/plain; charset=utf-8",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Subtitle extraction failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "online",
        "ffmpeg_available": bool(FFMPEG_PATH and os.path.exists(FFMPEG_PATH)),
    })


if __name__ == "__main__":
    import sys
    is_dev = "--dev" in sys.argv
    port = int(os.environ.get("PORT", 5000))

    if is_dev:
        print(f"Starting in Development mode on port {port}...")
        app.run(host="0.0.0.0", port=port, debug=True)
    else:
        # Production WSGI server: Handles 100-200 concurrent connections with thread pooling
        try:
            from waitress import serve
            print(f"============================================================")
            print(f" MediaDownloader High-Concurrency Production Server Online")
            print(f" Serving on http://localhost:{port} (16 Workers, 200 Max Conn)")
            print(f" Rate Limiting & Traffic Control: ACTIVE")
            print(f"============================================================")
            serve(app, host="0.0.0.0", port=port, threads=16, connection_limit=200, channel_timeout=120)
        except ImportError:
            print(f"Waitress not found, falling back to standard server on port {port}...")
            app.run(host="0.0.0.0", port=port, threaded=True)
