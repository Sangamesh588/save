import os
import sys

# Add the project root (parent of api/) to Python path so we can import app.py and downloader.py
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Set Vercel environment flag before importing app
os.environ["VERCEL"] = "1"

from app import app

# Vercel looks for an `app` variable that is a WSGI application
# The variable name MUST be `app` for @vercel/python to detect it

if __name__ == "__main__":
    app.run()
