import os
import sys

# Add project root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Set Vercel environment flag before importing app
os.environ["VERCEL"] = "1"

from app import app

class VercelPathCorrectionMiddleware:
    """
    On Vercel, rewrites to /api/index.py set PATH_INFO to '/api/index.py'.
    This WSGI middleware restores the original requested path from Vercel's
    request headers so Flask can route /, /static/*, /api/*, etc. properly.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        orig_path = (
            environ.get("HTTP_X_MATCHED_PATH")
            or environ.get("HTTP_X_FORWARDED_PATH")
            or environ.get("HTTP_X_FORWARDED_URI")
            or environ.get("RAW_URI")
            or environ.get("REQUEST_URI")
        )
        if orig_path:
            clean_path = orig_path.split("?")[0]
            if clean_path and not clean_path.startswith("/api/index.py"):
                environ["PATH_INFO"] = clean_path

        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathCorrectionMiddleware(app.wsgi_app)

if __name__ == "__main__":
    app.run()
