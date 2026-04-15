"""
pdf_parser.py — PDF text extraction using pdfplumber.

Handles:
  - Digital PDFs (clean text layer)
  - Image-only PDFs (routes to image_parser for OCR)
  - Multi-page forms (each page analyzed independently, results merged)

No external API calls. Pure local computation.
"""

import io
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger("irs_forms_export.parsers.pdf")

# Lazy imports — not all deployments need these
_pdfplumber = None
_pdf2image = None


def _get_pdfplumber():
    global _pdfplumber
    if _pdfplumber is None:
        try:
            import pdfplumber
            _pdfplumber = pdfplumber
        except ImportError:
            raise ImportError(
                "pdf_parser: pdfplumber not installed — run: pip install pdfplumber"
            )
    return _pdfplumber


def _get_pdf2image():
    global _pdf2image
    if _pdf2image is None:
        try:
            import pdf2image
            _pdf2image = pdf2image
        except ImportError:
            _pdf2image = None
    return _pdf2image


def _is_image_only_pdf(pdf) -> bool:
    """Return True if PDF has no text layer (scanned / image-only)."""
    total_chars = 0
    for page in pdf.pages[:3]:  # Check first 3 pages
        text = page.extract_text() or ""
        total_chars += len(text.strip())
    return total_chars < 50  # Fewer than 50 chars = likely image-only


def _extract_page_text(page) -> str:
    """Extract text from a single pdfplumber page, including tables."""
    lines = []

    # Try word-level extraction first (preserves layout better for tax forms)
    try:
        words = page.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=False,
            use_text_flow=True,
        )
        if words:
            # Group words into lines by y-position
            from collections import defaultdict
            line_map = defaultdict(list)
            for w in words:
                y_bucket = round(w["top"] / 5) * 5  # 5pt buckets
                line_map[y_bucket].append(w)
            for y_key in sorted(line_map.keys()):
                line_words = sorted(line_map[y_key], key=lambda w: w["x0"])
                lines.append(" ".join(w["text"] for w in line_words))
    except Exception:
        pass

    # Fall back to extract_text if word extraction failed
    if not lines:
        raw = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
        lines = raw.split("\n")

    # Also extract table data (tax forms often use tables for box values)
    try:
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                if row:
                    row_text = "  |  ".join(str(cell or "").strip() for cell in row if cell)
                    if row_text.strip():
                        lines.append(row_text)
    except Exception:
        pass

    return "\n".join(lines)


def _ocr_pdf_pages(pdf_bytes: bytes) -> str:
    """
    OCR an image-only PDF using pdf2image + pytesseract.
    Falls back gracefully if not available.
    """
    pdf2image = _get_pdf2image()
    if pdf2image is None:
        logger.warning("pdf_parser: pdf2image not available — cannot OCR image PDF")
        return ""

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning("pdf_parser: pytesseract/PIL not available for OCR")
        return ""

    try:
        images = pdf2image.convert_from_bytes(pdf_bytes, dpi=300)
        all_text = []
        for i, img in enumerate(images):
            text = pytesseract.image_to_string(img, config="--psm 6")
            if text.strip():
                all_text.append(f"[Page {i+1}]\n{text}")
        return "\n\n".join(all_text)
    except Exception as e:
        logger.error(f"pdf_parser: OCR failed: {e}")
        return ""


def parse_pdf_bytes(pdf_bytes: bytes) -> list[dict]:
    """
    Parse a PDF from raw bytes.

    Returns list of extracted page dicts:
        [{"page": 1, "text": "...", "form_type": "...", ...}, ...]

    Each dict contains the full extracted text plus form detection metadata.
    The caller (document_parser) will run extract_form_fields on each.
    """
    pdfplumber = _get_pdfplumber()

    all_pages = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Check if this is an image-only PDF
            if _is_image_only_pdf(pdf):
                logger.info("pdf_parser: image-only PDF detected, routing to OCR")
                ocr_text = _ocr_pdf_pages(pdf_bytes)
                if ocr_text:
                    all_pages.append({
                        "page": "ocr",
                        "text": ocr_text,
                        "source": "tesseract_ocr",
                    })
                else:
                    all_pages.append({
                        "page": "ocr_failed",
                        "text": "",
                        "source": "tesseract_ocr",
                        "error": "No text extracted from image PDF — use vision endpoint for better results",
                    })
                return all_pages

            # Digital PDF — extract text from each page
            for i, page in enumerate(pdf.pages):
                text = _extract_page_text(page)
                if text.strip():
                    all_pages.append({
                        "page": i + 1,
                        "text": text,
                        "source": "pdfplumber",
                        "page_width": float(page.width),
                        "page_height": float(page.height),
                    })

    except Exception as e:
        logger.error(f"pdf_parser: failed to parse PDF: {e}")
        all_pages.append({
            "page": "error",
            "text": "",
            "error": str(e),
        })

    return all_pages


def parse_pdf(path: Union[str, Path]) -> list[dict]:
    """
    Parse a PDF file by path. Returns same format as parse_pdf_bytes.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"pdf_parser: file not found: {path}")
    if not path.suffix.lower() == ".pdf":
        raise ValueError(f"pdf_parser: expected .pdf file, got: {path.suffix}")

    return parse_pdf_bytes(path.read_bytes())
