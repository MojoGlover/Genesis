"""
form_1040.py — 2025 Form 1040 Line Mapping
===========================================
Maps TaxResult fields to the actual lines on the 2025 Form 1040.
Use this to cross-reference with your actual IRS form or tax software.

Form 1040 (2025) structure reference: IRS Publication 17
"""

from typing import Dict, Any
from tax_engine.calculator import TaxResult


def map_to_1040(result: TaxResult) -> Dict[str, Any]:
    """
    Returns a dict of 1040 line numbers → values from a TaxResult.
    Lines correspond to the 2025 Form 1040 layout.
    """

    if result.year != 2025:
        print(f"⚠️  Note: This mapping is optimized for 2025 Form 1040. "
              f"Year {result.year} may have different line numbers.")

    lines: Dict[str, Any] = {}

    # ══ PAGE 1 — INCOME ══════════════════════════════════════════════════════

    lines["1a"]  = ("Wages, salaries, tips (W-2 Box 1)",
                    result.gross_income - _non_wage_income(result))
    # Note: Lines 1b-1h cover specific W-2 situations (dependent care, tips, etc.)
    lines["2b"]  = ("Taxable interest", "from income entries")
    lines["3b"]  = ("Ordinary dividends", "from income entries")
    lines["4b"]  = ("IRA distributions (taxable)", "from income entries")
    lines["5b"]  = ("Pensions and annuities (taxable)", "from income entries")
    lines["6b"]  = ("Social Security benefits (taxable — up to 85%)",
                    "from income entries")
    lines["7"]   = ("Capital gain or (loss) — attach Schedule D if required",
                    "from income entries")
    lines["8"]   = ("Additional income (Schedule 1, Part I)", "freelance/rental/other")

    lines["9"]   = ("TOTAL INCOME (add lines 1a + 2b + 3b + 4b + 5b + 6b + 7 + 8)",
                    result.gross_income)

    # ══ PAGE 1 — ADJUSTMENTS (above-the-line) ════════════════════════════════

    lines["10"]  = ("Adjustments to income (Schedule 1, Part II)",
                    result.above_the_line_total)
    # Schedule 1 Part II breakdown:
    lines["S1-11"] = ("Educator expenses (max $300/$600 MFJ)", "from deductions")
    lines["S1-15"] = ("Student loan interest deduction (max $2,500)", "from deductions")
    lines["S1-16"] = ("Tuition and fees deduction", "N/A for 2025")
    lines["S1-17"] = ("Self-employed health insurance deduction", "from deductions")
    lines["S1-19"] = ("IRA deduction", "from deductions")
    lines["S1-23"] = ("Half of self-employment tax (SE tax deduction)",
                      result.se_tax_deduction)
    lines["S1-25"] = ("HSA deduction (Form 8889)", "from deductions")

    lines["11"]  = ("ADJUSTED GROSS INCOME (line 9 minus line 10)",
                    result.agi)

    # ══ PAGE 2 — STANDARD OR ITEMIZED DEDUCTION ══════════════════════════════

    lines["12"]  = (f"Standard OR itemized deduction [{result.deduction_used}]",
                    result.deduction_amount)
    # If itemized: attach Schedule A
    lines["13"]  = ("QBI deduction (Section 199A — Form 8995 or 8995-A)",
                    result.qbi_deduction)
    lines["14"]  = ("Sum of lines 12 + 13",
                    round(result.deduction_amount + result.qbi_deduction, 2))
    lines["15"]  = ("TAXABLE INCOME (line 11 minus line 14, min $0)",
                    result.taxable_income)

    # ══ PAGE 2 — TAX & CREDITS ═══════════════════════════════════════════════

    lines["16"]  = ("Tax (from Tax Table or Tax Computation Worksheet)",
                    result.ordinary_tax + result.lt_cap_gains_tax)
    # LT cap gains → use Qualified Dividends & Capital Gain Tax Worksheet
    lines["17"]  = ("Alternative Minimum Tax (Form 6251)", "calculate if applicable")
    lines["18"]  = ("Add lines 16 + 17", result.ordinary_tax + result.lt_cap_gains_tax)

    lines["19"]  = ("Child Tax Credit / Credit for Other Dependents",
                    result.child_tax_credit)
    lines["20"]  = ("Schedule 3, line 8 (other non-refundable credits)",
                    result.other_credits_total)
    lines["21"]  = ("Add lines 19 + 20", result.total_credits)
    lines["22"]  = ("Subtract line 21 from line 18 (tax after credits, min $0)",
                    result.total_tax_before_credits - result.total_credits)

    lines["23"]  = ("Other taxes (SE tax — Schedule SE)", result.se_tax_total)
    lines["24"]  = ("TOTAL TAX (line 22 + line 23)", result.total_tax)

    # ══ PAGE 2 — PAYMENTS ════════════════════════════════════════════════════

    lines["25a"] = ("Federal income tax withheld (W-2 Box 2 + 1099s)",
                    result.federal_withholding)
    lines["26"]  = ("2025 estimated tax payments + amount applied from 2024",
                    result.estimated_payments)
    lines["27"]  = ("Earned Income Credit (EIC — Schedule EIC)", "if applicable")
    lines["28"]  = ("Additional Child Tax Credit (Schedule 8812)",
                    "if applicable — refundable portion")
    lines["29"]  = ("American Opportunity Credit (Form 8863, line 29)", "if applicable")
    lines["31"]  = ("Other refundable credits (Schedule 3, line 15)", "if applicable")

    total_payments = result.federal_withholding + result.estimated_payments
    lines["33"]  = ("TOTAL PAYMENTS (add lines 25-32)", total_payments)

    # ══ PAGE 2 — REFUND OR AMOUNT OWED ═══════════════════════════════════════

    if result.refund_or_owed >= 0:
        lines["35a"] = ("REFUND (line 33 minus line 24)", result.refund_or_owed)
        lines["37"]  = ("AMOUNT YOU OWE", 0.0)
    else:
        lines["35a"] = ("REFUND", 0.0)
        lines["37"]  = ("AMOUNT YOU OWE (line 24 minus line 33)",
                        abs(result.refund_or_owed))

    # ══ SCHEDULE A — ITEMIZED DEDUCTIONS (if itemized) ═══════════════════════

    if result.deduction_used == "itemized":
        lines["SchedA-1"]  = ("Medical and dental expenses (enter total)", "from deductions")
        lines["SchedA-3"]  = ("Medical: subtract 7.5% of AGI floor applied", "calculated")
        lines["SchedA-5"]  = ("State and local income taxes (or sales tax)", "from deductions")
        lines["SchedA-6"]  = ("Real estate taxes", "from deductions")
        lines["SchedA-7"]  = ("SALT total (capped at $10,000 for 2025)", "from deductions")
        lines["SchedA-8a"] = ("Home mortgage interest (Form 1098)", "from deductions")
        lines["SchedA-11"] = ("Gifts to charity (cash)", "from deductions")
        lines["SchedA-12"] = ("Gifts to charity (other than cash)", "from deductions")
        lines["SchedA-17"] = ("Total itemized deductions", result.itemized_deductions)

    return lines


def print_1040(result: TaxResult) -> None:
    """Pretty-print the 1040 mapping."""
    lines = map_to_1040(result)
    proj = " ⚠️ PROJECTED" if result.is_projected else ""
    print(f"\n{'═'*65}")
    print(f"  FORM 1040 LINE MAPPING — Tax Year {result.year}{proj}")
    print(f"  Filing Status: {result.filing_status.upper()}")
    print(f"{'═'*65}")
    for line_num, (desc, val) in lines.items():
        if isinstance(val, float):
            val_str = f"${val:>12,.2f}"
        else:
            val_str = f"  {str(val):<20}"
        print(f"  Line {line_num:<10} {desc[:38]:<38}  {val_str}")
    print(f"{'═'*65}\n")


def _non_wage_income(result: TaxResult) -> float:
    """Rough estimate of non-W2 income for line 1a calculation."""
    # This is approximate since TaxResult stores totals, not source breakdown
    # A full implementation would track income sources separately
    return 0.0  # calculator stores gross; refine if tracking W2 separately
