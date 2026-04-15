"""
irs_forms_export — IRS Forms Export Module for Accountant Agent

Converts structured tax data from the Accountant into TurboTax-compatible
TXF (Tax Exchange Format) files for import.

Supported tax years: 2024, 2025
State: Florida — federal only, no state income tax

Amazon Flex specific:
  - 1099-NEC income → Schedule C
  - Standard mileage rate as primary vehicle deduction
  - Phone/data plan, insulated bags, phone mounts → Schedule C supplies/other

Quick start:
    from irs_forms_export import load_accountant_data, validate_tax_data
    from irs_forms_export import map_to_turbotax, export_txf, export_summary

    tax_return = load_accountant_data(agent_output)
    errors = validate_tax_data(tax_return)
    if not errors:
        export = map_to_turbotax(tax_return)
        export_txf(export, "output/2024_taxes.txf")
    else:
        for e in errors:
            print(f"[{e.severity}] {e.code}: {e.message}")
"""

from .models import (
    TaxReturn, TurboTaxExport, ValidationError,
    W2Entry, Form1099Entry, Form1099Type,
    SelfEmploymentIncome, ScheduleCExpenses,
    MileageRecord, DepreciationAsset, DepreciationType,
    DeductionData, DeductionMethod,
    CreditData, DependentInfo, PersonalInfo, FilingStatus,
)
from .validator import validate_tax_data, YEAR_RULES
from .turbotax_mapper import map_to_turbotax
from .exporters import (
    export_txf, export_tab_delimited, export_json,
    export_summary, export_all,
)


def load_accountant_data(data: dict) -> TaxReturn:
    """
    Ingest and structure tax data from the Accountant agent dict.

    Expected keys:
        tax_year          — int (2024 or 2025)
        personal_info     — dict (filing_status, dependents, etc.)
        w2_income         — list of W-2 dicts
        1099_income       — list of 1099 dicts
        self_employment_income — list of Schedule C dicts
        mileage           — mileage dict
        depreciation      — list of asset dicts
        deductions        — deduction dict
        credits           — credits dict

    Returns TaxReturn (Pydantic model, validated).
    """
    # Normalize key names from agent format
    tax_year = int(data.get("tax_year", 2024))

    # Personal info
    pi_raw = data.get("personal_info", {})
    personal_info = PersonalInfo(
        first_name=pi_raw.get("first_name", ""),
        last_name=pi_raw.get("last_name", ""),
        ssn_last4=pi_raw.get("ssn_last4", "XXXX"),
        filing_status=FilingStatus(pi_raw.get("filing_status", "single")),
        address_line1=pi_raw.get("address_line1", pi_raw.get("address", "")),
        address_city=pi_raw.get("city", ""),
        address_state=pi_raw.get("state", "FL"),
        address_zip=pi_raw.get("zip", ""),
        dependents=[DependentInfo(**d) for d in pi_raw.get("dependents", [])],
        over_65=pi_raw.get("over_65", False),
        blind=pi_raw.get("blind", False),
    )

    # W-2 income
    w2_income = []
    for w in data.get("w2_income", []):
        w2_income.append(W2Entry(
            employer_name=w.get("employer_name", w.get("employer", "")),
            employer_ein=w.get("ein"),
            box1_wages=float(w.get("wages", w.get("box1_wages", 0))),
            box2_federal_withheld=float(w.get("federal_withholding",
                                               w.get("box2_federal_withheld", 0))),
            box3_ss_wages=float(w.get("box3_ss_wages", 0)),
            box4_ss_withheld=float(w.get("box4_ss_withheld", 0)),
            box5_medicare_wages=float(w.get("box5_medicare_wages", 0)),
            box6_medicare_withheld=float(w.get("box6_medicare_withheld", 0)),
            state_wages=float(w.get("state_wages", 0)),
            state_withheld=float(w.get("state_withholding",
                                       w.get("state_withheld", 0))),
        ))

    # 1099 income (key is "1099_income" in spec)
    form1099 = []
    for f in data.get("1099_income", data.get("form1099_income", [])):
        form1099.append(Form1099Entry(
            payer_name=f.get("payer", f.get("payer_name", "")),
            payer_tin=f.get("tin"),
            form_type=Form1099Type(f.get("type", "NEC")),
            amount=float(f.get("amount", 0)),
            qualified_dividends=float(f.get("qualified_dividends", 0)),
            federal_withheld=float(f.get("federal_withheld", 0)),
            state_withheld=float(f.get("state_withheld", 0)),
        ))

    # Self-employment / Schedule C
    self_employment = []
    for se in data.get("self_employment_income", []):
        expenses_raw = se.get("expenses", se.get("business_expenses", {}))
        expenses = ScheduleCExpenses(
            advertising=float(expenses_raw.get("advertising", 0)),
            car_and_truck=float(expenses_raw.get("car_and_truck",
                                                   expenses_raw.get("vehicle", 0))),
            commissions_fees=float(expenses_raw.get("commissions_fees",
                                                      expenses_raw.get("commissions", 0))),
            contract_labor=float(expenses_raw.get("contract_labor", 0)),
            depletion=float(expenses_raw.get("depletion", 0)),
            depreciation_179=float(expenses_raw.get("depreciation",
                                                      expenses_raw.get("depreciation_179", 0))),
            employee_benefits=float(expenses_raw.get("employee_benefits", 0)),
            insurance=float(expenses_raw.get("insurance", 0)),
            mortgage_interest_bank=float(expenses_raw.get("mortgage_interest", 0)),
            other_interest=float(expenses_raw.get("other_interest", 0)),
            legal_professional=float(expenses_raw.get("legal_professional",
                                                       expenses_raw.get("legal", 0))),
            office=float(expenses_raw.get("office", 0)),
            pension_profit_sharing=float(expenses_raw.get("pension", 0)),
            rent_vehicles_equipment=float(expenses_raw.get("rent_vehicles", 0)),
            rent_other_property=float(expenses_raw.get("rent_other",
                                                         expenses_raw.get("rent", 0))),
            repairs_maintenance=float(expenses_raw.get("repairs", 0)),
            supplies=float(expenses_raw.get("supplies", 0)),
            taxes_licenses=float(expenses_raw.get("taxes_licenses",
                                                    expenses_raw.get("taxes", 0))),
            travel=float(expenses_raw.get("travel", 0)),
            meals=float(expenses_raw.get("meals", 0)),
            utilities=float(expenses_raw.get("utilities", 0)),
            wages=float(expenses_raw.get("wages", 0)),
            phone_internet=float(expenses_raw.get("phone_internet",
                                                    expenses_raw.get("phone", 0))),
            software_subscriptions=float(expenses_raw.get("software",
                                                            expenses_raw.get("software_subscriptions", 0))),
            education_training=float(expenses_raw.get("education", 0)),
            other_expenses=float(expenses_raw.get("other", 0)),
        )
        self_employment.append(SelfEmploymentIncome(
            business_name=se.get("business_name", "Self-Employment"),
            business_code=se.get("business_code", "492000"),
            gross_receipts=float(se.get("gross_receipts", 0)),
            returns_allowances=float(se.get("returns_allowances", 0)),
            cogs=float(se.get("cogs", se.get("cost_of_goods_sold", 0))),
            other_income=float(se.get("other_income", 0)),
            expenses=expenses,
        ))

    # Mileage
    mileage = None
    mil_raw = data.get("mileage")
    if mil_raw:
        # Look up IRS rate if not provided
        year_rules = YEAR_RULES.get(tax_year, YEAR_RULES[2024])
        mileage = MileageRecord(
            total_business_miles=float(mil_raw.get("total_business_miles",
                                                    mil_raw.get("miles", 0))),
            irs_rate_per_mile=float(mil_raw.get("irs_rate",
                                                 mil_raw.get("irs_rate_per_mile",
                                                              year_rules["mileage_rate"]))),
            computed_deduction=mil_raw.get("computed_deduction"),
            commute_miles=float(mil_raw.get("commute_miles", 0)),
        )

    # Depreciation
    depreciation = []
    for asset in data.get("depreciation", []):
        depreciation.append(DepreciationAsset(
            description=asset.get("description", "Asset"),
            purchase_date=asset.get("purchase_date", f"{tax_year}-01-01"),
            cost_basis=float(asset.get("cost_basis", asset.get("cost", 0))),
            depreciation_type=DepreciationType(
                asset.get("type", asset.get("depreciation_type", "section_179"))
            ),
            section_179_amount=float(asset.get("section_179_amount",
                                                 asset.get("section_179", 0))),
            bonus_depreciation=float(asset.get("bonus_depreciation", 0)),
            recovery_period=int(asset.get("recovery_period", 5)),
            business_use_pct=float(asset.get("business_use_pct", 1.0)),
        ))

    # Deductions
    ded_raw = data.get("deductions", {})
    deductions = DeductionData(
        method=DeductionMethod(ded_raw.get("method", "standard")),
        mortgage_interest=float(ded_raw.get("mortgage_interest", 0)),
        state_local_taxes=float(ded_raw.get("state_local_taxes",
                                              ded_raw.get("property_tax", 0))),
        charitable_cash=float(ded_raw.get("charitable_cash",
                                            ded_raw.get("charity", 0))),
        charitable_noncash=float(ded_raw.get("charitable_noncash", 0)),
        medical_expenses=float(ded_raw.get("medical_expenses", 0)),
        other_itemized=float(ded_raw.get("other_itemized", 0)),
    )

    # Credits
    cred_raw = data.get("credits", {})
    credits = CreditData(
        child_tax_credit=float(cred_raw.get("child_tax_credit", 0)),
        additional_child_tax=float(cred_raw.get("additional_child_tax", 0)),
        earned_income_credit=float(cred_raw.get("earned_income_credit",
                                                   cred_raw.get("eic", 0))),
        child_dependent_care=float(cred_raw.get("child_dependent_care",
                                                   cred_raw.get("childcare", 0))),
        education_american_opp=float(cred_raw.get("education_american_opp",
                                                    cred_raw.get("aoc", 0))),
        education_lifetime_learn=float(cred_raw.get("education_lifetime_learn",
                                                      cred_raw.get("llc", 0))),
        retirement_saver=float(cred_raw.get("retirement_saver", 0)),
        ev_vehicle_credit=float(cred_raw.get("ev_vehicle_credit",
                                               cred_raw.get("ev_credit", 0))),
        other_credits=float(cred_raw.get("other_credits", 0)),
    )

    return TaxReturn(
        tax_year=tax_year,
        personal_info=personal_info,
        w2_income=w2_income,
        form1099_income=form1099,
        self_employment=self_employment,
        mileage=mileage,
        depreciation=depreciation,
        deductions=deductions,
        credits=credits,
    )


__all__ = [
    "load_accountant_data",
    "validate_tax_data",
    "map_to_turbotax",
    "export_txf",
    "export_tab_delimited",
    "export_json",
    "export_summary",
    "export_all",
    "TaxReturn",
    "TurboTaxExport",
    "ValidationError",
    "YEAR_RULES",
]
