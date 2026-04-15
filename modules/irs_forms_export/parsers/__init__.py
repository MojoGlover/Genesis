"""
irs_forms_export.parsers — IRS form text-extraction intelligence.

These parsers are pure local computation — no external API calls.
They consume text (from PDF, OCR, or direct input) and produce
dicts compatible with load_accountant_data().

External capabilities (file upload, vision API) live in PlugOps.
"""

from .form_patterns import detect_form_type, extract_form_fields, FORM_TYPES
from .pdf_parser import parse_pdf, parse_pdf_bytes
from .image_parser import parse_image, parse_image_bytes, ocr_available
from .csv_parser import parse_mileage_csv, parse_expense_csv
from .document_parser import parse_document, parse_documents, merge_parsed_docs

__all__ = [
    "detect_form_type",
    "extract_form_fields",
    "FORM_TYPES",
    "parse_pdf",
    "parse_pdf_bytes",
    "parse_image",
    "parse_image_bytes",
    "ocr_available",
    "parse_mileage_csv",
    "parse_expense_csv",
    "parse_document",
    "parse_documents",
    "merge_parsed_docs",
]
