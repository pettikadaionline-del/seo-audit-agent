"""Vercel entrypoint: Vercel detects the FastAPI `app` exported from index.py."""
from app.main import app  # noqa: F401
