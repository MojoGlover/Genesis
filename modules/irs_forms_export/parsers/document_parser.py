"""
document_parser.py — Main document ingestion dispatcher.

Routes files to the right parser based on extension and content,
then converts extracted data to load_accountant_data()-compatible dicts.

Flow:
    File/bytes → detect type → parse → extract fields → normalize to agent dict

Supported sources:
    .pdf        — pdfplumber (digital) or tesseract OCR (image)
    .jpg/.png   — pytesseract OCR
    .heic       — pillow-heif + pytesseract (iPhone photos)
    .csv/.tsv   — mileage logs or expense sheets
    .xlsx/.xls  — same as CSV via openpyxl
    str         — pre-extracted text (from PlugOps vision, etc.)
"""

import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger("irs_forms_export.parsers.document")

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
                     ".webp", ".gif", ".heic"}
_CSV_EXTENSIONS   = {".csv", ".tsv", ".txt"}
_EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
_PDF_EXTENSION    = ".pdf"


def _detect_source_type(source: Union[str, Path, bytes],
                         hint: str = None) -> str:
    """
    Determine document type: 'pdf', 'image', 'csv', 'excel', 'text', or 'unknown'.
    """
    if hint:
        return hint.lower()

    if isinstance(source, (str, Path)):
        path = Path(source)
        ext  = path.suffix.lower()
        if ext == _PDF_EXTENSION:
            return "pdf"
        if ext in _IMAGE_EXTENSIONS:
            return "image"
        if ext in _CSV_EXTENSIONS:
            return "csv"
        if ext in _EXCEL_EXTENSIONS:
            return "excel"
        # Could be a pre-extracted text string
        if isinstance(source, str) and len(source) > 50 and "\n" in source:
            return "text"
        return "unknown"

    if isinstance(source, bytes):
        # Detect by magic bytes
        if source[:4] == b"%PDF":
            return "pdf"
        if source[:2] in (b"\xff\xd8", b"\x89P"):  # JPEG, PNG
            return "image"
        if source[:4] == b"PK\x03\x04":  # ZIP = xlsx
            return "excel"
        # Try to decode as text
        try:
            decoded = source[:512].decode("utf-8")
            if "," in decoded or "\t" in decoded:
                return "csv"
        except UnicodeDecodeError:
            pass
        return "unknown"

    if isinstance(source, str) and len(source) > 50:
        return "text"

    return "unknown"


def _parsed_pages_to_fields(pages: list[dict]) -> list[dict]:
    """
    Run form detection + field extraction on parsed page dicts.
    Returns list of extracted field dicts.
    """
    from .form_patterns import detect_form_type, extract_form_fields

    results = []
    full_text = "\n\n".join(p.get("text", "") for p in pages if p.get("text"))

    # Try whole-document detection first (some forms span pages)
    overall_form_type = detect_form_type(full_text)

    if overall_form_type != "UNKNOWN":
        # Treat all pages as one form
        fields = extract_form_fields(full_text, overall_form_type)
        fields["_pages"] = len(pages)
        results.append(fields)
    else:
        # Try each page independently (multi-form documents)
        for page in pages:
            text = page.get("text", "")
            if not text.strip():
                continue
            form_type = detect_form_type(text)
            if form_type != "UNKNOWN":
                fields = extract_form_fields(text, form_type)
                fields["_page"] = page.get("page")
                results.append(fields)
            else:
                # Still try extraction — might be a receipt or partial form
                fields = extract_form_fields(text, "RECEIPT")
                if fields.get("amount", 0) > 0:
                    results.append(fields)

    return results


def _fields_to_agent_dict(fields_list: list[dict]) -> dict:
    """
    Convert a list of extracted field dicts into a load_accountant_data()-compatible dict.

    Multiple forms of the same type are accumulated as list entries.
    Returns a partial dict — caller merges with existing data.
    """
    agent_dict = {
        "w2_income": [],
        "1099_income": [],
        "_receipts": [],   # Non-standard — accountant can use for expense categorization
        "_parse_metadata": [],
    }

    for fields in fields_list:
        form_type = fields.get("_form_type", "UNKNOWN")
        meta = {
            "form_type": form_type,
            "confidence": fields.get("_confidence", 0.0),
            "tax_year":   fields.get("_tax_year", 2024),
        }
        agent_dict["_parse_metadata"].append(meta)

        if form_type == "W2":
            agent_dict["w2_income"].append({
                "employer_name": fields.get("employer_name", ""),
                "ein": fields.get("ein"),
                "wages": fields.get("wages", 0.0),
                "federal_withholding": fields.get("federal_withholding", 0.0),
                "box3_ss_wages": fields.get("box3_ss_wages", 0.0),
                "box4_ss_withheld": fields.get("box4_ss_withheld", 0.0),
                "box5_medicare_wages": fields.get("box5_medicare_wages", 0.0),
                "box6_medicare_withheld": fields.get("box6_medicare_withheld", 0.0),
                "state_wages": fields.get("state_wages", 0.0),
                "state_withholding": fields.get("state_withholding", 0.0),
            })

        elif form_type in ("1099_NEC", "1099_INT", "1099_DIV", "1099_MISC"):
            agent_dict["1099_income"].append({
                "payer": fields.get("payer", ""),
                "tin":   fields.get("tin"),
                "type":  fields.get("type", form_type.split("_")[1]),
                "amount": fields.get("amount", 0.0),
                "qualified_dividends": fields.get("qualified_dividends", 0.0),
                "federal_withheld": fields.get("federal_withheld", 0.0),
            })

        elif form_type == "RECEIPT":
            agent_dict["_receipts"].append({
                "vendor":          fields.get("vendor", ""),
                "date":            fields.get("date", ""),
                "amount":          fields.get("amount", 0.0),
                "category_hint":   fields.get("category_hint", "other"),
            })

    # Clean up empty lists
    if not agent_dict["w2_income"]:
        del agent_dict["w2_income"]
    if not agent_dict["1099_income"]:
        del agent_dict["1099_income"]
    if not agent_dict["_receipts"]:
        del agent_dict["_receipts"]

    return agent_dict


# ── Public API ────────────────────────────────────────────────────────────────

def parse_document(source: Union[str, Path, bytes], *,
                   hint: str = None,
                   tax_year: int = 2024,
                   mileage_irs_rate: float = None) -> dict:
    """
    Parse any supported document type and extract tax-relevant data.

    Args:
        source:          File path, raw bytes, or pre-extracted text string.
        hint:            Force document type: 'pdf', 'image', 'csv', 'excel', 'text'.
        tax_year:        Used for mileage rate lookup if parsing a mileage log.
        mileage_irs_rate: Override IRS mileage rate (default: from YEAR_RULES).

    Returns:
        Partial load_accountant_data()-compatible dict. Keys present depend on
        what was found:
            w2_income       — list of W-2 dicts (if W-2 found)
            1099_income     — list of 1099 dicts (if 1099 found)
            mileage         — mileage dict (if mileage log found)
            _receipts       — list of receipt dicts (if receipts found)
            _parse_metadata — list of metadata dicts per extracted form
            _parse_errors   — list of error strings (if any)
    """
    from .pdf_parser import parse_pdf_bytes, parse_pdf
    from .image_parser import parse_image_bytes, parse_image
    from .csv_parser import parse_mileage_csv, parse_expense_csv
    from .form_patterns import detect_form_type

    source_type = _detect_source_type(source, hint)
    result = {}

    try:
        if source_type == "pdf":
            if isinstance(source, bytes):
                pages = parse_pdf_bytes(source)
            else:
                pages = parse_pdf(source)

            fields_list = _parsed_pages_to_fields(pages)
            if fields_list:
                result = _fields_to_agent_dict(fields_list)
            else:
                result["_parse_errors"] = ["No recognizable forms found in PDF"]

        elif source_type == "image":
            if isinstance(source, bytes):
                ocr_result = parse_image_bytes(source)
            else:
                ocr_result = parse_image(source)

            text = ocr_result.get("text", "")
            if text.strip():
                form_type = detect_form_type(text)
                from .form_patterns import extract_form_fields
                fields = extract_form_fields(text, form_type)
                result = _fields_to_agent_dict([fields])
                result["_ocr_confidence"] = ocr_result.get("confidence_hint", 0.0)
            else:
                result["_parse_errors"] = [
                    ocr_result.get("error", "OCR produced no text — "
                                   "try PlugOps vision tool for better accuracy")
                ]

        elif source_type in ("csv", "excel"):
            # Try mileage log first, fall back to expense sheet
            # Determine by content sniff
            try:
                from .csv_parser import _read_csv_rows, _read_excel_rows, _find_col, _MILES_ALIASES
                if source_type == "excel":
                    headers, _ = _read_excel_rows(source)
                else:
                    headers, _ = _read_csv_rows(source)

                miles_col = _find_col(headers, _MILES_ALIASES)
                is_mileage = bool(miles_col) or any(
                    "odo" in h.lower() or "mile" in h.lower() for h in headers
                )
            except Exception:
                is_mileage = False

            if is_mileage:
                mileage = parse_mileage_csv(source, tax_year, mileage_irs_rate)
                result["mileage"] = mileage
            else:
                expenses = parse_expense_csv(source, tax_year)
                result["_expense_sheet"] = expenses

        elif source_type == "text":
            # Pre-extracted text — run form detection directly
            text = source if isinstance(source, str) else source.decode("utf-8", errors="replace")
            form_type = detect_form_type(text)
            from .form_patterns import extract_form_fields
            fields = extract_form_fields(text, form_type)
            result = _fields_to_agent_dict([fields])

        else:
            result["_parse_errors"] = [f"Unsupported document type (hint={hint}, detected={source_type})"]

    except Exception as e:
        logger.error(f"document_parser: parse_document failed: {e}")
        result["_parse_errors"] = result.get("_parse_errors", []) + [str(e)]

    return result


def parse_documents(sources: list, **kwargs) -> list[dict]:
    """
    Parse a list of documents. Returns a list of partial agent dicts.
    Passes **kwargs to each parse_document() call.
    """
    results = []
    for source in sources:
        try:
            r = parse_document(source, **kwargs)
            results.append(r)
        except Exception as e:
            results.append({"_parse_errors": [str(e)]})
    return results


def merge_parsed_docs(parsed_list: list[dict]) -> dict:
    """
    Merge multiple parsed document dicts into a single load_accountant_data()-
    compatible dict by accumulating lists and combining dicts.

    Usage:
        docs = parse_documents([w2_path, nec_path, mileage_csv])
        merged = merge_parsed_docs(docs)
        tax_return = load_accountant_data(merged)
    """
    merged = {
        "w2_income": [],
        "1099_income": [],
        "_receipts": [],
        "_expense_sheets": [],
        "_parse_metadata": [],
        "_parse_errors": [],
    }

    for doc in parsed_list:
        merged["w2_income"].extend(doc.get("w2_income", []))
        merged["1099_income"].extend(doc.get("1099_income", []))
        merged["_receipts"].extend(doc.get("_receipts", []))
        merged["_parse_metadata"].extend(doc.get("_parse_metadata", []))
        merged["_parse_errors"].extend(doc.get("_parse_errors", []))

        # Mileage — sum up if multiple logs
        if "mileage" in doc:
            existing = merged.get("mileage")
            new_m = doc["mileage"]
            if existing is None:
                merged["mileage"] = dict(new_m)
            else:
                existing["total_business_miles"] = round(
                    existing.get("total_business_miles", 0) +
                    new_m.get("total_business_miles", 0), 1
                )
                existing["trips"] = existing.get("trips", []) + new_m.get("trips", [])
                # Recompute deduction
                rate = existing.get("irs_rate", new_m.get("irs_rate", 0.67))
                existing["computed_deduction"] = round(
                    existing["total_business_miles"] * rate, 2)

        # Expense sheets — accumulate
        if "_expense_sheet" in doc:
            merged["_expense_sheets"].append(doc["_expense_sheet"])

        # OCR confidence
        if "_ocr_confidence" in doc:
            merged.setdefault("_ocr_confidences", []).append(doc["_ocr_confidence"])

    # Clean up empty lists
    for key in ("_receipts", "_parse_errors"):
        if not merged[key]:
            del merged[key]

    return merged
