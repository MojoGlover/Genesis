"""
form_patterns.py — IRS form detection and field extraction via regex.

Pure text → structured data. No IO, no external calls.

Supported form types:
    W2          — W-2 Wage and Tax Statement
    1099_NEC    — 1099-NEC Nonemployee Compensation
    1099_INT    — 1099-INT Interest Income
    1099_DIV    — 1099-DIV Dividends and Distributions
    1099_MISC   — 1099-MISC Miscellaneous Income
    RECEIPT     — Generic expense receipt
    MILEAGE_LOG — Mileage tracking log
    UNKNOWN     — Not recognized
"""

import re
from typing import Optional

# ── Form type constants ────────────────────────────────────────────────────────

FORM_TYPES = {
    "W2":         "W-2 Wage and Tax Statement",
    "1099_NEC":   "1099-NEC Nonemployee Compensation",
    "1099_INT":   "1099-INT Interest Income",
    "1099_DIV":   "1099-DIV Dividends and Distributions",
    "1099_MISC":  "1099-MISC Miscellaneous Information",
    "RECEIPT":    "Expense Receipt",
    "MILEAGE_LOG": "Mileage Log",
    "UNKNOWN":    "Unknown Document",
}

# ── Form detection patterns ────────────────────────────────────────────────────

_FORM_SIGNATURES = [
    ("W2",        [
        r"W-?2\s+Wage",
        r"OMB\s*No\.?\s*1545-0008",
        r"wages[,\s]+tips[,\s]+other comp",
        r"box\s*1\s*wages",
    ]),
    ("1099_NEC",  [
        r"1099-?NEC",
        r"nonemployee\s+compensation",
        r"OMB\s*No\.?\s*1545-0116",
        r"form\s+1099[- ]nec",
    ]),
    ("1099_INT",  [
        r"1099-?INT",
        r"interest\s+income",
        r"OMB\s*No\.?\s*1545-0112",
        r"form\s+1099[- ]int",
    ]),
    ("1099_DIV",  [
        r"1099-?DIV",
        r"dividends\s+and\s+distributions",
        r"OMB\s*No\.?\s*1545-0110",
        r"total\s+ordinary\s+dividends",
    ]),
    ("1099_MISC", [
        r"1099-?MISC",
        r"miscellaneous\s+information",
        r"OMB\s*No\.?\s*1545-0115",
        r"form\s+1099[- ]misc",
    ]),
    ("MILEAGE_LOG", [
        r"mileage\s+log",
        r"business\s+miles",
        r"odometer\s+(start|end|reading)",
        r"trip\s+purpose",
        r"irs\s+mileage",
    ]),
    ("RECEIPT",   [
        r"subtotal|total\s+(due|amount|charge)",
        r"receipt\s*#",
        r"invoice\s*#",
        r"thank\s+you\s+for\s+your\s+purchase",
        r"visa|mastercard|amex|discover",
    ]),
]


def detect_form_type(text: str) -> str:
    """
    Detect which IRS form type is described in `text`.
    Returns one of the FORM_TYPES keys.
    """
    text_lower = text.lower()
    for form_type, patterns in _FORM_SIGNATURES:
        matches = sum(1 for p in patterns if re.search(p, text_lower, re.IGNORECASE))
        if matches >= 1:
            # NEC and MISC both contain "1099" — require stronger match for ambiguous cases
            if form_type in ("1099_NEC", "1099_INT", "1099_DIV", "1099_MISC"):
                if matches >= 1 and re.search(r"1099[- ]?" + form_type.split("_")[1],
                                              text_lower, re.IGNORECASE):
                    return form_type
                elif matches >= 2:
                    return form_type
            else:
                return form_type
    return "UNKNOWN"


# ── Money value extraction helpers ────────────────────────────────────────────

def _extract_dollar(text: str, label_pattern: str,
                    window: int = 200,
                    fallback: float = 0.0) -> float:
    """
    Find `label_pattern` in text, then extract the nearest dollar value
    within `window` characters after the match.
    """
    m = re.search(label_pattern, text, re.IGNORECASE)
    if not m:
        return fallback
    snippet = text[m.end(): m.end() + window]
    # Look for dollar amounts: optional $, digits with optional commas, optional decimal
    amounts = re.findall(r"\$?\s*([\d,]+\.?\d{0,2})", snippet)
    for amt in amounts:
        try:
            val = float(amt.replace(",", ""))
            if val > 0:
                return round(val, 2)
        except ValueError:
            continue
    return fallback


def _extract_text_after(text: str, label_pattern: str,
                         window: int = 150,
                         default: str = "") -> str:
    """Extract a short text string after a label."""
    m = re.search(label_pattern, text, re.IGNORECASE)
    if not m:
        return default
    snippet = text[m.end(): m.end() + window].strip()
    # Take first non-empty line
    for line in snippet.split("\n"):
        line = line.strip()
        if line and len(line) > 1:
            return line
    return snippet[:60].strip() or default


def _extract_ein(text: str) -> Optional[str]:
    """Extract an EIN (XX-XXXXXXX format) from text."""
    m = re.search(r"\b(\d{2}-\d{7})\b", text)
    return m.group(1) if m else None


def _extract_ssn_last4(text: str) -> Optional[str]:
    """Extract last 4 of SSN (XXX-XX-XXXX or XXX-XX-#### masked)."""
    # Masked: XXX-XX-1234 or ***-**-1234
    m = re.search(r"[X*]{3}[- ][X*]{2}[- ](\d{4})", text, re.IGNORECASE)
    if m:
        return m.group(1)
    # Full SSN — only return last 4
    m = re.search(r"\b\d{3}[- ]\d{2}[- ](\d{4})\b", text)
    if m:
        return m.group(1)
    return None


def _extract_tax_year(text: str, default: int = 2024) -> int:
    """Extract the tax year from form text."""
    # "2024 W-2" or "Tax Year 2024" or "For calendar year 2024"
    m = re.search(r"\b(202[34567])\b", text)
    return int(m.group(1)) if m else default


# ── Form-specific field extractors ────────────────────────────────────────────

def _extract_w2(text: str) -> dict:
    """
    Extract W-2 fields from text.
    Returns dict compatible with load_accountant_data() w2_income list entry.
    """
    result = {
        "_form_type": "W2",
        "_confidence": 0.0,
        "employer_name": "",
        "ein": None,
        "wages": 0.0,
        "federal_withholding": 0.0,
        "box3_ss_wages": 0.0,
        "box4_ss_withheld": 0.0,
        "box5_medicare_wages": 0.0,
        "box6_medicare_withheld": 0.0,
        "state_wages": 0.0,
        "state_withholding": 0.0,
    }

    # Employer name — usually at top of form before EIN
    employer_match = re.search(
        r"(?:employer'?s?\s+name[,\s]+address[^:]*:?\s*)([A-Z][^\n]{2,60})",
        text, re.IGNORECASE
    )
    if not employer_match:
        # Try first substantial uppercase line
        for line in text.split("\n")[:15]:
            line = line.strip()
            if len(line) > 4 and line.isupper() and not re.match(r"^\d", line):
                result["employer_name"] = line.title()
                break
    else:
        result["employer_name"] = employer_match.group(1).strip()

    result["ein"] = _extract_ein(text)

    # Box 1 — Wages, tips, other comp
    result["wages"] = (
        _extract_dollar(text, r"(?:box\s*1\b|1\s+wages,?\s+tips)", window=120)
        or _extract_dollar(text, r"wages[,\s]+tips[,\s]+other\s+comp", window=120)
    )

    # Box 2 — Federal income tax withheld
    result["federal_withholding"] = (
        _extract_dollar(text, r"(?:box\s*2\b|2\s+federal\s+income\s+tax\s+withheld)", window=120)
        or _extract_dollar(text, r"federal\s+income\s+tax\s+withheld", window=120)
    )

    # Box 3 — Social security wages
    result["box3_ss_wages"] = _extract_dollar(
        text, r"(?:box\s*3\b|3\s+social\s+security\s+wages)", window=120)

    # Box 4 — Social security tax withheld
    result["box4_ss_withheld"] = _extract_dollar(
        text, r"(?:box\s*4\b|4\s+social\s+security\s+tax\s+withheld)", window=120)

    # Box 5 — Medicare wages
    result["box5_medicare_wages"] = _extract_dollar(
        text, r"(?:box\s*5\b|5\s+medicare\s+wages)", window=120)

    # Box 6 — Medicare tax withheld
    result["box6_medicare_withheld"] = _extract_dollar(
        text, r"(?:box\s*6\b|6\s+medicare\s+tax\s+withheld)", window=120)

    # State wages and withholding (boxes 15-17)
    result["state_wages"] = _extract_dollar(
        text, r"(?:box\s*16|16\s+state\s+wages)", window=100)
    result["state_withholding"] = _extract_dollar(
        text, r"(?:box\s*17|17\s+state\s+income\s+tax)", window=100)

    # Confidence: count non-zero fields
    filled = sum(1 for k in ["wages", "federal_withholding", "box3_ss_wages"]
                 if result[k] > 0)
    result["_confidence"] = min(filled / 3.0, 1.0)

    return result


def _extract_1099_nec(text: str) -> dict:
    """
    Extract 1099-NEC fields.
    Returns dict compatible with load_accountant_data() 1099_income list entry.
    """
    result = {
        "_form_type": "1099_NEC",
        "_confidence": 0.0,
        "payer": "",
        "tin": None,
        "type": "NEC",
        "amount": 0.0,
        "federal_withheld": 0.0,
        "flows_to_schedule_c": True,  # NEC default = Schedule C
    }

    # Payer name — usually at top
    for line in text.split("\n")[:10]:
        line = line.strip()
        if len(line) > 3 and not re.match(r"^[\d\s\$\-\.]+$", line):
            if not re.search(r"1099|OMB|IRS|Department|Treasury|form", line, re.IGNORECASE):
                result["payer"] = line
                break

    result["tin"] = _extract_ein(text)

    # Box 1 — Nonemployee compensation
    result["amount"] = (
        _extract_dollar(text, r"(?:box\s*1\b|1\s+nonemployee\s+comp)", window=120)
        or _extract_dollar(text, r"nonemployee\s+compensation", window=120)
    )

    # Box 4 — Federal income tax withheld
    result["federal_withheld"] = (
        _extract_dollar(text, r"(?:box\s*4\b|4\s+federal\s+income\s+tax\s+withheld)", window=120)
        or _extract_dollar(text, r"federal\s+income\s+tax\s+withheld", window=120)
    )

    result["_confidence"] = 0.9 if result["amount"] > 0 else 0.3
    return result


def _extract_1099_int(text: str) -> dict:
    """Extract 1099-INT fields."""
    result = {
        "_form_type": "1099_INT",
        "_confidence": 0.0,
        "payer": "",
        "tin": None,
        "type": "INT",
        "amount": 0.0,
        "federal_withheld": 0.0,
    }

    for line in text.split("\n")[:10]:
        line = line.strip()
        if len(line) > 3 and not re.match(r"^[\d\s\$\-\.]+$", line):
            if not re.search(r"1099|OMB|IRS|Department|Treasury|form", line, re.IGNORECASE):
                result["payer"] = line
                break

    result["tin"] = _extract_ein(text)
    result["amount"] = (
        _extract_dollar(text, r"(?:box\s*1\b|1\s+interest\s+income)", window=120)
        or _extract_dollar(text, r"interest\s+income", window=120)
    )
    result["federal_withheld"] = _extract_dollar(
        text, r"federal\s+income\s+tax\s+withheld", window=120)
    result["_confidence"] = 0.9 if result["amount"] > 0 else 0.3
    return result


def _extract_1099_div(text: str) -> dict:
    """Extract 1099-DIV fields."""
    result = {
        "_form_type": "1099_DIV",
        "_confidence": 0.0,
        "payer": "",
        "tin": None,
        "type": "DIV",
        "amount": 0.0,              # Box 1a total ordinary dividends
        "qualified_dividends": 0.0,  # Box 1b
        "federal_withheld": 0.0,
    }

    for line in text.split("\n")[:10]:
        line = line.strip()
        if len(line) > 3 and not re.match(r"^[\d\s\$\-\.]+$", line):
            if not re.search(r"1099|OMB|IRS|Department|Treasury|form", line, re.IGNORECASE):
                result["payer"] = line
                break

    result["tin"] = _extract_ein(text)
    result["amount"] = (
        _extract_dollar(text, r"(?:1a\s+total\s+ordinary|box\s*1a)", window=120)
        or _extract_dollar(text, r"total\s+ordinary\s+dividends", window=120)
    )
    result["qualified_dividends"] = (
        _extract_dollar(text, r"(?:1b\s+qualified|box\s*1b)", window=120)
        or _extract_dollar(text, r"qualified\s+dividends", window=120)
    )
    result["federal_withheld"] = _extract_dollar(
        text, r"federal\s+income\s+tax\s+withheld", window=120)
    result["_confidence"] = 0.9 if result["amount"] > 0 else 0.3
    return result


def _extract_receipt(text: str) -> dict:
    """
    Extract expense receipt fields.
    Returns dict with vendor, date, amount, category hints.
    """
    result = {
        "_form_type": "RECEIPT",
        "_confidence": 0.0,
        "vendor": "",
        "date": "",
        "amount": 0.0,
        "category_hint": "other",
    }

    # Vendor — usually first prominent line
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        result["vendor"] = lines[0][:60]

    # Date
    date_m = re.search(
        r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})\b",
        text
    )
    if date_m:
        result["date"] = date_m.group(1)

    # Total amount — look for "Total", "Amount Due", "TOTAL"
    result["amount"] = (
        _extract_dollar(text, r"\bTotal\s+(Due|Amount|Charge|:|\b)", window=80)
        or _extract_dollar(text, r"\bAMOUNT\s+DUE\b", window=80)
        or _extract_dollar(text, r"\bTOTAL\b", window=80)
        or _extract_dollar(text, r"\bAmount\s+Charged\b", window=80)
    )

    # Category hint from keywords
    text_lower = text.lower()
    if any(w in text_lower for w in ["fuel", "gas station", "shell", "exxon", "bp ", "chevron"]):
        result["category_hint"] = "fuel"
    elif any(w in text_lower for w in ["amazon", "supplies", "staples", "office depot"]):
        result["category_hint"] = "supplies"
    elif any(w in text_lower for w in ["phone", "verizon", "t-mobile", "att", "boost", "cricket"]):
        result["category_hint"] = "phone_internet"
    elif any(w in text_lower for w in ["repair", "maintenance", "oil change", "tire", "auto"]):
        result["category_hint"] = "repairs"
    elif any(w in text_lower for w in ["hotel", "motel", "airbnb", "flight", "airline", "uber", "lyft"]):
        result["category_hint"] = "travel"
    elif any(w in text_lower for w in ["restaurant", "food", "doordash", "grubhub", "mcdonald", "subway"]):
        result["category_hint"] = "meals"

    result["_confidence"] = 0.7 if result["amount"] > 0 else 0.3
    return result


# ── Main public API ────────────────────────────────────────────────────────────

_FORM_EXTRACTORS = {
    "W2":        _extract_w2,
    "1099_NEC":  _extract_1099_nec,
    "1099_INT":  _extract_1099_int,
    "1099_DIV":  _extract_1099_div,
    "1099_MISC": _extract_1099_nec,   # similar structure
    "RECEIPT":   _extract_receipt,
}


def extract_form_fields(text: str, form_type: Optional[str] = None) -> dict:
    """
    Extract structured fields from IRS form text.

    Args:
        text:      Raw text from PDF parser or OCR.
        form_type: Override form type detection (one of FORM_TYPES keys).
                   If None, auto-detects.

    Returns:
        Dict with extracted fields + metadata:
            _form_type:  detected/specified form type
            _confidence: float 0-1 extraction confidence
            _raw_snippet: first 300 chars of input text
            ...form-specific fields...
    """
    if form_type is None:
        form_type = detect_form_type(text)

    extractor = _FORM_EXTRACTORS.get(form_type, _extract_receipt)
    result = extractor(text)
    result["_form_type"] = form_type
    result["_raw_snippet"] = text[:300].replace("\n", " ")
    result["_tax_year"] = _extract_tax_year(text)
    return result
