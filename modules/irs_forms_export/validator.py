"""
validator.py — IRS rules validation for TaxReturn data

Validates against current-year IRS limits and flags issues before export.
Florida: no state tax calculations.
"""

from __future__ import annotations
from typing import List

from .models import TaxReturn, ValidationError, DeductionMethod, Form1099Type


# ─── Year-specific IRS constants ──────────────────────────────────────────────

YEAR_RULES: dict = {
    2024: {
        "standard_deduction": {
            "single": 14_600, "mfj": 29_200, "mfs": 14_600,
            "hoh": 21_900, "qss": 29_200,
        },
        "mileage_rate":          0.67,
        "ss_wage_base":          168_600,
        "se_tax_rate":           0.153,
        "qbi_threshold_single":  191_950,
        "qbi_threshold_mfj":     383_900,
        "child_tax_credit_max":  2_000,
        "ctc_refundable_max":    1_700,
        "additional_std_65":     1_550,   # extra std deduction if over 65 (single)
        "additional_std_65_mfj": 1_250,
    },
    2025: {
        "standard_deduction": {
            "single": 15_000, "mfj": 30_000, "mfs": 15_000,
            "hoh": 22_500, "qss": 30_000,
        },
        "mileage_rate":          0.70,
        "ss_wage_base":          176_100,
        "se_tax_rate":           0.153,
        "qbi_threshold_single":  197_300,
        "qbi_threshold_mfj":     394_600,
        "child_tax_credit_max":  2_000,
        "ctc_refundable_max":    1_700,
        "additional_std_65":     1_600,
        "additional_std_65_mfj": 1_300,
    },
}


def validate_tax_data(tax_return: TaxReturn) -> List[ValidationError]:
    """
    Run all validation checks on a TaxReturn.
    Returns list of ValidationError (may be empty on clean data).
    """
    errors: List[ValidationError] = []
    rules = YEAR_RULES.get(tax_return.tax_year, YEAR_RULES[2024])
    status = tax_return.personal_info.filing_status.value

    _check_mileage(tax_return, rules, errors)
    _check_deductions(tax_return, rules, status, errors)
    _check_w2(tax_return, errors)
    _check_1099_nec(tax_return, errors)
    _check_depreciation(tax_return, errors)
    _check_se_tax(tax_return, rules, errors)
    _check_qbi(tax_return, rules, status, errors)
    _check_florida_state(tax_return, errors)
    _check_credits(tax_return, rules, errors)

    return errors


# ─── Individual checks ────────────────────────────────────────────────────────

def _check_mileage(tr: TaxReturn, rules: dict, errors: List[ValidationError]) -> None:
    if tr.mileage is None:
        return

    # Verify mileage rate matches IRS rate for the year
    expected_rate = rules["mileage_rate"]
    if abs(tr.mileage.irs_rate_per_mile - expected_rate) > 0.001:
        errors.append(ValidationError(
            severity="warning",
            code="MILEAGE_RATE_MISMATCH",
            field="mileage.irs_rate_per_mile",
            message=(
                f"Mileage rate {tr.mileage.irs_rate_per_mile} doesn't match "
                f"IRS {tr.tax_year} rate of ${expected_rate}/mile."
            ),
            suggestion=f"Update irs_rate_per_mile to {expected_rate}",
        ))

    # Mileage deduction cannot exceed total SE income
    deduction = tr.mileage.deduction_amount
    se_net = tr.total_se_net
    if deduction > se_net and se_net > 0:
        errors.append(ValidationError(
            severity="error",
            code="MILEAGE_EXCEEDS_SE_INCOME",
            field="mileage.computed_deduction",
            message=(
                f"Mileage deduction ${deduction:,.2f} exceeds total SE net income "
                f"${se_net:,.2f}. This may trigger IRS scrutiny."
            ),
            suggestion="Verify total business miles and confirm gross SE income is complete.",
        ))

    # Verify mileage computation
    expected = round(tr.mileage.total_business_miles * tr.mileage.irs_rate_per_mile, 2)
    if (tr.mileage.computed_deduction is not None
            and abs(tr.mileage.computed_deduction - expected) > 1.00):
        errors.append(ValidationError(
            severity="warning",
            code="MILEAGE_COMPUTATION_MISMATCH",
            field="mileage.computed_deduction",
            message=(
                f"Computed deduction ${tr.mileage.computed_deduction:,.2f} doesn't match "
                f"{tr.mileage.total_business_miles} miles × ${tr.mileage.irs_rate_per_mile} "
                f"= ${expected:,.2f}"
            ),
            suggestion="Let the module compute the deduction automatically (set computed_deduction=None).",
        ))


def _check_deductions(
    tr: TaxReturn, rules: dict, status: str, errors: List[ValidationError]
) -> None:
    std = rules["standard_deduction"].get(status, 14_600)

    # Flag if both methods provided
    if (tr.deductions.method == DeductionMethod.ITEMIZED
            and tr.deductions.itemized_total == 0):
        errors.append(ValidationError(
            severity="warning",
            code="ITEMIZED_NO_AMOUNTS",
            field="deductions.method",
            message="Deduction method is 'itemized' but no itemized amounts are provided.",
            suggestion="Either supply itemized amounts or change method to 'standard'.",
        ))

    # Recommend standard if itemized is less
    if (tr.deductions.method == DeductionMethod.ITEMIZED
            and tr.deductions.itemized_total < std):
        errors.append(ValidationError(
            severity="info",
            code="STANDARD_DEDUCTION_LARGER",
            field="deductions.method",
            message=(
                f"Itemized total ${tr.deductions.itemized_total:,.2f} is less than the "
                f"{tr.tax_year} standard deduction of ${std:,.2f} for {status}. "
                "Taking standard deduction saves more tax."
            ),
            suggestion="Change deduction method to 'standard'.",
        ))

    # Florida: SALT should be property tax only (no state income tax)
    if tr.deductions.state_local_taxes > 10_000:
        errors.append(ValidationError(
            severity="warning",
            code="SALT_CAP_EXCEEDED",
            field="deductions.state_local_taxes",
            message=(
                f"SALT deduction ${tr.deductions.state_local_taxes:,.2f} exceeds the "
                "$10,000 TCJA cap. Only $10,000 is deductible."
            ),
            suggestion="Cap SALT deduction at $10,000.",
        ))


def _check_w2(tr: TaxReturn, errors: List[ValidationError]) -> None:
    for i, w2 in enumerate(tr.w2_income):
        # Box 4 SS withheld should be 6.2% of Box 3 SS wages
        if w2.box3_ss_wages > 0 and w2.box4_ss_withheld > 0:
            expected_ss = round(w2.box3_ss_wages * 0.062, 2)
            if abs(w2.box4_ss_withheld - expected_ss) > 5.00:
                errors.append(ValidationError(
                    severity="warning",
                    code="W2_SS_WITHHELD_MISMATCH",
                    field=f"w2_income[{i}].box4_ss_withheld",
                    message=(
                        f"W-2 from {w2.employer_name}: SS withheld "
                        f"${w2.box4_ss_withheld} doesn't match expected "
                        f"6.2% of SS wages (${expected_ss:,.2f})."
                    ),
                ))

        # Box 6 Medicare: 1.45% of Box 5
        if w2.box5_medicare_wages > 0 and w2.box6_medicare_withheld > 0:
            expected_med = round(w2.box5_medicare_wages * 0.0145, 2)
            if abs(w2.box6_medicare_withheld - expected_med) > 5.00:
                errors.append(ValidationError(
                    severity="warning",
                    code="W2_MEDICARE_WITHHELD_MISMATCH",
                    field=f"w2_income[{i}].box6_medicare_withheld",
                    message=(
                        f"W-2 from {w2.employer_name}: Medicare withheld "
                        f"${w2.box6_medicare_withheld} doesn't match expected "
                        f"1.45% of Medicare wages (${expected_med:,.2f})."
                    ),
                ))

        # Florida: no state income tax — flag if state withholding > 0
        if w2.state_withheld > 0:
            errors.append(ValidationError(
                severity="warning",
                code="FL_STATE_WITHHOLDING",
                field=f"w2_income[{i}].state_withheld",
                message=(
                    f"W-2 from {w2.employer_name} shows state withholding "
                    f"${w2.state_withheld:,.2f}. Florida has no state income tax. "
                    "Verify this is correct (may be from work in another state)."
                ),
            ))


def _check_1099_nec(tr: TaxReturn, errors: List[ValidationError]) -> None:
    for i, f1099 in enumerate(tr.form1099_income):
        if f1099.form_type == Form1099Type.NEC:
            if not f1099.flows_to_schedule_c:
                errors.append(ValidationError(
                    severity="error",
                    code="NEC_NOT_ON_SCHEDULE_C",
                    field=f"form1099_income[{i}].flows_to_schedule_c",
                    message=(
                        f"1099-NEC from {f1099.payer_name} (${f1099.amount:,.2f}) "
                        "must flow to Schedule C as self-employment income per IRS rules."
                    ),
                    suggestion="Set flows_to_schedule_c=True for all 1099-NEC entries.",
                ))

            # NEC income should appear in SE schedule
            se_gross = tr.total_se_gross
            total_nec = tr.total_1099_nec
            if total_nec > 0 and se_gross < total_nec * 0.95:
                errors.append(ValidationError(
                    severity="warning",
                    code="NEC_NOT_IN_SCHEDULE_C",
                    field="self_employment",
                    message=(
                        f"Total 1099-NEC income ${total_nec:,.2f} doesn't appear in "
                        f"Schedule C gross receipts (${se_gross:,.2f}). "
                        "IRS requires 1099-NEC to flow to Schedule C."
                    ),
                    suggestion="Add a SelfEmploymentIncome entry with gross_receipts matching your 1099-NEC total.",
                ))


def _check_depreciation(tr: TaxReturn, errors: List[ValidationError]) -> None:
    from dateutil.parser import parse as parse_date
    from datetime import date

    for i, asset in enumerate(tr.depreciation):
        try:
            purchase = parse_date(asset.purchase_date).date()
        except Exception:
            errors.append(ValidationError(
                severity="error",
                code="DEPRECIATION_BAD_DATE",
                field=f"depreciation[{i}].purchase_date",
                message=f"Asset '{asset.description}': invalid purchase_date '{asset.purchase_date}'",
                suggestion="Use ISO format: YYYY-MM-DD",
            ))
            continue

        # Asset must be purchased in or before the tax year
        if purchase.year > tr.tax_year:
            errors.append(ValidationError(
                severity="error",
                code="DEPRECIATION_FUTURE_ASSET",
                field=f"depreciation[{i}].purchase_date",
                message=(
                    f"Asset '{asset.description}' purchased {asset.purchase_date} "
                    f"is after tax year {tr.tax_year}."
                ),
            ))

        # Section 179 cannot exceed business income
        if asset.section_179_amount > 0:
            se_net = tr.total_se_net
            total_179 = sum(
                a.section_179_amount for a in tr.depreciation
            )
            if total_179 > se_net and se_net > 0:
                errors.append(ValidationError(
                    severity="warning",
                    code="SEC_179_EXCEEDS_INCOME",
                    field=f"depreciation[{i}].section_179_amount",
                    message=(
                        f"Section 179 total ${total_179:,.2f} may exceed business "
                        f"income ${se_net:,.2f}. Excess is carried forward."
                    ),
                    suggestion="Review Section 179 election; excess carries to next year.",
                ))
                break


def _check_se_tax(tr: TaxReturn, rules: dict, errors: List[ValidationError]) -> None:
    if tr.total_se_net <= 400:
        return  # Below SE tax filing threshold

    expected_se = round(max(tr.total_se_net, 0) * 0.9235 * 0.153, 2)
    computed = tr.se_tax
    if abs(computed - expected_se) > 1.00:
        errors.append(ValidationError(
            severity="info",
            code="SE_TAX_NOTE",
            field="se_tax",
            message=(
                f"SE tax computed at ${computed:,.2f} "
                f"(net SE income × 92.35% × 15.3%)."
            ),
        ))

    # Deduction reminder
    errors.append(ValidationError(
        severity="info",
        code="SE_DEDUCTION_REMINDER",
        field="se_deduction",
        message=(
            f"SE tax deduction (50% of SE tax): ${tr.se_deduction:,.2f} "
            "applied as above-the-line deduction on Form 1040 Schedule 1."
        ),
    ))


def _check_qbi(
    tr: TaxReturn, rules: dict, status: str, errors: List[ValidationError]
) -> None:
    if tr.total_se_net <= 0:
        return

    threshold_key = "qbi_threshold_mfj" if status == "mfj" else "qbi_threshold_single"
    threshold = rules[threshold_key]

    if tr.agi > threshold:
        errors.append(ValidationError(
            severity="warning",
            code="QBI_ABOVE_THRESHOLD",
            field="qbi_deduction",
            message=(
                f"AGI ${tr.agi:,.2f} exceeds the {tr.tax_year} QBI phaseout threshold "
                f"(${threshold:,.2f} for {status}). QBI deduction may be limited by "
                "W-2 wages or UBIA of qualified property. Consult a tax professional."
            ),
        ))
    else:
        errors.append(ValidationError(
            severity="info",
            code="QBI_ELIGIBLE",
            field="qbi_deduction",
            message=(
                f"Estimated QBI (Section 199A) deduction: ${tr.qbi_deduction:,.2f} "
                "(20% of qualified business income, below phaseout threshold)."
            ),
        ))


def _check_florida_state(tr: TaxReturn, errors: List[ValidationError]) -> None:
    errors.append(ValidationError(
        severity="info",
        code="FL_NO_STATE_TAX",
        field="personal_info.address_state",
        message=(
            "Florida has no state income tax. "
            "Only federal return is required. No state filing needed."
        ),
    ))


def _check_credits(tr: TaxReturn, rules: dict, errors: List[ValidationError]) -> None:
    # Child tax credit max
    max_ctc = rules["child_tax_credit_max"]
    num_qualifying = sum(
        1 for d in tr.personal_info.dependents
        if d.qualifying_child and (tr.tax_year - d.birth_year) < 17
    )
    if tr.credits.child_tax_credit > num_qualifying * max_ctc:
        errors.append(ValidationError(
            severity="error",
            code="CTC_EXCEEDS_MAX",
            field="credits.child_tax_credit",
            message=(
                f"Child tax credit ${tr.credits.child_tax_credit:,.2f} exceeds "
                f"max of ${num_qualifying * max_ctc:,.2f} "
                f"({num_qualifying} qualifying child(ren) × ${max_ctc:,})."
            ),
        ))
