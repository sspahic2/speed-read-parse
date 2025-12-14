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

## Heuristics

- PDFs (PyMuPDF): drops top/bottom ~7% of each page to avoid headers/footers; uses span font size to tag headings (larger than median body size, short lines only) and merges nearby lines into paragraphs using vertical gaps.
- EPUBs: walks document items, treating `h1`-`h6` elements as headings and `p` elements as paragraphs.
