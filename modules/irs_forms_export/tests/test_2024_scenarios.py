"""
test_2024_scenarios.py — Unit tests for IRS Forms Export module

Scenarios:
  1. Amazon Flex only (1099-NEC + mileage, single filer, no W-2)
  2. W-2 + Amazon Flex side income
  3. Itemized vs standard deduction comparison
  4. Multi-1099 (Amazon Flex + interest + dividends)
  5. Validation error cases
  6. TXF output format verification
  7. 2025 tax year
"""

import os
import sys
import json
import tempfile
import unittest

# Allow running from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from irs_forms_export import (
    load_accountant_data, validate_tax_data,
    map_to_turbotax, export_txf, export_tab_delimited,
    export_summary, export_all, YEAR_RULES,
)


# ─── Shared fixtures ──────────────────────────────────────────────────────────

def amazon_flex_only_2024() -> dict:
    """Amazon Flex driver, single filer, 1099-NEC only, mileage deduction."""
    return {
        "tax_year": 2024,
        "personal_info": {
            "first_name": "Darnie",
            "last_name": "Glover",
            "filing_status": "single",
            "address_line1": "123 Main St",
            "city": "Tampa",
            "state": "FL",
            "zip": "33601",
        },
        "w2_income": [],
        "1099_income": [
            {"payer": "Amazon.com Services LLC", "amount": 48500.00, "type": "NEC"},
        ],
        "self_employment_income": [
            {
                "business_name": "Amazon Flex Delivery",
                "business_code": "492000",
                "gross_receipts": 48500.00,
                "expenses": {
                    "supplies": 320.00,      # insulated bags, phone mount
                    "phone_internet": 480.00, # 40% of $100/mo phone bill × 12
                    "other": 150.00,          # misc delivery supplies
                },
            }
        ],
        "mileage": {
            "total_business_miles": 18500,
            "irs_rate_per_mile": 0.67,
        },
        "deductions": {"method": "standard"},
        "credits": {},
    }


def w2_plus_flex_2024() -> dict:
    """W-2 job + Amazon Flex side income."""
    return {
        "tax_year": 2024,
        "personal_info": {
            "first_name": "Darnie",
            "last_name": "Glover",
            "filing_status": "single",
            "city": "Tampa",
            "state": "FL",
            "zip": "33601",
        },
        "w2_income": [
            {
                "employer_name": "Tech Corp LLC",
                "wages": 55000.00,
                "federal_withholding": 8200.00,
                "box3_ss_wages": 55000.00,
                "box4_ss_withheld": 3410.00,
                "box5_medicare_wages": 55000.00,
                "box6_medicare_withheld": 797.50,
            }
        ],
        "1099_income": [
            {"payer": "Amazon.com Services LLC", "amount": 22000.00, "type": "NEC"},
        ],
        "self_employment_income": [
            {
                "business_name": "Amazon Flex Delivery",
                "business_code": "492000",
                "gross_receipts": 22000.00,
                "expenses": {
                    "supplies": 180.00,
                    "phone_internet": 480.00,
                },
            }
        ],
        "mileage": {
            "total_business_miles": 8200,
            "irs_rate_per_mile": 0.67,
        },
        "deductions": {"method": "standard"},
        "credits": {},
    }


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestLoadAccountantData(unittest.TestCase):

    def test_amazon_flex_only_loads(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        self.assertEqual(tr.tax_year, 2024)
        self.assertEqual(len(tr.form1099_income), 1)
        self.assertAlmostEqual(tr.total_1099_nec, 48500.00)
        self.assertEqual(len(tr.self_employment), 1)
        self.assertIsNotNone(tr.mileage)
        self.assertEqual(tr.mileage.total_business_miles, 18500)
        self.assertAlmostEqual(tr.mileage.irs_rate_per_mile, 0.67)

    def test_w2_plus_flex_loads(self):
        data = w2_plus_flex_2024()
        tr = load_accountant_data(data)
        self.assertEqual(len(tr.w2_income), 1)
        self.assertAlmostEqual(tr.total_w2_wages, 55000.00)
        self.assertAlmostEqual(tr.total_1099_nec, 22000.00)

    def test_filing_status_florida(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        self.assertEqual(tr.personal_info.address_state, "FL")
        self.assertEqual(tr.personal_info.filing_status.value, "single")

    def test_mileage_deduction_computed(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        expected = round(18500 * 0.67, 2)
        self.assertAlmostEqual(tr.mileage.deduction_amount, expected, places=2)

    def test_se_net_profit(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        se = tr.self_employment[0]
        # Expenses: supplies 320 + phone 480 + other 150 = 950
        # Gross: 48500 — Net: 48500 - 950 = 47550
        self.assertAlmostEqual(se.expenses.total, 950.00, places=2)
        self.assertAlmostEqual(se.net_profit, 47550.00, places=2)

    def test_1099_nec_flows_to_schedule_c(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        for f in tr.form1099_income:
            if f.form_type.value == "NEC":
                self.assertTrue(f.flows_to_schedule_c)


class TestValidation(unittest.TestCase):

    def test_clean_amazon_flex_no_errors(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        errors = validate_tax_data(tr)
        # Should have only INFO items, no errors or warnings
        hard_errors = [e for e in errors if e.severity == "error"]
        self.assertEqual(hard_errors, [],
                         msg=f"Unexpected errors: {[e.message for e in hard_errors]}")

    def test_florida_info_present(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        errors = validate_tax_data(tr)
        fl_note = [e for e in errors if e.code == "FL_NO_STATE_TAX"]
        self.assertEqual(len(fl_note), 1)

    def test_se_tax_reminder(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        errors = validate_tax_data(tr)
        se_note = [e for e in errors if e.code == "SE_DEDUCTION_REMINDER"]
        self.assertEqual(len(se_note), 1)

    def test_wrong_mileage_rate_flagged(self):
        data = amazon_flex_only_2024()
        data["mileage"]["irs_rate_per_mile"] = 0.58  # wrong rate for 2024
        tr = load_accountant_data(data)
        errors = validate_tax_data(tr)
        rate_warn = [e for e in errors if e.code == "MILEAGE_RATE_MISMATCH"]
        self.assertEqual(len(rate_warn), 1)

    def test_itemized_less_than_standard_flagged(self):
        data = amazon_flex_only_2024()
        data["deductions"] = {
            "method": "itemized",
            "mortgage_interest": 3000,
            "charitable_cash": 500,
        }
        tr = load_accountant_data(data)
        errors = validate_tax_data(tr)
        std_better = [e for e in errors if e.code == "STANDARD_DEDUCTION_LARGER"]
        self.assertEqual(len(std_better), 1)

    def test_nec_not_in_schedule_c_flagged(self):
        """1099-NEC income doesn't appear in Schedule C."""
        data = amazon_flex_only_2024()
        data["self_employment_income"] = []  # Remove Schedule C
        tr = load_accountant_data(data)
        errors = validate_tax_data(tr)
        nec_err = [e for e in errors if e.code == "NEC_NOT_IN_SCHEDULE_C"]
        self.assertEqual(len(nec_err), 1)

    def test_qbi_eligible_info(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        errors = validate_tax_data(tr)
        qbi = [e for e in errors if e.code == "QBI_ELIGIBLE"]
        self.assertEqual(len(qbi), 1)


class TestSECalculations(unittest.TestCase):

    def test_se_tax_calculation(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        # Net SE ~47550; SE tax = 47550 * 0.9235 * 0.153
        net = tr.total_se_net
        expected_se = round(net * 0.9235 * 0.153, 2)
        self.assertAlmostEqual(tr.se_tax, expected_se, places=1)

    def test_se_deduction_is_half_se_tax(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        self.assertAlmostEqual(tr.se_deduction, round(tr.se_tax * 0.50, 2), places=2)

    def test_qbi_deduction_20pct(self):
        """QBI = Sched C net profit × 20% (Form 8995 Line 1 = Sched C Line 31).
        SE deduction does NOT reduce QBI — it lives on Schedule 1, not Sched C."""
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        expected_qbi = round(max(tr.total_se_net, 0) * 0.20, 2)
        self.assertAlmostEqual(tr.qbi_deduction, expected_qbi, places=1)

    def test_agi_includes_se_deduction(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        gross = tr.total_1099_nec + tr.total_se_net
        # Wait — 1099-NEC flows to Schedule C, so gross = total_se_net
        # AGI = SE net - SE deduction
        expected_agi = max(tr.total_se_net - tr.se_deduction, 0)
        self.assertAlmostEqual(tr.agi, expected_agi, places=1)


class TestTurboTaxMapper(unittest.TestCase):

    def test_mapping_returns_export(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        export = map_to_turbotax(tr)
        self.assertIsNotNone(export)
        self.assertGreater(len(export.txf_records), 0)
        self.assertGreater(len(export.tab_records), 0)

    def test_1099_nec_in_txf(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        export = map_to_turbotax(tr)
        nec_records = [r for r in export.txf_records if r["category"] == "C631"]
        self.assertEqual(len(nec_records), 1)
        self.assertAlmostEqual(nec_records[0]["amount"], 48500.00)

    def test_schedule_c_in_tab(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        export = map_to_turbotax(tr)
        fields = {r["field"] for r in export.tab_records}
        self.assertIn("ScheduleC_GrossReceipts", fields)
        self.assertIn("ScheduleC_GrossProfit", fields)
        self.assertIn("ScheduleC_NetProfit", fields)

    def test_mileage_in_tab(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        export = map_to_turbotax(tr)
        fields = {r["field"]: r["value"] for r in export.tab_records}
        self.assertIn("ScheduleC_BusinessMiles", fields)
        self.assertEqual(fields["ScheduleC_BusinessMiles"], "18500")

    def test_florida_note_present(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        export = map_to_turbotax(tr)
        fl_notes = [n for n in export.export_notes if "Florida" in n or "FL" in n]
        self.assertGreater(len(fl_notes), 0)

    def test_w2_income_in_export(self):
        data = w2_plus_flex_2024()
        tr = load_accountant_data(data)
        export = map_to_turbotax(tr)
        w2_records = [r for r in export.txf_records if r["category"] == "C110"]
        self.assertEqual(len(w2_records), 1)
        self.assertAlmostEqual(w2_records[0]["amount"], 55000.00)

    def test_se_deduction_in_export(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        export = map_to_turbotax(tr)
        se_ded = [r for r in export.txf_records if r["category"] == "C290"]
        self.assertEqual(len(se_ded), 1)


class TestExporters(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        self.export = map_to_turbotax(tr)

    def test_txf_file_written(self):
        path = os.path.join(self.tmpdir, "2024_taxes.txf")
        export_txf(self.export, path)
        self.assertTrue(os.path.exists(path))

    def test_txf_starts_with_v042(self):
        path = os.path.join(self.tmpdir, "2024_taxes.txf")
        export_txf(self.export, path)
        with open(path) as f:
            first_line = f.readline().strip()
        self.assertEqual(first_line, "V042")

    def test_txf_contains_end_markers(self):
        path = os.path.join(self.tmpdir, "2024_taxes.txf")
        export_txf(self.export, path)
        with open(path) as f:
            content = f.read()
        self.assertIn("^", content)

    def test_txf_contains_category_codes(self):
        path = os.path.join(self.tmpdir, "2024_taxes.txf")
        export_txf(self.export, path)
        with open(path) as f:
            content = f.read()
        self.assertIn("C631", content)   # 1099-NEC
        self.assertIn("C650", content)   # Schedule C gross

    def test_tab_delimited_file_written(self):
        path = os.path.join(self.tmpdir, "2024_taxes.txt")
        export_tab_delimited(self.export, path)
        self.assertTrue(os.path.exists(path))

    def test_tab_delimited_format(self):
        path = os.path.join(self.tmpdir, "2024_taxes.txt")
        export_tab_delimited(self.export, path)
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        for line in lines:
            self.assertIn("\t", line, msg=f"Line missing tab: {line}")

    def test_export_all_creates_three_files(self):
        paths = export_all(self.export, self.tmpdir)
        self.assertIn("txf", paths)
        self.assertIn("tab", paths)
        self.assertIn("json", paths)
        for p in paths.values():
            self.assertTrue(os.path.exists(p), msg=f"Missing: {p}")

    def test_summary_contains_key_figures(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        summary = export_summary(tr)
        self.assertIn("TAX SUMMARY", summary)
        self.assertIn("Schedule C", summary)
        self.assertIn("Self-Employment Tax", summary)
        self.assertIn("Florida", summary)


class TestTaxYear2025(unittest.TestCase):

    def test_2025_standard_deduction_single(self):
        rules = YEAR_RULES[2025]
        self.assertEqual(rules["standard_deduction"]["single"], 15_000)

    def test_2025_mileage_rate(self):
        rules = YEAR_RULES[2025]
        self.assertAlmostEqual(rules["mileage_rate"], 0.70)

    def test_2025_loads_correctly(self):
        data = amazon_flex_only_2024()
        data["tax_year"] = 2025
        data["mileage"]["irs_rate_per_mile"] = 0.70
        tr = load_accountant_data(data)
        self.assertEqual(tr.tax_year, 2025)
        errors = validate_tax_data(tr)
        rate_warns = [e for e in errors if e.code == "MILEAGE_RATE_MISMATCH"]
        self.assertEqual(rate_warns, [])  # Correct rate, no warning


class TestAmazonFlexSpecific(unittest.TestCase):
    """Verify Amazon Flex business logic is handled correctly."""

    def test_1099_nec_is_self_employment(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        nec = [f for f in tr.form1099_income if f.form_type.value == "NEC"]
        self.assertTrue(all(f.flows_to_schedule_c for f in nec))

    def test_phone_expense_in_schedule_c(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        se = tr.self_employment[0]
        self.assertGreater(se.expenses.phone_internet, 0)

    def test_supplies_in_schedule_c(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        se = tr.self_employment[0]
        self.assertGreater(se.expenses.supplies, 0)

    def test_mileage_is_primary_vehicle_deduction(self):
        """Car and truck should be 0 when mileage method is used."""
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        se = tr.self_employment[0]
        # Mileage deduction handled separately, not in car_and_truck
        self.assertEqual(se.expenses.car_and_truck, 0.0)
        self.assertIsNotNone(tr.mileage)
        self.assertGreater(tr.mileage.deduction_amount, 0)

    def test_no_state_tax_in_export(self):
        data = amazon_flex_only_2024()
        tr = load_accountant_data(data)
        export = map_to_turbotax(tr)
        # No state tax fields
        state_fields = [r for r in export.tab_records
                        if "State_Tax" in r["field"] or "StateTax" in r["field"]]
        self.assertEqual(state_fields, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
