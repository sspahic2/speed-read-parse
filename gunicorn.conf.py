"""Gunicorn configuration defaults suitable for container or VM deployment."""
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Allow overriding via WEB_CONCURRENCY; otherwise derive from CPU count.
workers = int(os.getenv("WEB_CONCURRENCY", max(1, multiprocessing.cpu_count() * 2 + 1)))

# Tune timeouts/keepalive via env vars if needed.
timeout = int(os.getenv("WEB_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("WEB_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("WEB_KEEPALIVE", "5"))

accesslog = "-"
errorlog = "-"
