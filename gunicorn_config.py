"""Gunicorn config for Render free tier (512MB RAM)."""
import os

bind = "0.0.0.0:" + os.environ.get("PORT", "8000")
timeout = 120
keepalive = 5

