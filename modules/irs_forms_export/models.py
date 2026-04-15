"""
models.py — Pydantic schemas for the IRS Forms Export module

Ingests structured data from the Accountant agent and provides a validated
TaxReturn object for downstream processing.

Tax years supported: 2024, 2025
State: Florida — federal only, no state income tax
"""

from __future__ import annotations
from decimal import Decimal
from typing import List, Literal, Optional, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class FilingStatus(str, Enum):
    SINGLE              = "single"
    MARRIED_JOINTLY     = "mfj"
    MARRIED_SEPARATELY  = "mfs"
    HEAD_OF_HOUSEHOLD   = "hoh"
    QUALIFYING_SURVIVING= "qss"

class Form1099Type(str, Enum):
    NEC  = "NEC"   # Nonemployee compensation → Schedule C
    MISC = "MISC"  # Miscellaneous income
    INT  = "INT"   # Interest income
    DIV  = "DIV"   # Dividend income
    K    = "K"     # Partnership/S-Corp (K-1)
    R    = "R"     # Retirement/pension (1099-R)

class DeductionMethod(str, Enum):
    STANDARD = "standard"
    ITEMIZED = "itemized"

class DepreciationType(str, Enum):
    SECTION_179 = "section_179"
    MACRS       = "macrs"
    BONUS       = "bonus"
    STRAIGHT_LINE = "straight_line"


# ─── Sub-models ───────────────────────────────────────────────────────────────

class W2Entry(BaseModel):
    """Single W-2 form entry."""
    employer_name:       str
    employer_ein:        Optional[str] = None
    box1_wages:          float = Field(ge=0, description="Box 1: Wages, tips, other compensation")
    box2_federal_withheld: float = Field(ge=0, description="Box 2: Federal income tax withheld")
    box3_ss_wages:       float = Field(ge=0, default=0.0, description="Box 3: Social security wages")
    box4_ss_withheld:    float = Field(ge=0, default=0.0, description="Box 4: Social security tax withheld")
    box5_medicare_wages: float = Field(ge=0, default=0.0, description="Box 5: Medicare wages and tips")
    box6_medicare_withheld: float = Field(ge=0, default=0.0, description="Box 6: Medicare tax withheld")
    box12_codes:         Dict[str, float] = Field(default_factory=dict, description="Box 12 entries {code: amount}")
    box13_retirement_plan: bool = False
    state_wages:         float = 0.0   # Florida: informational only
    state_withheld:      float = 0.0   # Florida: should be 0


class Form1099Entry(BaseModel):
    """Single 1099 form entry — covers NEC, MISC, INT, DIV."""
    payer_name:    str
    payer_tin:     Optional[str] = None
    form_type:     Form1099Type
    amount:        float = Field(ge=0)
    # INT-specific
    early_withdrawal_penalty: float = 0.0
    # DIV-specific
    qualified_dividends:      float = 0.0
    total_capital_gains:      float = 0.0
    # NEC/MISC-specific
    federal_withheld:         float = 0.0
    state_withheld:           float = 0.0  # Florida: should be 0
    # NEC routing
    flows_to_schedule_c:      bool = True  # NEC always → Sched C

    @model_validator(mode="after")
    def nec_flows_to_schedule_c(self) -> "Form1099Entry":
        if self.form_type == Form1099Type.NEC:
            self.flows_to_schedule_c = True
        return self


class ScheduleCExpenses(BaseModel):
    """Schedule C Part II expenses — line numbers match IRS form."""
    advertising:              float = 0.0   # Line 8
    car_and_truck:            float = 0.0   # Line 9  (mileage OR actual)
    commissions_fees:         float = 0.0   # Line 10
    contract_labor:           float = 0.0   # Line 11
    depletion:                float = 0.0   # Line 12
    depreciation_179:         float = 0.0   # Line 13
    employee_benefits:        float = 0.0   # Line 14
    insurance:                float = 0.0   # Line 15
    mortgage_interest_bank:   float = 0.0   # Line 16a
    other_interest:           float = 0.0   # Line 16b
    legal_professional:       float = 0.0   # Line 17
    office:                   float = 0.0   # Line 18
    pension_profit_sharing:   float = 0.0   # Line 19
    rent_vehicles_equipment:  float = 0.0   # Line 20a
    rent_other_property:      float = 0.0   # Line 20b
    repairs_maintenance:      float = 0.0   # Line 21
    supplies:                 float = 0.0   # Line 22
    taxes_licenses:           float = 0.0   # Line 23
    travel:                   float = 0.0   # Line 24a
    meals:                    float = 0.0   # Line 24b (enter full amt; 50% applied)
    utilities:                float = 0.0   # Line 25
    wages:                    float = 0.0   # Line 26
    # Line 27a — Other expenses (itemized)
    phone_internet:           float = 0.0
    software_subscriptions:   float = 0.0
    education_training:       float = 0.0
    other_expenses:           float = 0.0

    @property
    def meals_deductible(self) -> float:
        """50% meals limitation per IRC §274(n)."""
        return self.meals * 0.50

    @property
    def other_total(self) -> float:
        return (self.phone_internet + self.software_subscriptions
                + self.education_training + self.other_expenses)

    @property
    def total(self) -> float:
        return (
            self.advertising + self.car_and_truck + self.commissions_fees
            + self.contract_labor + self.depletion + self.depreciation_179
            + self.employee_benefits + self.insurance
            + self.mortgage_interest_bank + self.other_interest
            + self.legal_professional + self.office + self.pension_profit_sharing
            + self.rent_vehicles_equipment + self.rent_other_property
            + self.repairs_maintenance + self.supplies + self.taxes_licenses
            + self.travel + self.meals_deductible + self.utilities + self.wages
            + self.other_total
        )


class SelfEmploymentIncome(BaseModel):
    """Schedule C data for a single business / trade."""
    business_name:   str = "Self-Employment"
    business_code:   str = "492000"  # Couriers/messengers (Amazon Flex default)
    gross_receipts:  float = Field(ge=0, description="Line 1: Total revenue")
    returns_allowances: float = 0.0
    cogs:            float = 0.0
    other_income:    float = 0.0
    expenses:        ScheduleCExpenses = Field(default_factory=ScheduleCExpenses)

    @property
    def gross_income(self) -> float:
        return self.gross_receipts - self.returns_allowances - self.cogs + self.other_income

    @property
    def net_profit(self) -> float:
        return self.gross_income - self.expenses.total


class MileageRecord(BaseModel):
    """Business mileage deduction data."""
    total_business_miles: float = Field(ge=0)
    irs_rate_per_mile:    float = Field(gt=0, description="IRS standard mileage rate for tax year")
    # Computed or overridden
    computed_deduction:   Optional[float] = None
    commute_miles:        float = 0.0  # Non-deductible commute miles (informational)

    @property
    def deduction_amount(self) -> float:
        if self.computed_deduction is not None:
            return self.computed_deduction
        return round(self.total_business_miles * self.irs_rate_per_mile, 2)


class DepreciationAsset(BaseModel):
    """Single depreciable asset."""
    description:         str
    purchase_date:       str   # ISO date YYYY-MM-DD
    cost_basis:          float = Field(ge=0)
    depreciation_type:   DepreciationType = DepreciationType.SECTION_179
    section_179_amount:  float = 0.0
    bonus_depreciation:  float = 0.0
    recovery_period:     int   = 5   # MACRS years (5yr for vehicles, computers)
    business_use_pct:    float = Field(default=1.0, ge=0, le=1.0)


class DeductionData(BaseModel):
    """Itemized or standard deduction package."""
    method:                DeductionMethod = DeductionMethod.STANDARD
    # Itemized Schedule A amounts (only used when method=itemized)
    mortgage_interest:     float = 0.0
    state_local_taxes:     float = 0.0   # SALT — Florida: property tax only
    charitable_cash:       float = 0.0
    charitable_noncash:    float = 0.0
    medical_expenses:      float = 0.0   # Only amount > 7.5% AGI
    other_itemized:        float = 0.0

    @property
    def itemized_total(self) -> float:
        return (self.mortgage_interest + self.state_local_taxes
                + self.charitable_cash + self.charitable_noncash
                + self.medical_expenses + self.other_itemized)


class CreditData(BaseModel):
    """Applicable tax credits."""
    child_tax_credit:         float = 0.0   # $2,000/child (2024)
    additional_child_tax:     float = 0.0   # Refundable portion
    earned_income_credit:     float = 0.0   # EIC — computed based on income
    child_dependent_care:     float = 0.0   # Form 2441
    education_american_opp:   float = 0.0   # AOC — $2,500 max
    education_lifetime_learn: float = 0.0   # LLC — $2,000 max
    retirement_saver:         float = 0.0   # Form 8880
    ev_vehicle_credit:        float = 0.0   # Form 8936
    other_credits:            float = 0.0

    @property
    def total(self) -> float:
        return (self.child_tax_credit + self.additional_child_tax
                + self.earned_income_credit + self.child_dependent_care
                + self.education_american_opp + self.education_lifetime_learn
                + self.retirement_saver + self.ev_vehicle_credit
                + self.other_credits)


class DependentInfo(BaseModel):
    """Single dependent entry."""
    name:            str
    relationship:    str
    birth_year:      int
    ssn_last4:       str = "XXXX"  # Masked
    months_in_home:  int = 12
    qualifying_child: bool = True


class PersonalInfo(BaseModel):
    """Taxpayer personal/filing information."""
    first_name:          str
    last_name:           str
    ssn_last4:           str = "XXXX"   # Masked — never store full SSN
    filing_status:       FilingStatus = FilingStatus.SINGLE
    address_line1:       str = ""
    address_city:        str = ""
    address_state:       str = "FL"
    address_zip:         str = ""
    dependents:          List[DependentInfo] = Field(default_factory=list)
    over_65:             bool = False
    blind:               bool = False
    spouse_over_65:      bool = False
    spouse_blind:        bool = False


# ─── Root TaxReturn model ─────────────────────────────────────────────────────

class TaxReturn(BaseModel):
    """
    Complete tax return data structure.
    Ingested from accountant agent dict via load_accountant_data().
    """
    tax_year:              int = Field(ge=2024, le=2026)
    personal_info:         PersonalInfo
    w2_income:             List[W2Entry]            = Field(default_factory=list)
    form1099_income:       List[Form1099Entry]       = Field(default_factory=list)
    self_employment:       List[SelfEmploymentIncome] = Field(default_factory=list)
    mileage:               Optional[MileageRecord]   = None
    depreciation:          List[DepreciationAsset]   = Field(default_factory=list)
    deductions:            DeductionData             = Field(default_factory=DeductionData)
    credits:               CreditData                = Field(default_factory=CreditData)

    # Computed fields (populated by validator)
    _total_w2_wages:       float = 0.0
    _total_1099_nec:       float = 0.0
    _total_se_net:         float = 0.0
    _se_tax:               float = 0.0
    _se_deduction:         float = 0.0
    _qbi_deduction:        float = 0.0
    _agi:                  float = 0.0

    @property
    def total_w2_wages(self) -> float:
        return sum(w.box1_wages for w in self.w2_income)

    @property
    def total_federal_withheld(self) -> float:
        w2_wh = sum(w.box2_federal_withheld for w in self.w2_income)
        f1099_wh = sum(f.federal_withheld for f in self.form1099_income)
        return w2_wh + f1099_wh

    @property
    def total_1099_nec(self) -> float:
        return sum(f.amount for f in self.form1099_income
                   if f.form_type == Form1099Type.NEC)

    @property
    def total_1099_int(self) -> float:
        return sum(f.amount for f in self.form1099_income
                   if f.form_type == Form1099Type.INT)

    @property
    def total_1099_div(self) -> float:
        return sum(f.amount for f in self.form1099_income
                   if f.form_type == Form1099Type.DIV)

    @property
    def total_se_gross(self) -> float:
        return sum(se.gross_receipts for se in self.self_employment)

    @property
    def total_se_net(self) -> float:
        return sum(se.net_profit for se in self.self_employment)

    @property
    def se_tax(self) -> float:
        """Self-employment tax = 15.3% on 92.35% of net SE income."""
        net = max(self.total_se_net, 0)
        return round(net * 0.9235 * 0.153, 2)

    @property
    def se_deduction(self) -> float:
        """Above-the-line deduction: 50% of SE tax."""
        return round(self.se_tax * 0.50, 2)

    @property
    def qbi_deduction(self) -> float:
        """
        Section 199A QBI deduction — 20% of qualified business income.
        Simplified: no W-2 wage / UBIA limitation for income below threshold.
        2024 threshold: $191,950 single / $383,900 MFJ
        2025 threshold: $197,300 single / $394,600 MFJ
        """
        thresholds = {
            2024: {"single": 191_950, "mfj": 383_900, "mfs": 191_950, "hoh": 191_950, "qss": 383_900},
            2025: {"single": 197_300, "mfj": 394_600, "mfs": 197_300, "hoh": 197_300, "qss": 394_600},
        }
        status = self.personal_info.filing_status.value
        threshold = thresholds.get(self.tax_year, thresholds[2024]).get(status, 191_950)
        qbi = max(self.total_se_net - self.se_deduction, 0)
        if self.agi <= threshold:
            return round(qbi * 0.20, 2)
        # Phaseout: simplified — above threshold QBI deduction may be limited
        # Full calculation requires W-2 wages paid; flag for user review
        return round(qbi * 0.20, 2)  # Conservative estimate; validator will flag

    @property
    def agi(self) -> float:
        """Approximate AGI (above-the-line deductions applied).

        1099-NEC that flows to Schedule C is already included in total_se_net
        (as gross_receipts). Only count NEC that does NOT go to Schedule C
        to avoid double-counting.
        """
        nec_not_on_sch_c = sum(
            f.amount for f in self.form1099_income
            if f.form_type == Form1099Type.NEC and not f.flows_to_schedule_c
        )
        gross = (self.total_w2_wages + nec_not_on_sch_c
                 + self.total_1099_int + self.total_1099_div
                 + self.total_se_net)
        return max(gross - self.se_deduction, 0)

    @field_validator("tax_year")
    @classmethod
    def valid_tax_year(cls, v: int) -> int:
        if v not in (2024, 2025, 2026):
            raise ValueError(f"Unsupported tax year: {v}. Supported: 2024, 2025, 2026")
        return v


class ValidationError(BaseModel):
    """Single validation issue found in a TaxReturn."""
    severity:    Literal["error", "warning", "info"]
    code:        str
    field:       str
    message:     str
    suggestion:  Optional[str] = None


class TurboTaxExport(BaseModel):
    """Ready-to-export TurboTax data package."""
    tax_return:    TaxReturn
    txf_records:   List[Dict[str, Any]]    = Field(default_factory=list)
    tab_records:   List[Dict[str, str]]    = Field(default_factory=list)
    export_notes:  List[str]               = Field(default_factory=list)
