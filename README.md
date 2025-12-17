# Speed Reader Book Service

Flask service that ingests PDF or EPUB uploads and returns JSON distinguishing headings and paragraphs, trimming common headers/footers.

## Setup

```bash
pip install -r requirements.txt
python app.py  # runs on http://localhost:5000
```

## API

- `POST /extract` with form-data file field named `file` containing a `.pdf` or `.epub`.

Example:

```bash
curl -X POST http://localhost:5000/extract ^
  -F "file=@/path/to/book.pdf" | python -m json.tool
```

## Production / Gunicorn

- This app exposes a WSGI `app` object; run it with Gunicorn (Linux/macOS/WSL):

  ```bash
  gunicorn -c gunicorn.conf.py app:app
  ```

- Configurable environment variables:
  - `WEB_CONCURRENCY` (workers, defaults to `cpu_count*2+1`)
  - `WEB_TIMEOUT` (request timeout, default `60`)
  - `WEB_GRACEFUL_TIMEOUT` (default `30`)
  - `WEB_KEEPALIVE` (default `5`)
  - `PORT` (bind port, default `8000`)
  - `MAX_CONTENT_LENGTH` (bytes; request body limit, default `20*1024*1024`)

- For local development on Windows, keep using `python app.py`. Gunicorn is not supported natively on Windows shells; use WSL if you want to mirror production.

## Railway

- Deploy the repo and set the start command to:

  ```bash
  gunicorn -c gunicorn.conf.py app:app
  ```

- Railway provides `PORT`; keep it unset locally so Gunicorn binds to 8000.
- Optional env vars: `WEB_CONCURRENCY` (e.g., 2–4), `WEB_TIMEOUT`, `WEB_GRACEFUL_TIMEOUT`, `WEB_KEEPALIVE`, `MAX_CONTENT_LENGTH`.
- Health check: `POST /extract` with `form-data` field `file` containing a `.pdf` or `.epub`.

## Local (Windows)

- Install deps: `python -m venv .venv && .venv\\Scripts\\activate && pip install -r requirements.txt`
- Run the dev server: `python app.py` (auto-reloads if `debug=True`).
- To mirror production locally, run Gunicorn in WSL or a Linux shell: `gunicorn -c gunicorn.conf.py app:app`.

## Heuristics

- PDFs (PyMuPDF): drops top/bottom ~7% of each page to avoid headers/footers; uses span font size to tag headings (larger than median body size, short lines only) and merges nearby lines into paragraphs using vertical gaps.
- EPUBs: walks document items, treating `h1`-`h6` elements as headings and `p` elements as paragraphs.
