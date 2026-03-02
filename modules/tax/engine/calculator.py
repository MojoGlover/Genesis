"""
calculator.py — Core Tax Calculation Engine
============================================
KEY DESIGN: Your entries (income, deductions, credits, withholding) are stored
on the TaxCalculator instance. Switching years NEVER erases your data.
Call calculate(year=XXXX) to apply different year rules to the same entries.

Usage:
    calc = TaxCalculator(filing_status="single")
    calc.set_income(w2=85000, freelance=18000)
    calc.set_deductions(mortgage_interest=9500, charity=3000)
    calc.set_withholding(federal=14000)

    result_2025 = calc.calculate(year=2025)   # primary
    result_2024 = calc.calculate(year=2024)   # compare prior year
    result_2026 = calc.calculate(year=2026)   # plan ahead (projected)
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional, List
import json

from tax_engine.years import get_year
from tax_engine.years.base import BracketResult


# ─── Input Containers ─────────────────────────────────────────────────────────

@dataclass
class IncomeEntries:
    """All income sources. Add what applies; leave others at 0."""
    w2:                   float = 0.0   # Box 1 wages from W-2(s)
    freelance:            float = 0.0   # 1099-NEC / self-employment
    business_net:         float = 0.0   # Schedule C net (after expenses)
    interest:             float = 0.0   # 1099-INT
    ordinary_dividends:   float = 0.0   # 1099-DIV Box 1a
    qualified_dividends:  float = 0.0   # 1099-DIV Box 1b (subset of ordinary)
    lt_capital_gains:     float = 0.0   # Long-term cap gains (1099-B)
    st_capital_gains:     float = 0.0   # Short-term cap gains (taxed as ordinary)
    rental_net:           float = 0.0   # Net rental income after expenses
    social_security:      float = 0.0   # SS benefits received
    pension_annuity:      float = 0.0   # 1099-R distributions
    ira_distribution:     float = 0.0   # Traditional IRA withdrawals
    other:                float = 0.0   # Alimony (pre-2019), prizes, etc.

    # Metadata
    notes: str = ""


@dataclass
class DeductionEntries:
    """
    Deductions split into above-the-line (reduce AGI) and below-the-line
    (Schedule A itemized, compared against standard deduction).
    """
    # ── Above-the-Line (always usable, reduce AGI directly) ──────────────────
    ira_contribution:         float = 0.0  # Traditional IRA only
    student_loan_interest:    float = 0.0  # Max $2,500 before phaseout
    hsa_contribution:         float = 0.0  # Pre-tax HSA contributions
    self_employed_health_ins: float = 0.0  # 100% deductible
    educator_expenses:        float = 0.0  # Max $300 ($600 MFJ both educators)
    alimony_paid:             float = 0.0  # Pre-2019 divorce agreements only

    # ── Itemized — Schedule A ─────────────────────────────────────────────────
    state_income_tax:         float = 0.0  # State/local income OR sales tax
    property_tax:             float = 0.0  # Real estate property taxes
    mortgage_interest:        float = 0.0  # Primary + 1 secondary home
    points_paid:              float = 0.0  # Mortgage points (purchase year)
    mortgage_insurance:       float = 0.0  # PMI (if qualified)
    charity_cash:             float = 0.0  # Cash donations to qualified orgs
    charity_noncash:          float = 0.0  # Property/goods donations
    medical_expenses:         float = 0.0  # TOTAL (before 7.5% AGI floor)
    investment_interest:      float = 0.0  # Interest on margin loans, etc.
    casualty_losses:          float = 0.0  # Federally declared disasters only

    # ── Other Adjustments ─────────────────────────────────────────────────────
    retirement_contrib_401k:  float = 0.0  # Employee pre-tax 401k (info only)
    # ^ 401k reduces W-2 Box 1 automatically — don't double-count

    notes: str = ""


@dataclass
class CreditEntries:
    """Tax credits to apply after computing tax."""
    child_tax_credit_children:  int   = 0      # Number of qualifying children
    child_care_expenses:        float = 0.0    # Form 2441
    child_care_dependents:      int   = 0
    education_credit:           float = 0.0    # AOTC / LLC (Form 8863)
    retirement_savings_credit:  float = 0.0    # Saver's Credit (Form 8880)
    ev_credit:                  float = 0.0    # Clean vehicle credit
    other_credits:              float = 0.0

    notes: str = ""


# ─── Result Containers ────────────────────────────────────────────────────────

@dataclass
class TaxResult:
    """Full tax calculation result for a specific year."""

    year: int
    filing_status: str
    is_projected: bool = False
    projection_warning: str = ""

    # ── Income ────────────────────────────────────────────────────────────────
    gross_income:           float = 0.0
    se_tax:                 float = 0.0
    se_tax_deduction:       float = 0.0   # above-the-line (half of SE tax)
    above_the_line_total:   float = 0.0
    agi:                    float = 0.0

    # ── Deductions ────────────────────────────────────────────────────────────
    standard_deduction:     float = 0.0
    itemized_deductions:    float = 0.0
    deduction_used:         str   = ""    # "standard" or "itemized"
    deduction_amount:       float = 0.0
    personal_exemptions:    float = 0.0   # 2026 projected
    qbi_deduction:          float = 0.0
    taxable_income:         float = 0.0

    # ── Tax Calculation ───────────────────────────────────────────────────────
    ordinary_tax:           float = 0.0
    lt_cap_gains_tax:       float = 0.0
    se_tax_total:           float = 0.0   # full SE tax (both halves)
    total_tax_before_credits: float = 0.0
    bracket_detail:         List[BracketResult] = field(default_factory=list)

    # ── Credits ──────────────────────────────────────────────────────────────
    child_tax_credit:       float = 0.0
    other_credits_total:    float = 0.0
    total_credits:          float = 0.0

    # ── Final ─────────────────────────────────────────────────────────────────
    total_tax:              float = 0.0
    federal_withholding:    float = 0.0
    estimated_payments:     float = 0.0
    refund_or_owed:         float = 0.0   # positive=refund, negative=you owe
    effective_rate:         float = 0.0   # total_tax / gross_income
    marginal_rate:          float = 0.0   # top bracket rate hit

    def to_dict(self) -> dict:
        d = asdict(self)
        # Convert BracketResult list to plain dicts
        d["bracket_detail"] = [
            {
                "rate": f"{b['bracket_rate']*100:.0f}%",
                "from": b["bracket_min"],
                "to": b["bracket_max"] if b["bracket_max"] != float("inf") else "∞",
                "income_in_bracket": round(b["income_in_bracket"], 2),
                "tax": round(b["tax_in_bracket"], 2),
            }
            for b in d["bracket_detail"]
        ]
        return d

    def summary(self) -> str:
        """Human-readable one-page summary."""
        proj = " ⚠️ PROJECTED" if self.is_projected else ""
        lines = [
            f"═══════════════════════════════════════════════",
            f"  TAX SUMMARY — {self.year}{proj}",
            f"  Filing Status: {self.filing_status.upper()}",
            f"═══════════════════════════════════════════════",
            f"  Gross Income:         ${self.gross_income:>12,.2f}",
            f"  Above-the-Line Ded.:  ${self.above_the_line_total:>12,.2f}",
            f"  AGI:                  ${self.agi:>12,.2f}",
            f"  ─────────────────────────────────────────────",
            f"  Deduction ({self.deduction_used}): ${self.deduction_amount:>12,.2f}",
        ]
        if self.personal_exemptions:
            lines.append(f"  Personal Exemptions:  ${self.personal_exemptions:>12,.2f}")
        if self.qbi_deduction:
            lines.append(f"  QBI Deduction:        ${self.qbi_deduction:>12,.2f}")
        lines += [
            f"  Taxable Income:       ${self.taxable_income:>12,.2f}",
            f"  ─────────────────────────────────────────────",
            f"  Ordinary Tax:         ${self.ordinary_tax:>12,.2f}",
        ]
        if self.lt_cap_gains_tax:
            lines.append(f"  Cap Gains Tax:        ${self.lt_cap_gains_tax:>12,.2f}")
        if self.se_tax_total:
            lines.append(f"  Self-Employment Tax:  ${self.se_tax_total:>12,.2f}")
        lines += [
            f"  Tax Before Credits:   ${self.total_tax_before_credits:>12,.2f}",
            f"  Credits:             -${self.total_credits:>12,.2f}",
            f"  ─────────────────────────────────────────────",
            f"  Total Tax:            ${self.total_tax:>12,.2f}",
            f"  Withholding/Payments:-${self.federal_withholding + self.estimated_payments:>12,.2f}",
            f"  ─────────────────────────────────────────────",
        ]
        if self.refund_or_owed >= 0:
            lines.append(f"  REFUND:              +${self.refund_or_owed:>12,.2f}")
        else:
            lines.append(f"  AMOUNT OWED:          ${abs(self.refund_or_owed):>12,.2f}")
        lines += [
            f"  ─────────────────────────────────────────────",
            f"  Effective Rate:        {self.effective_rate*100:>11.2f}%",
            f"  Marginal Rate:         {self.marginal_rate*100:>11.1f}%",
            f"═══════════════════════════════════════════════",
        ]
        if self.projection_warning:
            lines.append(f"\n  ⚠️  {self.projection_warning}")
        return "\n".join(lines)


# ─── Main Calculator ──────────────────────────────────────────────────────────

class TaxCalculator:
    """
    Stateful tax calculator. Set your data once, calculate for any year.
    Switching years NEVER erases income, deduction, or credit entries.
    """

    def __init__(
        self,
        filing_status: str = "single",
        taxpayer_age: int = 40,
        spouse_age: Optional[int] = None,
        num_dependents: int = 0,
        default_year: int = 2025,
    ):
        self.filing_status = filing_status
        self.taxpayer_age = taxpayer_age
        self.spouse_age = spouse_age
        self.num_dependents = num_dependents
        self.default_year = default_year

        # ── Persistent entries ────────────────────────────────────────────────
        # These STAY when you switch years.
        self._income = IncomeEntries()
        self._deductions = DeductionEntries()
        self._credits = CreditEntries()
        self._federal_withholding: float = 0.0
        self._estimated_payments: float = 0.0

        # ── Result cache ──────────────────────────────────────────────────────
        self._results: Dict[int, TaxResult] = {}

    # ── Setters (fluent — return self for chaining) ───────────────────────────

    def set_income(
        self,
        w2: float = None,
        freelance: float = None,
        business_net: float = None,
        interest: float = None,
        ordinary_dividends: float = None,
        qualified_dividends: float = None,
        lt_capital_gains: float = None,
        st_capital_gains: float = None,
        rental_net: float = None,
        social_security: float = None,
        pension_annuity: float = None,
        ira_distribution: float = None,
        other: float = None,
        notes: str = None,
    ) -> "TaxCalculator":
        """Set income entries. Only updates fields you pass — others unchanged."""
        if w2 is not None:                self._income.w2 = w2
        if freelance is not None:         self._income.freelance = freelance
        if business_net is not None:      self._income.business_net = business_net
        if interest is not None:          self._income.interest = interest
        if ordinary_dividends is not None: self._income.ordinary_dividends = ordinary_dividends
        if qualified_dividends is not None: self._income.qualified_dividends = qualified_dividends
        if lt_capital_gains is not None:  self._income.lt_capital_gains = lt_capital_gains
        if st_capital_gains is not None:  self._income.st_capital_gains = st_capital_gains
        if rental_net is not None:        self._income.rental_net = rental_net
        if social_security is not None:   self._income.social_security = social_security
        if pension_annuity is not None:   self._income.pension_annuity = pension_annuity
        if ira_distribution is not None:  self._income.ira_distribution = ira_distribution
        if other is not None:             self._income.other = other
        if notes is not None:             self._income.notes = notes
        self._results.clear()  # invalidate cached results
        return self

    def set_deductions(
        self,
        ira_contribution: float = None,
        student_loan_interest: float = None,
        hsa_contribution: float = None,
        self_employed_health_ins: float = None,
        educator_expenses: float = None,
        alimony_paid: float = None,
        state_income_tax: float = None,
        property_tax: float = None,
        mortgage_interest: float = None,
        points_paid: float = None,
        mortgage_insurance: float = None,
        charity_cash: float = None,
        charity_noncash: float = None,
        medical_expenses: float = None,
        investment_interest: float = None,
        casualty_losses: float = None,
        notes: str = None,
    ) -> "TaxCalculator":
        """Set deduction entries. Only updates fields you pass."""
        if ira_contribution is not None:      self._deductions.ira_contribution = ira_contribution
        if student_loan_interest is not None: self._deductions.student_loan_interest = student_loan_interest
        if hsa_contribution is not None:      self._deductions.hsa_contribution = hsa_contribution
        if self_employed_health_ins is not None: self._deductions.self_employed_health_ins = self_employed_health_ins
        if educator_expenses is not None:     self._deductions.educator_expenses = educator_expenses
        if alimony_paid is not None:          self._deductions.alimony_paid = alimony_paid
        if state_income_tax is not None:      self._deductions.state_income_tax = state_income_tax
        if property_tax is not None:          self._deductions.property_tax = property_tax
        if mortgage_interest is not None:     self._deductions.mortgage_interest = mortgage_interest
        if points_paid is not None:           self._deductions.points_paid = points_paid
        if mortgage_insurance is not None:    self._deductions.mortgage_insurance = mortgage_insurance
        if charity_cash is not None:          self._deductions.charity_cash = charity_cash
        if charity_noncash is not None:       self._deductions.charity_noncash = charity_noncash
        if medical_expenses is not None:      self._deductions.medical_expenses = medical_expenses
        if investment_interest is not None:   self._deductions.investment_interest = investment_interest
        if casualty_losses is not None:       self._deductions.casualty_losses = casualty_losses
        if notes is not None:                 self._deductions.notes = notes
        self._results.clear()
        return self

    def set_credits(
        self,
        child_tax_credit_children: int = None,
        child_care_expenses: float = None,
        child_care_dependents: int = None,
        education_credit: float = None,
        retirement_savings_credit: float = None,
        ev_credit: float = None,
        other_credits: float = None,
        notes: str = None,
    ) -> "TaxCalculator":
        if child_tax_credit_children is not None: self._credits.child_tax_credit_children = child_tax_credit_children
        if child_care_expenses is not None:       self._credits.child_care_expenses = child_care_expenses
        if child_care_dependents is not None:     self._credits.child_care_dependents = child_care_dependents
        if education_credit is not None:          self._credits.education_credit = education_credit
        if retirement_savings_credit is not None: self._credits.retirement_savings_credit = retirement_savings_credit
        if ev_credit is not None:                 self._credits.ev_credit = ev_credit
        if other_credits is not None:             self._credits.other_credits = other_credits
        if notes is not None:                     self._credits.notes = notes
        self._results.clear()
        return self

    def set_withholding(
        self,
        federal: float = 0.0,
        estimated_payments: float = 0.0,
    ) -> "TaxCalculator":
        """Federal tax withheld (W-2 Box 2) + any quarterly estimated payments."""
        self._federal_withholding = federal
        self._estimated_payments = estimated_payments
        self._results.clear()
        return self

    def set_filing_status(self, status: str) -> "TaxCalculator":
        self.filing_status = status
        self._results.clear()
        return self

    # ── Main Calculation ──────────────────────────────────────────────────────

    def calculate(self, year: int = None) -> TaxResult:
        """
        Calculate taxes for the given year using the stored entries.
        Same entries, different year rules. Results are cached per year.
        """
        yr = year or self.default_year

        if yr in self._results:
            return self._results[yr]

        rules = get_year(yr)
        inc = self._income
        ded = self._deductions
        cred = self._credits
        status = rules._normalize_status(self.filing_status)
        result = TaxResult(
            year=yr,
            filing_status=self.filing_status,
            is_projected=rules.rules.is_projected,
            projection_warning=rules.rules.projection_notes if rules.rules.is_projected else "",
        )

        # ── Step 1: Gross Income ──────────────────────────────────────────────
        se_income = inc.freelance + inc.business_net
        gross = (
            inc.w2 + se_income + inc.interest
            + inc.ordinary_dividends + inc.st_capital_gains
            + inc.lt_capital_gains + inc.rental_net
            + (inc.social_security * 0.85)  # simplified: 85% taxable
            + inc.pension_annuity + inc.ira_distribution + inc.other
        )
        result.gross_income = round(gross, 2)

        # ── Step 2: Self-Employment Tax ───────────────────────────────────────
        se_details = rules.calculate_se_tax(se_income)
        result.se_tax_total = se_details["total_se_tax"]
        result.se_tax_deduction = se_details["deductible_half"]

        # ── Step 3: Above-the-Line Deductions → AGI ──────────────────────────
        student_loan_cap = min(ded.student_loan_interest, 2_500.0)
        educator_cap = min(ded.educator_expenses, 300.0)
        above_line = (
            ded.ira_contribution
            + student_loan_cap
            + ded.hsa_contribution
            + ded.self_employed_health_ins
            + educator_cap
            + ded.alimony_paid
            + result.se_tax_deduction
        )
        result.above_the_line_total = round(above_line, 2)
        result.agi = round(max(0.0, gross - above_line), 2)

        # ── Step 4: Itemized vs Standard Deduction ────────────────────────────
        # SALT cap (year-specific)
        salt_raw = ded.state_income_tax + ded.property_tax
        salt_capped = (
            min(salt_raw, rules.rules.salt_cap)
            if rules.rules.salt_cap != float("inf")
            else salt_raw
        )
        # Medical expenses: only the amount exceeding 7.5% of AGI
        medical_over_floor = max(0.0, ded.medical_expenses - (result.agi * 0.075))

        itemized = (
            salt_capped
            + ded.mortgage_interest
            + ded.points_paid
            + ded.charity_cash
            + ded.charity_noncash
            + medical_over_floor
            + ded.investment_interest
            + ded.casualty_losses
            + ded.mortgage_insurance
        )
        result.itemized_deductions = round(itemized, 2)
        result.standard_deduction = rules.get_standard_deduction(status)

        if itemized > result.standard_deduction:
            result.deduction_used = "itemized"
            result.deduction_amount = result.itemized_deductions
        else:
            result.deduction_used = "standard"
            result.deduction_amount = result.standard_deduction

        # ── Step 5: Personal Exemptions (2026 projected) ──────────────────────
        num_exemptions = 1
        if status in ("mfj", "qss"):
            num_exemptions = 2
        num_exemptions += self.num_dependents
        personal_exemptions = rules.rules.personal_exemption * num_exemptions
        result.personal_exemptions = round(personal_exemptions, 2)

        # ── Step 6: QBI Deduction ─────────────────────────────────────────────
        result.qbi_deduction = rules.calculate_qbi(se_income)

        # ── Step 7: Taxable Income ────────────────────────────────────────────
        taxable = max(
            0.0,
            result.agi
            - result.deduction_amount
            - result.personal_exemptions
            - result.qbi_deduction
        )
        # Separate qualified dividends + LT gains from ordinary income
        # (they get preferential rates)
        preferential = inc.qualified_dividends + inc.lt_capital_gains
        ordinary_taxable = max(0.0, taxable - preferential)
        result.taxable_income = round(taxable, 2)

        # ── Step 8: Ordinary Income Tax ───────────────────────────────────────
        ordinary_tax, bracket_detail = rules.calculate_brackets(ordinary_taxable, status)
        result.ordinary_tax = ordinary_tax
        result.bracket_detail = bracket_detail

        # ── Step 9: Long-Term Capital Gains Tax ───────────────────────────────
        if preferential > 0:
            result.lt_cap_gains_tax = rules.calculate_lt_cap_gains_tax(
                preferential, ordinary_taxable, status
            )

        # ── Step 10: Total Tax Before Credits ─────────────────────────────────
        result.total_tax_before_credits = round(
            result.ordinary_tax + result.lt_cap_gains_tax + result.se_tax_total, 2
        )

        # ── Step 11: Credits ──────────────────────────────────────────────────
        ctc_detail = rules.calculate_child_tax_credit(
            cred.child_tax_credit_children, result.agi, status
        )
        result.child_tax_credit = ctc_detail["credit_after_phaseout"]
        result.other_credits_total = (
            cred.education_credit
            + cred.retirement_savings_credit
            + cred.ev_credit
            + cred.other_credits
        )
        # Child care credit (simplified Form 2441)
        if cred.child_care_expenses > 0:
            max_care = 3_000.0 if cred.child_care_dependents == 1 else 6_000.0
            eligible = min(cred.child_care_expenses, max_care)
            result.other_credits_total += round(eligible * 0.20, 2)  # simplified 20%

        result.total_credits = round(
            result.child_tax_credit + result.other_credits_total, 2
        )

        # ── Step 12: Final Tax & Refund ───────────────────────────────────────
        result.total_tax = round(
            max(0.0, result.total_tax_before_credits - result.total_credits), 2
        )
        result.federal_withholding = self._federal_withholding
        result.estimated_payments = self._estimated_payments
        payments = self._federal_withholding + self._estimated_payments
        result.refund_or_owed = round(payments - result.total_tax, 2)

        # ── Step 13: Rates ────────────────────────────────────────────────────
        if gross > 0:
            result.effective_rate = round(result.total_tax / gross, 4)
        if bracket_detail:
            result.marginal_rate = bracket_detail[-1].bracket_rate

        self._results[yr] = result
        return result

    # ── Multi-Year Compare ────────────────────────────────────────────────────

    def compare_years(self, years: List[int] = None) -> str:
        """Calculate all years and print a side-by-side comparison."""
        yrs = years or [2024, 2025, 2026]
        results = {y: self.calculate(y) for y in yrs}

        headers = ["Metric"] + [str(y) + (" ⚠️" if results[y].is_projected else "") for y in yrs]
        rows = [
            ("Gross Income",       [f"${results[y].gross_income:,.0f}" for y in yrs]),
            ("AGI",                [f"${results[y].agi:,.0f}" for y in yrs]),
            ("Deduction Used",     [results[y].deduction_used for y in yrs]),
            ("Deduction Amount",   [f"${results[y].deduction_amount:,.0f}" for y in yrs]),
            ("QBI Deduction",      [f"${results[y].qbi_deduction:,.0f}" for y in yrs]),
            ("Taxable Income",     [f"${results[y].taxable_income:,.0f}" for y in yrs]),
            ("Ordinary Tax",       [f"${results[y].ordinary_tax:,.0f}" for y in yrs]),
            ("SE Tax",             [f"${results[y].se_tax_total:,.0f}" for y in yrs]),
            ("Total Tax",          [f"${results[y].total_tax:,.0f}" for y in yrs]),
            ("Credits",            [f"${results[y].total_credits:,.0f}" for y in yrs]),
            ("Refund / (Owed)",    [f"${results[y].refund_or_owed:,.0f}" for y in yrs]),
            ("Effective Rate",     [f"{results[y].effective_rate*100:.2f}%" for y in yrs]),
            ("Marginal Rate",      [f"{results[y].marginal_rate*100:.1f}%" for y in yrs]),
        ]

        col_w = 18
        line = "─" * (col_w * (len(yrs) + 1) + len(yrs))
        out = [line]
        out.append("  ".join(h.ljust(col_w) for h in headers))
        out.append(line)
        for label, vals in rows:
            out.append("  ".join([label.ljust(col_w)] + [v.ljust(col_w) for v in vals]))
        out.append(line)
        if any(results[y].is_projected for y in yrs):
            out.append("⚠️  2026 values are TCJA-sunset projections — verify before use.")
        return "\n".join(out)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_json(self, year: int = None) -> str:
        """Export result as JSON for AI consumption or storage."""
        yr = year or self.default_year
        result = self.calculate(yr)
        return json.dumps(result.to_dict(), indent=2, default=str)

    def export_entries(self) -> dict:
        """Export all current entries as a dict (for saving state)."""
        return {
            "filing_status": self.filing_status,
            "taxpayer_age": self.taxpayer_age,
            "num_dependents": self.num_dependents,
            "default_year": self.default_year,
            "income": asdict(self._income),
            "deductions": asdict(self._deductions),
            "credits": asdict(self._credits),
            "federal_withholding": self._federal_withholding,
            "estimated_payments": self._estimated_payments,
        }

    @classmethod
    def from_entries(cls, data: dict) -> "TaxCalculator":
        """Restore a calculator from exported entries dict."""
        calc = cls(
            filing_status=data.get("filing_status", "single"),
            taxpayer_age=data.get("taxpayer_age", 40),
            num_dependents=data.get("num_dependents", 0),
            default_year=data.get("default_year", 2025),
        )
        if "income" in data:
            calc._income = IncomeEntries(**data["income"])
        if "deductions" in data:
            calc._deductions = DeductionEntries(**data["deductions"])
        if "credits" in data:
            calc._credits = CreditEntries(**data["credits"])
        calc._federal_withholding = data.get("federal_withholding", 0.0)
        calc._estimated_payments = data.get("estimated_payments", 0.0)
        return calc
