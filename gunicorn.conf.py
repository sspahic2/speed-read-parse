"""Gunicorn configuration defaults suitable for container or VM deployment."""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Keep worker count low to avoid per-process memory overhead from heavy deps (PyMuPDF, lxml).
# Override with WEB_CONCURRENCY if you need more throughput.
workers = int(os.getenv("WEB_CONCURRENCY", "1"))

# Use a few threads instead of more processes to stay within small RAM plans.
worker_class = "gthread"
threads = int(os.getenv("WEB_THREADS", "2"))

# Periodically recycle workers to shed any leaks.
max_requests = int(os.getenv("WEB_MAX_REQUESTS", "200"))
max_requests_jitter = int(os.getenv("WEB_MAX_REQUESTS_JITTER", "50"))

# Tune timeouts/keepalive via env vars if needed.
timeout = int(os.getenv("WEB_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("WEB_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("WEB_KEEPALIVE", "5"))

accesslog = "-"
errorlog = "-"
