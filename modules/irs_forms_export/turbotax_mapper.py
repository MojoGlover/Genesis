"""
turbotax_mapper.py — Maps TaxReturn data to TurboTax TXF records

TXF (Tax Exchange Format) v042 specification:
  - First line of file: V042
  - Each record ends with: ^
  - Record fields (one per line):
      A  = account/payer name
      D  = date (MM/DD/YYYY)
      N  = description/name
      C  = category code (maps to IRS form line)
      L  = copy number (1 = first W2, 2 = second W2, etc.)
      $  = dollar amount (positive; negative for losses)
  - Category codes map to specific form lines in TurboTax

Category codes used here (TXF v042 standard):
  W-2:
    C110 = Box 1 Wages
    C111 = Box 2 Federal tax withheld
    C112 = Box 4 SS tax withheld
    C113 = Box 6 Medicare tax withheld
  1099-INT:
    C505 = Box 1 Interest income
  1099-DIV:
    C516 = Box 1a Ordinary dividends
    C517 = Box 1b Qualified dividends
  1099-NEC → Schedule C:
    C631 = Nonemployee compensation
  Schedule C:
    C650 = Gross receipts/sales
    C651 = Cost of goods sold
    C660 = Advertising
    C661 = Car and truck expenses
    C662 = Commissions and fees
    C663 = Contract labor
    C664 = Depletion
    C665 = Depreciation (Form 4562)
    C666 = Employee benefit programs
    C667 = Insurance (other than health)
    C668 = Mortgage interest (bank)
    C669 = Other interest
    C670 = Legal and professional
    C671 = Office expense
    C672 = Pension/profit sharing
    C673 = Rent/lease vehicles and equipment
    C674 = Rent/lease other business property
    C675 = Repairs and maintenance
    C676 = Supplies
    C677 = Taxes and licenses
    C678 = Travel
    C679 = Deductible meals (50%)
    C680 = Utilities
    C681 = Wages (paid to employees)
    C682 = Other expenses
  SE tax:
    C290 = Deductible part of SE tax (Schedule 1)
  QBI:
    C293 = Qualified business income deduction
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import date

from .models import (
    TaxReturn, TurboTaxExport, Form1099Type,
    DeductionMethod, DepreciationType
)


def map_to_turbotax(tax_return: TaxReturn) -> TurboTaxExport:
    """
    Convert TaxReturn to TurboTaxExport with both TXF records and
    tab-delimited fallback records.
    """
    txf_records: List[Dict[str, Any]] = []
    tab_records: List[Dict[str, str]] = []
    notes: List[str] = []

    # ── W-2 income ────────────────────────────────────────────────────────────
    for copy_num, w2 in enumerate(tax_return.w2_income, start=1):
        if w2.box1_wages > 0:
            txf_records.append(_txf(
                category="C110", copy=copy_num,
                amount=w2.box1_wages, name=w2.employer_name,
                description=f"W-2 Wages - {w2.employer_name}"
            ))
            tab_records.append({"field": f"Form1040_W2Wages_{copy_num}",
                                 "value": str(w2.box1_wages)})

        if w2.box2_federal_withheld > 0:
            txf_records.append(_txf(
                category="C111", copy=copy_num,
                amount=w2.box2_federal_withheld, name=w2.employer_name,
                description=f"W-2 Federal Withheld - {w2.employer_name}"
            ))
            tab_records.append({"field": f"Form1040_W2FedWithheld_{copy_num}",
                                 "value": str(w2.box2_federal_withheld)})

        if w2.box4_ss_withheld > 0:
            txf_records.append(_txf(
                category="C112", copy=copy_num,
                amount=w2.box4_ss_withheld, name=w2.employer_name,
                description=f"W-2 SS Withheld - {w2.employer_name}"
            ))

        if w2.box6_medicare_withheld > 0:
            txf_records.append(_txf(
                category="C113", copy=copy_num,
                amount=w2.box6_medicare_withheld, name=w2.employer_name,
                description=f"W-2 Medicare Withheld - {w2.employer_name}"
            ))

    # ── 1099 income ───────────────────────────────────────────────────────────
    nec_copy = 1
    int_copy = 1
    div_copy = 1

    for f1099 in tax_return.form1099_income:
        if f1099.form_type == Form1099Type.NEC:
            txf_records.append(_txf(
                category="C631", copy=nec_copy,
                amount=f1099.amount, name=f1099.payer_name,
                description=f"1099-NEC - {f1099.payer_name} (→ Schedule C)"
            ))
            tab_records.append({"field": f"Form1099NEC_Amount_{nec_copy}",
                                 "value": str(f1099.amount)})
            tab_records.append({"field": f"Form1099NEC_Payer_{nec_copy}",
                                 "value": f1099.payer_name})
            nec_copy += 1

        elif f1099.form_type == Form1099Type.INT:
            txf_records.append(_txf(
                category="C505", copy=int_copy,
                amount=f1099.amount, name=f1099.payer_name,
                description=f"1099-INT - {f1099.payer_name}"
            ))
            tab_records.append({"field": f"Form1099INT_Amount_{int_copy}",
                                 "value": str(f1099.amount)})
            int_copy += 1

        elif f1099.form_type == Form1099Type.DIV:
            txf_records.append(_txf(
                category="C516", copy=div_copy,
                amount=f1099.amount, name=f1099.payer_name,
                description=f"1099-DIV Ordinary - {f1099.payer_name}"
            ))
            if f1099.qualified_dividends > 0:
                txf_records.append(_txf(
                    category="C517", copy=div_copy,
                    amount=f1099.qualified_dividends, name=f1099.payer_name,
                    description=f"1099-DIV Qualified - {f1099.payer_name}"
                ))
            div_copy += 1

    # ── Schedule C ────────────────────────────────────────────────────────────
    sc_copy = 1
    for se in tax_return.self_employment:
        exp = se.expenses

        # Gross receipts
        if se.gross_receipts > 0:
            txf_records.append(_txf(
                category="C650", copy=sc_copy,
                amount=se.gross_receipts, name=se.business_name,
                description=f"Schedule C Gross Receipts - {se.business_name}"
            ))
            tab_records.append({"field": "ScheduleC_GrossReceipts",
                                 "value": str(se.gross_receipts)})

        if se.cogs > 0:
            txf_records.append(_txf(
                category="C651", copy=sc_copy,
                amount=se.cogs, name=se.business_name,
                description="Schedule C COGS"
            ))

        # Gross profit line
        tab_records.append({"field": "ScheduleC_GrossProfit",
                             "value": str(round(se.gross_income, 2))})

        # Expenses — only emit non-zero lines
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C660", "ScheduleC_Advertising", exp.advertising, "Advertising")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C661", "ScheduleC_CarExpense", exp.car_and_truck, "Car and Truck")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C662", "ScheduleC_CommissionsFees", exp.commissions_fees, "Commissions/Fees")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C663", "ScheduleC_ContractLabor", exp.contract_labor, "Contract Labor")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C664", "ScheduleC_Depletion", exp.depletion, "Depletion")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C665", "ScheduleC_Depreciation", exp.depreciation_179, "Depreciation")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C666", "ScheduleC_EmployeeBenefits", exp.employee_benefits, "Employee Benefits")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C667", "ScheduleC_Insurance", exp.insurance, "Insurance")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C670", "ScheduleC_LegalProfessional", exp.legal_professional, "Legal/Professional")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C671", "ScheduleC_Office", exp.office, "Office Expense")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C673", "ScheduleC_RentVehicles", exp.rent_vehicles_equipment, "Rent Vehicles/Equip")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C674", "ScheduleC_RentOther", exp.rent_other_property, "Rent Other Property")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C675", "ScheduleC_Repairs", exp.repairs_maintenance, "Repairs/Maintenance")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C676", "ScheduleC_Supplies", exp.supplies, "Supplies")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C677", "ScheduleC_TaxesLicenses", exp.taxes_licenses, "Taxes/Licenses")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C678", "ScheduleC_Travel", exp.travel, "Travel")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C679", "ScheduleC_Meals50pct", exp.meals_deductible, "Meals (50%)")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C680", "ScheduleC_Utilities", exp.utilities, "Utilities")
        _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                         "C681", "ScheduleC_Wages", exp.wages, "Wages")
        # Other expenses (phone, software, etc.)
        if exp.other_total > 0:
            _sched_c_expense(txf_records, tab_records, sc_copy, se.business_name,
                             "C682", "ScheduleC_OtherExpenses", exp.other_total, "Other Expenses")
            # Itemize other expenses in notes
            if exp.phone_internet > 0:
                notes.append(f"Schedule C Other: Phone/Internet ${exp.phone_internet:,.2f}")
            if exp.software_subscriptions > 0:
                notes.append(f"Schedule C Other: Software ${exp.software_subscriptions:,.2f}")
            if exp.education_training > 0:
                notes.append(f"Schedule C Other: Education ${exp.education_training:,.2f}")

        # Net profit
        tab_records.append({"field": "ScheduleC_NetProfit",
                             "value": str(round(se.net_profit, 2))})

        sc_copy += 1

    # ── Mileage ───────────────────────────────────────────────────────────────
    if tax_return.mileage and tax_return.mileage.total_business_miles > 0:
        miles = tax_return.mileage.total_business_miles
        deduction = tax_return.mileage.deduction_amount
        tab_records.append({"field": "ScheduleC_BusinessMiles",
                             "value": str(int(miles))})
        tab_records.append({"field": "ScheduleC_MileageDeduction",
                             "value": str(deduction)})
        notes.append(
            f"Business mileage: {int(miles):,} miles × "
            f"${tax_return.mileage.irs_rate_per_mile}/mile = ${deduction:,.2f}"
        )

    # ── SE tax deduction ──────────────────────────────────────────────────────
    if tax_return.se_deduction > 0:
        txf_records.append(_txf(
            category="C290", copy=1,
            amount=tax_return.se_deduction,
            description="Deductible Part of Self-Employment Tax (Schedule 1 Line 15)"
        ))
        tab_records.append({"field": "Schedule1_SEtaxDeduction",
                             "value": str(tax_return.se_deduction)})

    # ── QBI deduction ─────────────────────────────────────────────────────────
    if tax_return.qbi_deduction > 0:
        txf_records.append(_txf(
            category="C293", copy=1,
            amount=tax_return.qbi_deduction,
            description="QBI Deduction Section 199A (Form 1040 Line 13)"
        ))
        tab_records.append({"field": "Form1040_QBIDeduction",
                             "value": str(tax_return.qbi_deduction)})

    # ── Deductions ────────────────────────────────────────────────────────────
    from .validator import YEAR_RULES
    rules = YEAR_RULES.get(tax_return.tax_year, YEAR_RULES[2024])
    status = tax_return.personal_info.filing_status.value
    std_amt = rules["standard_deduction"].get(status, 14_600)

    if tax_return.deductions.method == DeductionMethod.STANDARD:
        tab_records.append({"field": "Form1040_StandardDeduction",
                             "value": str(std_amt)})
        notes.append(f"Standard deduction for {status} ({tax_return.tax_year}): ${std_amt:,}")
    else:
        tab_records.append({"field": "Form1040_ItemizedDeduction",
                             "value": str(round(tax_return.deductions.itemized_total, 2))})

    # ── Filing summary ────────────────────────────────────────────────────────
    tab_records.append({"field": "Form1040_FilingStatus",
                         "value": status})
    tab_records.append({"field": "Form1040_TaxYear",
                         "value": str(tax_return.tax_year)})
    tab_records.append({"field": "Form1040_State",
                         "value": "FL"})
    tab_records.append({"field": "Form1040_TotalFederalWithheld",
                         "value": str(round(tax_return.total_federal_withheld, 2))})

    notes.append("Florida resident — federal return only. No state filing required.")

    return TurboTaxExport(
        tax_return=tax_return,
        txf_records=txf_records,
        tab_records=tab_records,
        export_notes=notes,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _txf(
    category: str,
    copy: int,
    amount: float,
    name: str = "",
    description: str = "",
    txf_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a single TXF record dict."""
    return {
        "category":    category,
        "copy":        copy,
        "amount":      round(amount, 2),
        "name":        name,
        "description": description,
        "date":        txf_date or date.today().strftime("%m/%d/%Y"),
    }


def _sched_c_expense(
    txf_records: list,
    tab_records: list,
    copy: int,
    biz_name: str,
    txf_cat: str,
    tab_field: str,
    amount: float,
    label: str,
) -> None:
    """Emit a Schedule C expense line only if non-zero."""
    if amount <= 0:
        return
    txf_records.append(_txf(
        category=txf_cat, copy=copy,
        amount=amount, name=biz_name,
        description=f"Schedule C {label} - {biz_name}"
    ))
    tab_records.append({"field": tab_field, "value": str(round(amount, 2))})
