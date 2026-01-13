import os
import statistics
import tempfile
import shutil
from collections import Counter
from typing import List, Dict, Any

from flask import Flask, jsonify, request
import fitz  # PyMuPDF
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from werkzeug.exceptions import RequestEntityTooLarge

app = Flask(__name__)

# Limit upload size to guard against DOS/oversized files. Default 20 MB, overridable via env.
def _parse_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


app.config["MAX_CONTENT_LENGTH"] = _parse_int_env(
    "MAX_CONTENT_LENGTH", 20 * 1024 * 1024
)


def _spill_to_tempfile(upload_stream, suffix: str) -> str:
    """Write the uploaded stream to a temp file to avoid holding big payloads in RAM."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as tmp:
            upload_stream.seek(0)
            shutil.copyfileobj(upload_stream, tmp, length=1024 * 1024)
    except Exception:
        os.remove(path)
        raise
    return path


def _apply_style(entry: Dict[str, Any], items: List[Dict[str, Any]]) -> None:
    """Populate style metadata on a block using buffered line details."""
    sizes = [item.get("size") for item in items if item.get("size") is not None]
    line_heights = [
        item.get("line_height") for item in items if item.get("line_height") is not None
    ]
    weights = [item.get("weight") for item in items if item.get("weight")]

    if sizes:
        entry["font_size"] = round(statistics.mean(sizes), 2)
    if line_heights:
        entry["line_height"] = round(statistics.mean(line_heights), 2)
    if weights:
        entry["font_weight"] = Counter(weights).most_common(1)[0][0]


def _flush_paragraph(
    buffer: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
    buffer_type: str | None,
    page_number: int | None = None,
) -> None:
    """Move the buffered paragraph lines into the result list."""
    if not buffer:
        return
    joined = " ".join(item["text"] for item in buffer).strip()
    if joined:
        entry = {"type": buffer_type or "paragraph", "text": joined}
        if page_number is not None:
            entry["page"] = page_number
        _apply_style(entry, buffer)
        blocks.append(entry)
    buffer.clear()


def extract_pdf(file_stream) -> List[Dict[str, Any]]:
    """Extract headings and paragraphs from a PDF using PyMuPDF (fitz)."""
    temp_path = _spill_to_tempfile(file_stream, ".pdf")
    blocks: List[Dict[str, Any]] = []

    try:
        with fitz.open(temp_path) as doc:
            # First pass: collect font sizes across the whole document to find dominant body size.
            all_sizes: List[float] = []
            for page in doc:
                text_dict = page.get_text("dict")
                for block in text_dict.get("blocks", []):
                    if block.get("type", 0) != 0:
                        continue
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        if not spans:
                            continue
                        sizes = [span.get("size") for span in spans if span.get("size")]
                        if not sizes:
                            continue
                        avg_size = statistics.mean(sizes)
                        all_sizes.append(avg_size)

            size_bins: Dict[float, List[float]] = {}
            for size in all_sizes:
                key = round(size * 2) / 2.0  # bin to nearest 0.5pt
                size_bins.setdefault(key, []).append(size)

            if size_bins:
                dominant_key = max(size_bins.items(), key=lambda kv: len(kv[1]))[0]
                body_size_global = statistics.mean(size_bins[dominant_key])
            else:
                dominant_key = None
                body_size_global = 10.0

            if all_sizes:
                total = len(all_sizes)
                dist = sorted(size_bins.items(), key=lambda kv: len(kv[1]), reverse=True)
                top_bins = ", ".join(
                    f"{k:.1f}pt={len(v)/total*100:.1f}%"
                    for k, v in dist[:5]
                )
                # print(
                #     f"[pdf body] lines={total} dominant={body_size_global:.2f}pt "
                #     f"(bin {dominant_key:.1f}pt), top bins: {top_bins}"
                # )

            for page in doc:
                page_number = page.number + 1  # 1-based for logging
                page_height = float(page.rect.height)

                text_dict = page.get_text("dict")
                lines_data = []

                for block in text_dict.get("blocks", []):
                    if block.get("type", 0) != 0:
                        continue  # skip images/others
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        if not spans:
                            continue

                        text = "".join(span.get("text", "") for span in spans).strip()
                        if not text:
                            continue

                        tops = [span["bbox"][1] for span in spans]
                        bottoms = [span["bbox"][3] for span in spans]
                        sizes = [span.get("size") for span in spans if span.get("size")]
                        if not sizes:
                            continue

                        fonts = [span.get("font") for span in spans if span.get("font")]
                        weight = "bold" if any(
                            (font and "bold" in font.lower()) for font in fonts
                        ) else "normal"

                        lines_data.append(
                            {
                                "text": text,
                                "top": min(tops),
                                "bottom": max(bottoms),
                                "size": statistics.mean(sizes),
                                "height": max(bottoms) - min(tops),
                                "line_height": max(bottoms) - min(tops),
                                "weight": weight,
                            }
                        )

                if not lines_data:
                    continue

                median_height = statistics.median([ln["height"] for ln in lines_data])
                sizes_sorted = sorted([ln["size"] for ln in lines_data])
                body_size = body_size_global
                p90 = sizes_sorted[int(0.9 * (len(sizes_sorted) - 1))] if sizes_sorted else body_size
                heading_threshold = max(body_size * 1.4, p90 + 1.0)
                gap_threshold = median_height * 1.2
                body_tolerance = 0.75

                def looks_like_heading(text: str, avg_size: float, base_size: float) -> bool:
                    """Generic heading guess: short, noticeably larger font, low punctuation."""
                    words = text.split()
                    word_count = len(words)
                    if not words or word_count > 12:
                        return False
                    if avg_size < heading_threshold or (avg_size - base_size) < 3.0:
                        return False
                    punct_count = sum(1 for ch in text if ch in ".,;:!?")
                    if punct_count / max(len(text), 1) > 0.08:
                        return False
                    uppercaseish = sum(1 for w in words if w[:1].isupper() or w[:1].isdigit())
                    if uppercaseish / word_count < 0.35:
                        return False
                    return True

                lines_data.sort(key=lambda ln: ln["top"])
                paragraph_buffer: List[Dict[str, Any]] = []
                buffer_type: str | None = None
                meta_prefixes = ("from:", "subject:", "date:", "to:")
                small_delta = 1.0
                prev_bottom = None

                for line in lines_data:
                    text = line["text"]
                    avg_size = line["size"]

                    lower = text.lower().strip()
                    if lower.startswith(meta_prefixes):
                        _flush_paragraph(paragraph_buffer, blocks, buffer_type, page_number)
                        entry = {"type": "special_paragraph", "text": text, "page": page_number}
                        _apply_style(entry, [line])
                        blocks.append(entry)
                        prev_bottom = line["bottom"]
                        buffer_type = None
                        continue

                    is_heading = looks_like_heading(text, avg_size, body_size)

                    if is_heading:
                        _flush_paragraph(paragraph_buffer, blocks, buffer_type, page_number)
                        entry = {"type": "heading", "text": text, "page": page_number}
                        _apply_style(entry, [line])
                        blocks.append(entry)
                        buffer_type = None
                    else:
                        if prev_bottom is not None and (line["top"] - prev_bottom) > gap_threshold:
                            _flush_paragraph(paragraph_buffer, blocks, buffer_type, page_number)
                            buffer_type = None

                        line_type = (
                            "special_paragraph" if avg_size < (body_size - small_delta) else "paragraph"
                        )
                        if buffer_type is None:
                            buffer_type = line_type
                        elif line_type != buffer_type:
                            _flush_paragraph(paragraph_buffer, blocks, buffer_type, page_number)
                            buffer_type = line_type

                        paragraph_buffer.append(
                            {
                                "text": text,
                                "size": avg_size,
                                "font": line.get("font"),
                                "line_height": line.get("height"),
                                "weight": line.get("weight"),
                            }
                        )

                    prev_bottom = line["bottom"]

                _flush_paragraph(paragraph_buffer, blocks, buffer_type, page_number)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    return blocks


def extract_epub(file_stream) -> List[Dict[str, Any]]:
    """Extract headings and paragraphs from an EPUB file-like object."""
    blocks: List[Dict[str, Any]] = []

    temp_path = _spill_to_tempfile(file_stream, ".epub")
    try:
        book = epub.read_epub(temp_path)

        for page_number, item in enumerate(book.get_items_of_type(ITEM_DOCUMENT), start=1):
            soup = BeautifulSoup(item.get_content(), "lxml")
            for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"]):
                text = element.get_text(" ", strip=True)
                if not text:
                    continue
                block_type = "heading" if element.name.startswith("h") else "paragraph"
                blocks.append(
                    {
                        "type": block_type,
                        "text": text,
                        "page": page_number,
                        "font_size": None,
                        "font_weight": None,
                        "line_height": None,
                    }
                )
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    return blocks


@app.route("/extract", methods=["POST"])
def extract():
    """Upload endpoint. Returns JSON with headings and paragraphs."""
    max_len = app.config.get("MAX_CONTENT_LENGTH")
    if request.content_length is not None and max_len and request.content_length > max_len:
        return (
            jsonify(
                {
                    "error": "file too large",
                    "limit_bytes": max_len,
                }
            ),
            413,
        )

    if "file" not in request.files:
        return jsonify({"error": "file is required"}), 400

    uploaded_file = request.files["file"]
    filename = uploaded_file.filename or ""
    if not filename:
        return jsonify({"error": "filename is required"}), 400

    lowered = filename.lower()

    try:
        if lowered.endswith(".pdf"):
            blocks = extract_pdf(uploaded_file.stream)
            file_type = "pdf"
        elif lowered.endswith(".epub"):
            uploaded_file.stream.seek(0)
            blocks = extract_epub(uploaded_file.stream)
            file_type = "epub"
        else:
            return (
                jsonify({"error": "unsupported file type; upload a PDF or EPUB"}),
                400,
            )
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Failed to parse upload")
        return jsonify({"error": "failed to parse file", "detail": str(exc)}), 400

    return jsonify({"file_type": file_type, "content": blocks})


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(error):
    limit = app.config.get("MAX_CONTENT_LENGTH")
    return (
        jsonify(
            {
                "error": "file too large",
                "limit_bytes": limit,
            }
        ),
        413,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
