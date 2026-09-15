"""
Extracts plain text from uploaded requirement documents.

Kept deliberately dumb: one function per format, no OCR, no layout
reconstruction. Good enough for text-based requirement docs, which is
the realistic case for this tool. Scanned/image-only PDFs will come back
empty — the caller should treat an empty extraction as an error rather
than silently proceeding.
"""
from __future__ import annotations

import io

import docx  # python-docx
import pymupdf  # PyMuPDF

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class ExtractionError(ValueError):
    pass


def extract_text(filename: str, content: bytes) -> str:
    lower = filename.lower()

    if lower.endswith(".pdf"):
        return _extract_pdf(content)
    if lower.endswith(".docx"):
        return _extract_docx(content)
    if lower.endswith((".txt", ".md")):
        return _extract_plain_text(content)

    raise ExtractionError(
        f"Unsupported file type for '{filename}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


def _extract_pdf(content: bytes) -> str:
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:  # pymupdf raises its own exception types
        raise ExtractionError(f"Could not open PDF: {exc}") from exc

    pages = [page.get_text() for page in doc]
    doc.close()
    text = "\n\n".join(pages).strip()
    if not text:
        raise ExtractionError(
            "No extractable text found in this PDF. It may be a scanned image without OCR."
        )
    return text


def _extract_docx(content: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(content))
    except Exception as exc:
        raise ExtractionError(f"Could not open DOCX: {exc}") from exc

    parts = [p.text for p in document.paragraphs if p.text.strip()]
    # Also pull table cell text — requirements are often tabulated.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())

    text = "\n".join(parts).strip()
    if not text:
        raise ExtractionError("No extractable text found in this DOCX.")
    return text


def _extract_plain_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    text = text.strip()
    if not text:
        raise ExtractionError("File is empty.")
    return text
