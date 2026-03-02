"""
schedule_c.py — Schedule C (Profit or Loss from Business)
===========================================================
For sole proprietors and single-member LLCs.
Computes net profit/loss that feeds into TaxCalculator as business_net.

Usage:
    sc = ScheduleC(business_name="My Consulting")
    sc.set_revenue(gross_receipts=95000, returns_allowances=1500)
    sc.set_expenses(
        advertising=2000,
        car_and_truck=4500,
        office=1200,
        utilities=600,
        software=1800,
        home_office_sqft=200, home_total_sqft=1500,
        home_expenses=18000,
    )
    net = sc.calculate()
    print(sc.summary())

    # Feed into main calculator:
    calc.set_income(business_net=net)
"""

from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class ScheduleC:
    """
    Schedule C for a single business / trade.
    All dollar amounts are for the tax year being calculated.
    """

    business_name: str = "My Business"
    business_code: str = ""           # IRS principal business code
    ein: str = ""                     # Employer ID (if any)
    accounting_method: str = "cash"   # "cash" or "accrual"
    materially_participates: bool = True

    # ── PART I: INCOME ────────────────────────────────────────────────────────

    gross_receipts: float = 0.0       # Line 1: total revenue received
    returns_allowances: float = 0.0   # Line 2: refunds issued
    cogs: float = 0.0                 # Line 4: cost of goods sold (Part III)
    other_income: float = 0.0         # Line 6: misc business income

    # ── PART II: EXPENSES ─────────────────────────────────────────────────────

    advertising:            float = 0.0   # Line 8
    car_and_truck:          float = 0.0   # Line 9 (actual or standard mileage)
    commissions_fees:       float = 0.0   # Line 10
    contract_labor:         float = 0.0   # Line 11 (1099-NEC paid out)
    depletion:              float = 0.0   # Line 12
    depreciation_179:       float = 0.0   # Line 13 (Form 4562)
    employee_benefits:      float = 0.0   # Line 14
    insurance:              float = 0.0   # Line 15 (not health ins — see above-line)
    mortgage_interest_bus:  float = 0.0   # Line 16a
    other_interest:         float = 0.0   # Line 16b
    legal_professional:     float = 0.0   # Line 17
    office:                 float = 0.0   # Line 18
    pension_profit_sharing: float = 0.0   # Line 19
    rent_vehicles_equip:    float = 0.0   # Line 20a
    rent_other_property:    float = 0.0   # Line 20b
    repairs_maintenance:    float = 0.0   # Line 21
    supplies:               float = 0.0   # Line 22
    taxes_licenses:         float = 0.0   # Line 23
    travel:                 float = 0.0   # Line 24a
    meals:                  float = 0.0   # Line 24b (enter 100%, 50% applied auto)
    utilities:              float = 0.0   # Line 25
    wages:                  float = 0.0   # Line 26 (employees, not self)
    software_subscriptions: float = 0.0   # Line 27a (other expenses)
    phone_internet:         float = 0.0   # Line 27a (business %)
    education_training:     float = 0.0   # Line 27a
    other_expenses:         float = 0.0   # Line 27a catch-all

    # ── HOME OFFICE (Form 8829 simplified here) ───────────────────────────────
    # Only if you use part of your home regularly and exclusively for business.
    home_office_sqft: float = 0.0         # square footage of office space
    home_total_sqft:  float = 0.0         # total square footage of home
    home_expenses:    float = 0.0         # total home expenses (rent/mortgage+util)
    # Alternatively use IRS simplified method: $5/sqft, max 300 sqft
    use_simplified_home_office: bool = False

    # ── MILEAGE TRACKING ─────────────────────────────────────────────────────
    business_miles:  float = 0.0
    commute_miles:   float = 0.0
    total_miles:     float = 0.0
    mileage_rate:    float = 0.70          # 2025 rate; pass year-specific rate

    # ── COMPUTED (set after calculate()) ─────────────────────────────────────
    _gross_profit:      float = field(default=0.0, init=False, repr=False)
    _total_expenses:    float = field(default=0.0, init=False, repr=False)
    _home_office_ded:   float = field(default=0.0, init=False, repr=False)
    _net_profit:        float = field(default=0.0, init=False, repr=False)
    _calculated:        bool  = field(default=False, init=False, repr=False)

    def calculate(self) -> float:
        """
        Compute net profit/loss. Returns the value to pass to
        TaxCalculator.set_income(business_net=...).
        """

        # ── Gross Profit ──────────────────────────────────────────────────────
        gross_income = (self.gross_receipts - self.returns_allowances
                        - self.cogs + self.other_income)
        self._gross_profit = round(gross_income, 2)

        # ── Home Office ───────────────────────────────────────────────────────
        if self.use_simplified_home_office and self.home_office_sqft > 0:
            # IRS simplified method: $5/sqft, max 300 sqft
            self._home_office_ded = min(self.home_office_sqft, 300) * 5.0
        elif self.home_office_sqft > 0 and self.home_total_sqft > 0:
            # Regular method: business % of home expenses
            business_pct = self.home_office_sqft / self.home_total_sqft
            self._home_office_ded = round(self.home_expenses * business_pct, 2)
        else:
            self._home_office_ded = 0.0

        # ── Meals (50% deductible) ────────────────────────────────────────────
        meals_deductible = self.meals * 0.50

        # ── Mileage (if using standard rate instead of actual car_and_truck) ──
        if self.business_miles > 0 and self.car_and_truck == 0:
            self.car_and_truck = round(self.business_miles * self.mileage_rate, 2)

        # ── Total Expenses ────────────────────────────────────────────────────
        total_exp = (
            self.advertising
            + self.car_and_truck
            + self.commissions_fees
            + self.contract_labor
            + self.depletion
            + self.depreciation_179
            + self.employee_benefits
            + self.insurance
            + self.mortgage_interest_bus
            + self.other_interest
            + self.legal_professional
            + self.office
            + self.pension_profit_sharing
            + self.rent_vehicles_equip
            + self.rent_other_property
            + self.repairs_maintenance
            + self.supplies
            + self.taxes_licenses
            + self.travel
            + meals_deductible          # 50% of meals
            + self.utilities
            + self.wages
            + self.software_subscriptions
            + self.phone_internet
            + self.education_training
            + self.other_expenses
            + self._home_office_ded
        )
        self._total_expenses = round(total_exp, 2)

        # ── Net Profit / Loss ─────────────────────────────────────────────────
        self._net_profit = round(self._gross_profit - self._total_expenses, 2)
        self._calculated = True
        return self._net_profit

    def summary(self) -> str:
        """Human-readable Schedule C summary."""
        if not self._calculated:
            self.calculate()

        lines = [
            f"{'═'*55}",
            f"  SCHEDULE C — {self.business_name}",
            f"{'═'*55}",
            f"  PART I: INCOME",
            f"  Gross Receipts:         ${self.gross_receipts:>12,.2f}",
            f"  Returns/Allowances:    -${self.returns_allowances:>12,.2f}",
            f"  Cost of Goods Sold:    -${self.cogs:>12,.2f}",
            f"  Other Income:          +${self.other_income:>12,.2f}",
            f"  ─────────────────────────────────────────────",
            f"  Gross Profit:           ${self._gross_profit:>12,.2f}",
            f"",
            f"  PART II: EXPENSES",
        ]

        expense_items = [
            ("Advertising",            self.advertising),
            ("Car & Truck",            self.car_and_truck),
            ("Commissions & Fees",     self.commissions_fees),
            ("Contract Labor",         self.contract_labor),
            ("Depreciation/Sec 179",   self.depreciation_179),
            ("Insurance",              self.insurance),
            ("Interest",               self.mortgage_interest_bus + self.other_interest),
            ("Legal & Professional",   self.legal_professional),
            ("Office Expenses",        self.office),
            ("Rent (equip)",           self.rent_vehicles_equip),
            ("Rent (property)",        self.rent_other_property),
            ("Repairs & Maintenance",  self.repairs_maintenance),
            ("Supplies",               self.supplies),
            ("Taxes & Licenses",       self.taxes_licenses),
            ("Travel",                 self.travel),
            ("Meals (50% applied)",    self.meals * 0.50),
            ("Utilities",              self.utilities),
            ("Wages",                  self.wages),
            ("Software/Subscriptions", self.software_subscriptions),
            ("Phone & Internet",       self.phone_internet),
            ("Education/Training",     self.education_training),
            ("Home Office",            self._home_office_ded),
            ("Other Expenses",         self.other_expenses),
        ]

        for label, amount in expense_items:
            if amount > 0:
                lines.append(f"  {label:<28} ${amount:>12,.2f}")

        lines += [
            f"  ─────────────────────────────────────────────",
            f"  Total Expenses:         ${self._total_expenses:>12,.2f}",
            f"{'═'*55}",
            f"  NET PROFIT / (LOSS):    ${self._net_profit:>12,.2f}",
            f"{'═'*55}",
        ]

        if self._net_profit < 0:
            lines.append("  ⚠️  Net LOSS — passive activity rules may limit deductibility")
        if self._home_office_ded > 0:
            lines.append(f"  Home office: {self.home_office_sqft:.0f} of "
                         f"{self.home_total_sqft:.0f} sqft = "
                         f"{self.home_office_sqft/self.home_total_sqft*100:.1f}%")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        if not self._calculated:
            self.calculate()
        return {
            "business_name": self.business_name,
            "gross_profit": self._gross_profit,
            "total_expenses": self._total_expenses,
            "home_office_deduction": self._home_office_ded,
            "net_profit": self._net_profit,
        }
