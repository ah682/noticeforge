"""Bounded local extraction. Text offsets always refer to the retained page text."""

import csv
import hashlib
import io
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import pymupdf

from noticeforge.models import Document, SourcePage, TableCell, TextLine

MAX_BYTES = int(os.getenv("NOTICEFORGE_MAX_BYTES", "10485760"))
MAX_PAGES = int(os.getenv("NOTICEFORGE_MAX_PAGES", "100"))
MAX_PAGE_CHARS = 60000
OCR_DPI = 300
MAX_OCR_PIXELS = 20_000_000
OCR_TIMEOUT_SECONDS = 30
MAX_OCR_TSV_BYTES = 8 * 1024 * 1024
# PyMuPDF does not support concurrent native work from multiple threads. Keep
# complete document lifetimes serialized across parsing, OCR and page rendering.
# This lock protects one process; it is not a tested multiworker isolation guarantee.
_PDF_LOCK = Lock()


class InputError(ValueError):
    pass


@contextmanager
def _open_pdf(data: bytes):
    with _PDF_LOCK:
        try:
            pdf = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise InputError("The PDF could not be opened") from exc
        with pdf:
            yield pdf


def _make_page(number, lines, width=None, height=None, method="text", tables=None):
    text = ""
    located = []
    for value, box in lines:
        located.append(TextLine(text=value, start=len(text), end=len(text) + len(value), bbox=box))
        text += value + "\n"
    return SourcePage(
        number=number,
        text=text,
        width=width,
        height=height,
        method=method,
        lines=located,
        tables=tables or [],
    )


def _ocr_lines(tsv: str, scale: float, width: float, height: float):
    """Retain literal OCR words and locate each reconstructed line in PDF points.

    Two or more unusually wide gaps preserve column separators in a simple table
    row. This is a layout heuristic, not character correction or a claim that an
    arbitrary scan's table was recovered. Every resulting critical value remains
    review-required. A single large gap (for example, a footer) stays ordinary text.
    """
    groups: dict[tuple[str, str, str], list[tuple[str, int, int, int, int]]] = {}
    try:
        reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
        required = {"level", "block_num", "par_num", "line_num", "left", "top", "width", "height", "text"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Missing TSV columns")
        for row in reader:
            if row.get("level") != "5" or not (row.get("text") or "").strip():
                continue
            x, y, w, h = (int(row[name]) for name in ("left", "top", "width", "height"))
            if min(x, y, w, h) < 0 or x + w > width * scale + 1 or y + h > height * scale + 1:
                raise ValueError("OCR word lies outside page")
            key = (row["block_num"], row["par_num"], row["line_num"])
            groups.setdefault(key, []).append((row["text"], x, y, w, h))
    except (KeyError, TypeError, ValueError, csv.Error) as exc:
        raise InputError("OCR returned malformed text or page coordinates") from exc
    lines = []
    for words in groups.values():
        # Preserve Tesseract's reading order, including characters such as O/0.
        threshold = max(12 * scale, 2.5 * statistics.median(max(1, word[4]) for word in words))
        gaps = [right[1] - (left[1] + left[3]) for left, right in zip(words, words[1:])]
        preserve_columns = sum(gap > threshold for gap in gaps) >= 2
        text = words[0][0]
        for gap, word in zip(gaps, words[1:], strict=True):
            text += ("\t" if preserve_columns and gap > threshold else " ") + word[0]
        x = min(word[1] for word in words)
        y = min(word[2] for word in words)
        x2 = max(word[1] + word[3] for word in words)
        y2 = max(word[2] + word[4] for word in words)
        lines.append((text, (x / scale, y / scale, min(width, x2 / scale), min(height, y2 / scale))))
    return lines


def _ocr(page):
    """Optional English Tesseract TSV, bounded in time, threads and image area."""
    if not shutil.which("tesseract"):
        raise InputError("Tesseract OCR is unavailable; install it to read image-only pages")
    scale = min(OCR_DPI / 72, (MAX_OCR_PIXELS / max(1, page.rect.width * page.rect.height)) ** 0.5)
    if math.ceil(page.rect.width * scale) * math.ceil(page.rect.height * scale) > MAX_OCR_PIXELS:
        # Account for raster dimension rounding, including very wide pages.
        low, high = 0.0, scale
        for _ in range(40):
            middle = (low + high) / 2
            if math.ceil(page.rect.width * middle) * math.ceil(page.rect.height * middle) <= MAX_OCR_PIXELS:
                low = middle
            else:
                high = middle
        scale = low
    with tempfile.TemporaryDirectory(prefix="noticeforge-ocr-") as tmp:
        path = Path(tmp) / "page.png"
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        pixmap.set_dpi(round(72 * scale), round(72 * scale))
        pixmap.save(path)
        # OpenMP defaults can otherwise consume every host CPU per uploaded page.
        env = {**os.environ, "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"}
        try:
            output = Path(tmp) / "words.tsv"
            errors = Path(tmp) / "stderr.txt"
            with output.open("wb") as stdout, errors.open("wb") as stderr:
                subprocess.run(
                    ["tesseract", str(path), "stdout", "-l", "eng", "--psm", "6", "tsv"],
                    stdout=stdout,
                    stderr=stderr,
                    timeout=OCR_TIMEOUT_SECONDS,
                    check=True,
                    env=env,
                )
            if output.stat().st_size > MAX_OCR_TSV_BYTES:
                raise InputError("OCR text exceeded its 8 MiB page output limit")
            tsv = output.read_text(encoding="utf-8")
        except (subprocess.SubprocessError, OSError) as exc:
            raise InputError(f"OCR failed or exceeded its {OCR_TIMEOUT_SECONDS}-second page limit") from exc
        except UnicodeDecodeError as exc:
            raise InputError("OCR returned invalid UTF-8 text") from exc
    return _ocr_lines(tsv, scale, page.rect.width, page.rect.height)


def extract_document(data: bytes, filename: str, expected_pages: int | None = None) -> Document:
    if not data:
        raise InputError("The uploaded document is empty")
    if len(data) > MAX_BYTES:
        raise InputError(f"Document exceeds the {MAX_BYTES // 1048576} MiB limit")
    if expected_pages is not None and not 1 <= expected_pages <= 10000:
        raise InputError("Expected page count must be between 1 and 10000")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".pdf"}:
        raise InputError("Upload a UTF-8 .txt or a .pdf notice")
    warnings = []
    pages = []
    actual_count = 0
    if suffix == ".txt":
        if b"\x00" in data or data.startswith(b"%PDF"):
            raise InputError("The text file contains binary content")
        try:
            raw_text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InputError("Text notices must use UTF-8 encoding") from exc
        raw_pages = raw_text.replace("\r\n", "\n").split("\f")
        actual_count = len(raw_pages)
        for i, text in enumerate(raw_pages[:MAX_PAGES], 1):
            if len(text) > MAX_PAGE_CHARS:
                warnings.append(f"Page {i} truncated at {MAX_PAGE_CHARS} characters")
            pages.append(_make_page(i, [(line, None) for line in text[:MAX_PAGE_CHARS].splitlines()]))
    else:
        if not data.startswith(b"%PDF-"):
            raise InputError("The file is not a PDF (invalid signature)")
        with _open_pdf(data) as pdf:
            if pdf.needs_pass:
                raise InputError("Password-protected PDFs are not supported")
            actual_count = len(pdf)
            for i in range(min(len(pdf), MAX_PAGES)):
                page = pdf[i]
                raw = page.get_text("dict", sort=True)
                lines = []
                for block in raw["blocks"]:
                    for line in block.get("lines", []):
                        value = "".join(span["text"] for span in line["spans"])
                        lines.append((value, tuple(line["bbox"])))
                method = "pdf-text"
                if not any(value.strip() for value, _ in lines):
                    try:
                        lines = _ocr(page)
                        method = "ocr"
                    except InputError as exc:
                        warnings.append(f"Page {i + 1}: {exc}")
                        method = "unreadable"
                elif any(
                    image.get("bbox")
                    and (image["bbox"][2] - image["bbox"][0]) * (image["bbox"][3] - image["bbox"][1])
                    > 0.04 * page.rect.width * page.rect.height
                    for image in page.get_image_info()
                ):
                    warnings.append(
                        f"Page {i + 1}: substantial image region accompanies native text; "
                        "embedded image content has not been OCR-verified"
                    )
                tables = []
                if method == "pdf-text":
                    try:
                        for table in page.find_tables().tables:
                            extracted = table.extract()
                            rows = []
                            for row_index, row in enumerate(extracted):
                                cells = table.rows[row_index].cells
                                rows.append(
                                    [
                                        TableCell(text=value or "", bbox=cell)
                                        for value, cell in zip(row, cells, strict=True)
                                    ]
                                )
                            tables.append(rows)
                    except Exception:
                        warnings.append(f"Page {i + 1}: table layout detection failed; text requires review")
                retained = []
                length = 0
                for value, box in lines:
                    if length + len(value) > MAX_PAGE_CHARS:
                        warnings.append(f"Page {i + 1} truncated at {MAX_PAGE_CHARS} characters")
                        break
                    retained.append((value, box))
                    length += len(value) + 1
                pages.append(_make_page(i + 1, retained, page.rect.width, page.rect.height, method, tables))
    if not pages:
        raise InputError("Document has no pages")
    if actual_count > MAX_PAGES:
        warnings.append(f"Only {MAX_PAGES} of {actual_count} pages extracted (page limit)")
    advertised = []
    numbers = []
    for page in pages:
        for match in re.finditer(r"\bPage\s+(\d+)\s*(?:of|/)\s*(\d+)\b", page.text, re.I):
            try:
                number, total = int(match[1]), int(match[2])
                if not 1 <= number <= total <= 10000:
                    raise ValueError()
            except ValueError:
                warnings.append("Printed page count is invalid or exceeds 10000; verify the original notice")
                continue
            numbers.append(number)
            advertised.append(total)
    expected = expected_pages or (max(advertised) if advertised else actual_count)
    if expected != actual_count:
        warnings.append(f"Expected {expected} pages but received {actual_count}; notice may be incomplete")
    if numbers and (len(set(numbers)) != len(numbers) or set(numbers) != set(range(1, expected + 1))):
        warnings.append("Printed page sequence is missing or duplicated; verify the original notice")
    if any(not page.text.strip() for page in pages):
        warnings.append("One or more pages contain no readable text")
    return Document(
        sha256=hashlib.sha256(data).hexdigest(),
        filename=Path(filename).name,
        media_type="application/pdf" if suffix == ".pdf" else "text/plain",
        byte_size=len(data),
        pages=pages,
        expected_pages=expected,
        complete=not warnings,
        warnings=warnings,
    )


def render_page(data: bytes, number: int) -> bytes:
    with _open_pdf(data) as pdf:
        if not 1 <= number <= len(pdf):
            raise InputError("Page not found")
        page = pdf[number - 1]
        scale = min(1.5, (12_000_000 / max(1, page.rect.width * page.rect.height)) ** 0.5)
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
