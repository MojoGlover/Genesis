"""
exporters.py — Output handlers for IRS Forms Export module

Formats:
  1. TXF (Tax Exchange Format v042) — primary, TurboTax native import
  2. Tab-delimited (.txt) — fallback, human-readable
  3. JSON — for API consumption / Accountant agent storage
  4. Summary text — human-readable tax position overview
"""

from __future__ import annotations
import json
import os
from datetime import date
from pathlib import Path
from typing import List

from .models import TaxReturn, TurboTaxExport, DeductionMethod
from .validator import YEAR_RULES


# ─── TXF Export ───────────────────────────────────────────────────────────────

def export_txf(export: TurboTaxExport, filepath: str) -> None:
    """
    Write a TXF v042 file for TurboTax import.

    TXF format:
        V042                    <- version header (first line)
        A<account name>         <- account/payer name
        N<description>          <- description
        C<category code>        <- form/line mapping
        L<copy number>          <- which copy (1st W2, 2nd W2, etc.)
        $<amount>               <- dollar amount
        D<MM/DD/YYYY>           <- date
        ^                       <- end of record
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = ["V042"]  # Required header

    for rec in export.txf_records:
        # Account/payer name
        if rec.get("name"):
            lines.append(f"A{rec['name']}")
        # Description
        if rec.get("description"):
            lines.append(f"N{rec['description']}")
        # Category code
        lines.append(f"C{rec['category']}")
        # Copy number
        lines.append(f"L{rec['copy']}")
        # Dollar amount (format as integer cents? No — TXF uses decimal)
        lines.append(f"${rec['amount']:.2f}")
        # Date
        if rec.get("date"):
            lines.append(f"D{rec['date']}")
        # End of record
        lines.append("^")

    content = "\n".join(lines) + "\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[irs_forms_export] TXF written: {filepath} ({len(export.txf_records)} records)")


# ─── Tab-delimited fallback ───────────────────────────────────────────────────

def export_tab_delimited(export: TurboTaxExport, filepath: str) -> None:
    """
    Write tab-delimited .txt fallback file.
    Format: FIELD_NAME<tab>VALUE per line.
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = [
        f"# TurboTax Import Data — Tax Year {export.tax_return.tax_year}",
        f"# Generated: {date.today().isoformat()}",
        f"# State: FL (no state income tax)",
        "",
    ]

    for rec in export.tab_records:
        lines.append(f"{rec['field']}\t{rec['value']}")

    if export.export_notes:
        lines.append("")
        lines.append("# Notes:")
        for note in export.export_notes:
            lines.append(f"# {note}")

    content = "\n".join(lines) + "\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[irs_forms_export] Tab-delimited written: {filepath}")


# ─── JSON export ──────────────────────────────────────────────────────────────

def export_json(export: TurboTaxExport, filepath: str) -> None:
    """Export full structured data as JSON for API/agent consumption."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "tax_year":     export.tax_return.tax_year,
        "generated":    date.today().isoformat(),
        "filing_status": export.tax_return.personal_info.filing_status.value,
        "state":        "FL",
        "txf_records":  export.txf_records,
        "tab_records":  export.tab_records,
        "notes":        export.export_notes,
        "summary": {
            "total_w2_wages":        export.tax_return.total_w2_wages,
            "total_1099_nec":        export.tax_return.total_1099_nec,
            "total_se_net":          round(export.tax_return.total_se_net, 2),
            "se_tax":                export.tax_return.se_tax,
            "se_deduction":          export.tax_return.se_deduction,
            "qbi_deduction":         export.tax_return.qbi_deduction,
            "agi":                   round(export.tax_return.agi, 2),
            "total_federal_withheld": export.tax_return.total_federal_withheld,
        },
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[irs_forms_export] JSON written: {filepath}")


# ─── Human-readable summary ───────────────────────────────────────────────────

def export_summary(tax_return: TaxReturn) -> str:
    """
    Generate a human-readable summary of the tax position.
    Suitable for display in the Accountant agent chat interface.
    """
    rules = YEAR_RULES.get(tax_return.tax_year, YEAR_RULES[2024])
    status = tax_return.personal_info.filing_status.value
    std_ded = rules["standard_deduction"].get(status, 14_600)

    # Deduction to use
    use_itemized = (
        tax_return.deductions.method == DeductionMethod.ITEMIZED
        and tax_return.deductions.itemized_total > std_ded
    )
    deduction_used = (
        tax_return.deductions.itemized_total if use_itemized else std_ded
    )
    deduction_label = "Itemized" if use_itemized else "Standard"

    # Taxable income estimate
    agi = tax_return.agi
    taxable_income = max(
        agi - deduction_used - tax_return.qbi_deduction, 0
    )

    # Rough tax estimate (bracket calculation)
    estimated_tax = _estimate_tax(taxable_income, status, tax_return.tax_year)
    total_withheld = tax_return.total_federal_withheld
    plus_se_tax    = tax_return.se_tax
    total_liability = estimated_tax + plus_se_tax
    refund_or_owe  = total_withheld - total_liability

    lines = [
        f"═══ TAX SUMMARY — {tax_return.tax_year} FEDERAL ({'Florida — no state tax'}) ═══",
        "",
        "── INCOME ──",
    ]

    if tax_return.total_w2_wages > 0:
        lines.append(f"  W-2 Wages:              ${tax_return.total_w2_wages:>12,.2f}")
    if tax_return.total_1099_nec > 0:
        lines.append(f"  1099-NEC (SE):          ${tax_return.total_1099_nec:>12,.2f}")
    if tax_return.total_1099_int > 0:
        lines.append(f"  Interest (1099-INT):    ${tax_return.total_1099_int:>12,.2f}")
    if tax_return.total_1099_div > 0:
        lines.append(f"  Dividends (1099-DIV):   ${tax_return.total_1099_div:>12,.2f}")

    if tax_return.self_employment:
        for se in tax_return.self_employment:
            lines.append(f"  Schedule C ({se.business_name}):")
            lines.append(f"    Gross receipts:       ${se.gross_receipts:>12,.2f}")
            lines.append(f"    Total expenses:       ${se.expenses.total:>12,.2f}")
            lines.append(f"    Net profit:           ${se.net_profit:>12,.2f}")

        if tax_return.mileage:
            lines.append(f"  Business Miles:         {int(tax_return.mileage.total_business_miles):>12,} mi")
            lines.append(f"  Mileage Deduction:      ${tax_return.mileage.deduction_amount:>12,.2f}")

    lines += [
        "",
        "── ADJUSTMENTS ──",
        f"  SE Tax Deduction (50%): ${tax_return.se_deduction:>12,.2f}",
        "",
        f"  Adjusted Gross Income:  ${agi:>12,.2f}",
        "",
        "── DEDUCTIONS ──",
        f"  {deduction_label} Deduction:    ${deduction_used:>12,.2f}",
    ]

    if tax_return.qbi_deduction > 0:
        lines.append(f"  QBI Deduction (199A):   ${tax_return.qbi_deduction:>12,.2f}")

    lines += [
        "",
        f"  Taxable Income:         ${taxable_income:>12,.2f}",
        "",
        "── TAX CALCULATION ──",
        f"  Income Tax (est.):      ${estimated_tax:>12,.2f}",
        f"  Self-Employment Tax:    ${plus_se_tax:>12,.2f}",
        f"  Total Tax Liability:    ${total_liability:>12,.2f}",
        "",
        "── PAYMENTS & CREDITS ──",
        f"  Federal Withheld:       ${total_withheld:>12,.2f}",
    ]

    if tax_return.credits.total > 0:
        lines.append(f"  Tax Credits:            ${tax_return.credits.total:>12,.2f}")

    lines.append("")
    if refund_or_owe >= 0:
        lines.append(f"  ✓ ESTIMATED REFUND:     ${refund_or_owe:>12,.2f}")
    else:
        lines.append(f"  ✗ ESTIMATED TAX DUE:    ${abs(refund_or_owe):>12,.2f}")

    lines += [
        "",
        "─────────────────────────────────────────────────────────",
        "⚠  This is an estimate. Consult a tax professional for",
        "   final preparation and filing.",
        "─────────────────────────────────────────────────────────",
    ]

    return "\n".join(lines)


# ─── Export all formats at once ───────────────────────────────────────────────

def export_all(export: TurboTaxExport, output_dir: str) -> dict:
    """
    Write TXF, tab-delimited, and JSON files to output_dir.
    Returns dict of {format: filepath}.
    """
    year = export.tax_return.tax_year
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    paths = {
        "txf":  os.path.join(output_dir, f"{year}_taxes.txf"),
        "tab":  os.path.join(output_dir, f"{year}_taxes_turbotax.txt"),
        "json": os.path.join(output_dir, f"{year}_taxes_export.json"),
    }

    export_txf(export, paths["txf"])
    export_tab_delimited(export, paths["tab"])
    export_json(export, paths["json"])

    return paths


# ─── Tax bracket estimator ────────────────────────────────────────────────────

def _estimate_tax(taxable_income: float, status: str, year: int) -> float:
    """Simple bracket-based income tax estimate (not exact — use tax engine for precision)."""
    brackets_2024 = {
        "single": [(0.10, 0), (0.12, 11_600), (0.22, 47_150), (0.24, 100_525),
                   (0.32, 191_950), (0.35, 243_725), (0.37, 609_350)],
        "mfj":    [(0.10, 0), (0.12, 23_200), (0.22, 94_300), (0.24, 201_050),
                   (0.32, 383_900), (0.35, 487_450), (0.37, 731_200)],
        "hoh":    [(0.10, 0), (0.12, 16_550), (0.22, 63_100), (0.24, 100_500),
                   (0.32, 191_950), (0.35, 243_700), (0.37, 609_350)],
    }
    brackets_2025 = {
        "single": [(0.10, 0), (0.12, 11_925), (0.22, 48_475), (0.24, 103_350),
                   (0.32, 197_300), (0.35, 250_525), (0.37, 626_350)],
        "mfj":    [(0.10, 0), (0.12, 23_850), (0.22, 96_950), (0.24, 206_700),
                   (0.32, 394_600), (0.35, 501_050), (0.37, 751_600)],
        "hoh":    [(0.10, 0), (0.12, 17_000), (0.22, 64_850), (0.24, 103_350),
                   (0.32, 197_300), (0.35, 250_500), (0.37, 626_350)],
    }

    brackets_map = brackets_2025 if year == 2025 else brackets_2024
    brackets = brackets_map.get(status, brackets_map["single"])

    tax = 0.0
    for i, (rate, lower) in enumerate(brackets):
        upper = brackets[i + 1][1] if i + 1 < len(brackets) else float("inf")
        if taxable_income <= lower:
            break
        taxable_in_bracket = min(taxable_income, upper) - lower
        tax += taxable_in_bracket * rate

    return round(tax, 2)
