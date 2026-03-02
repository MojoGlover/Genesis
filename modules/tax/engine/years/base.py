"""
base.py — Abstract TaxYear base class
======================================
All year-specific rule sets inherit from this. Defines the interface
the calculator uses so year rules are swappable without changing logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class BracketResult:
    """Tax owed broken down by bracket."""
    bracket_rate: float
    bracket_min: float
    bracket_max: float          # float('inf') for top bracket
    income_in_bracket: float
    tax_in_bracket: float


@dataclass
class YearRules:
    """Container for all year-specific values. Populated by each TaxYear subclass."""

    year: int
    is_projected: bool = False   # True for 2026 — values are estimates
    projection_notes: str = ""

    # ── Standard Deductions ──────────────────────────────────────────────────
    standard_deduction: Dict[str, float] = field(default_factory=dict)
    # keys: "single", "mfj", "mfs", "hoh", "qss"

    # ── Tax Brackets ─────────────────────────────────────────────────────────
    # List of (rate, min_income) tuples, sorted low→high
    # min_income is the bottom of this bracket (taxable income)
    brackets: Dict[str, List[Tuple[float, float]]] = field(default_factory=dict)
    # keys: "single", "mfj", "mfs", "hoh"

    # ── Capital Gains Brackets (Long-Term) ───────────────────────────────────
    # List of (rate, min_income) tuples
    lt_cap_gains_brackets: Dict[str, List[Tuple[float, float]]] = field(default_factory=dict)

    # ── Contribution Limits ──────────────────────────────────────────────────
    contribution_limits: Dict[str, float] = field(default_factory=dict)
    # keys: "401k", "401k_catchup_50", "401k_catchup_60_63", "ira", "ira_catchup",
    #       "hsa_self", "hsa_family", "hsa_catchup_55"

    # ── AMT ──────────────────────────────────────────────────────────────────
    amt_exemption: Dict[str, float] = field(default_factory=dict)
    amt_phaseout_start: Dict[str, float] = field(default_factory=dict)
    amt_rates: List[Tuple[float, float]] = field(default_factory=list)  # (rate, min_amti)

    # ── Credits ──────────────────────────────────────────────────────────────
    child_tax_credit_per_child: float = 0.0
    child_tax_credit_phaseout_start: Dict[str, float] = field(default_factory=dict)
    additional_child_tax_credit_rate: float = 0.15   # refundable portion rate

    # ── Deduction Caps ───────────────────────────────────────────────────────
    salt_cap: float = 10_000.0          # $10k under TCJA; None = no cap
    mortgage_debt_limit: float = 750_000.0

    # ── QBI ──────────────────────────────────────────────────────────────────
    qbi_deduction_rate: float = 0.20
    qbi_available: bool = True          # False in 2026 if TCJA expires

    # ── Personal Exemptions (pre-TCJA / 2026 projected) ──────────────────────
    personal_exemption: float = 0.0     # $0 under TCJA; returns in 2026 if sunset

    # ── SS Wage Base ─────────────────────────────────────────────────────────
    ss_wage_base: float = 0.0

    # ── Standard Mileage ─────────────────────────────────────────────────────
    business_mileage_rate: float = 0.0   # per mile


class TaxYear(ABC):
    """
    Abstract base — each year subclass sets self.rules and overrides
    any methods that need year-specific logic.
    """

    rules: YearRules  # set by subclass __init__

    # ── Bracket Calculation ───────────────────────────────────────────────────

    def calculate_brackets(
        self, taxable_income: float, filing_status: str
    ) -> Tuple[float, List[BracketResult]]:
        """
        Apply marginal brackets to taxable_income.
        Returns (total_ordinary_tax, list_of_bracket_results).
        """
        status = self._normalize_status(filing_status)
        brackets = self.rules.brackets.get(status, self.rules.brackets["single"])

        total_tax = 0.0
        details: List[BracketResult] = []
        remaining = taxable_income

        for i, (rate, bracket_min) in enumerate(brackets):
            # Top of this bracket = bottom of next bracket (or infinity)
            if i + 1 < len(brackets):
                bracket_max = brackets[i + 1][1]
            else:
                bracket_max = float("inf")

            taxable_in_bracket = min(remaining, bracket_max - bracket_min)
            if taxable_in_bracket <= 0:
                continue

            tax_in_bracket = taxable_in_bracket * rate
            total_tax += tax_in_bracket
            details.append(BracketResult(
                bracket_rate=rate,
                bracket_min=bracket_min,
                bracket_max=bracket_max,
                income_in_bracket=taxable_in_bracket,
                tax_in_bracket=tax_in_bracket,
            ))
            remaining -= taxable_in_bracket
            if remaining <= 0:
                break

        return round(total_tax, 2), details

    # ── Standard Deduction ────────────────────────────────────────────────────

    def get_standard_deduction(self, filing_status: str) -> float:
        status = self._normalize_status(filing_status)
        return self.rules.standard_deduction.get(status, 0.0)

    # ── Capital Gains ─────────────────────────────────────────────────────────

    def calculate_lt_cap_gains_tax(
        self, lt_gains: float, taxable_income_before_gains: float, filing_status: str
    ) -> float:
        """
        Long-term capital gains are stacked on top of ordinary income
        to determine which cap-gains rate applies.
        """
        status = self._normalize_status(filing_status)
        brackets = self.rules.lt_cap_gains_brackets.get(
            status, self.rules.lt_cap_gains_brackets.get("single", [])
        )
        if not brackets:
            return 0.0

        # Gains start where ordinary income leaves off
        gains_start = taxable_income_before_gains
        gains_end = gains_start + lt_gains
        total_gains_tax = 0.0
        remaining = lt_gains

        for i, (rate, bracket_min) in enumerate(brackets):
            if i + 1 < len(brackets):
                bracket_max = brackets[i + 1][1]
            else:
                bracket_max = float("inf")

            # Overlap between [gains_start, gains_end] and [bracket_min, bracket_max]
            overlap_start = max(gains_start, bracket_min)
            overlap_end = min(gains_end, bracket_max)
            if overlap_end <= overlap_start:
                continue

            gains_in_bracket = overlap_end - overlap_start
            total_gains_tax += gains_in_bracket * rate
            remaining -= gains_in_bracket

        return round(total_gains_tax, 2)

    # ── SE Tax ────────────────────────────────────────────────────────────────

    def calculate_se_tax(self, net_se_income: float) -> Dict[str, float]:
        """Self-employment tax: 15.3% up to SS wage base, then 2.9%."""
        ss_base = self.rules.ss_wage_base
        ss_rate = 0.124
        medicare_rate = 0.029
        additional_medicare = 0.009   # on SE income over $200k (single) / $250k (MFJ)

        # SE tax applies to 92.35% of net SE income (to match employee experience)
        se_income_subject = net_se_income * 0.9235

        ss_income = min(se_income_subject, ss_base)
        ss_tax = ss_income * ss_rate
        medicare_tax = se_income_subject * medicare_rate

        total_se_tax = round(ss_tax + medicare_tax, 2)
        deductible_half = round(total_se_tax / 2, 2)

        return {
            "se_income_subject": round(se_income_subject, 2),
            "ss_tax": round(ss_tax, 2),
            "medicare_tax": round(medicare_tax, 2),
            "total_se_tax": total_se_tax,
            "deductible_half": deductible_half,      # above-the-line deduction
        }

    # ── QBI Deduction ─────────────────────────────────────────────────────────

    def calculate_qbi(self, net_business_income: float) -> float:
        """20% of QBI — simplified. Does not apply complex W-2/property limits."""
        if not self.rules.qbi_available or net_business_income <= 0:
            return 0.0
        return round(net_business_income * self.rules.qbi_deduction_rate, 2)

    # ── Credits ──────────────────────────────────────────────────────────────

    def calculate_child_tax_credit(
        self, num_children: int, agi: float, filing_status: str
    ) -> Dict[str, float]:
        """Basic child tax credit with phaseout."""
        status = self._normalize_status(filing_status)
        base = num_children * self.rules.child_tax_credit_per_child
        phaseout_start = self.rules.child_tax_credit_phaseout_start.get(status, 200_000)

        if agi > phaseout_start:
            # Reduces by $50 for each $1,000 (or fraction) over threshold
            excess = agi - phaseout_start
            reduction = ((excess // 1_000) + 1) * 50
            base = max(0.0, base - reduction)

        return {
            "base_credit": num_children * self.rules.child_tax_credit_per_child,
            "credit_after_phaseout": round(base, 2),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_status(status: str) -> str:
        """Normalize filing status string to canonical key."""
        mapping = {
            "single": "single",
            "s": "single",
            "mfj": "mfj",
            "married_filing_jointly": "mfj",
            "married filing jointly": "mfj",
            "joint": "mfj",
            "mfs": "mfs",
            "married_filing_separately": "mfs",
            "married filing separately": "mfs",
            "hoh": "hoh",
            "head_of_household": "hoh",
            "head of household": "hoh",
            "qss": "qss",
            "qualifying_surviving_spouse": "qss",
        }
        return mapping.get(status.lower().strip(), "single")

    @abstractmethod
    def get_year(self) -> int:
        """Return the tax year integer."""
        ...
