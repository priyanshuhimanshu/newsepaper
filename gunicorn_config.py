"""Gunicorn config for Render free tier (512MB RAM)."""
import multiprocessing
import os

bind = "0.0.0.0:" + os.environ.get("PORT", "8000")
workers = 1
threads = 2
timeout = 120
keepalive = 5
max_requests = 200
max_requests_jitter = 20
preload_app = False
