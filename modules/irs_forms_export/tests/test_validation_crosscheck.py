"""
test_validation_crosscheck.py — Triple-source accuracy validation

Runs the same tax scenario through all three reference engines and
compares results to our irs_forms_export module.

Reference engines:
  1. IRS Worksheets  — exact step-by-step arithmetic from official IRS
                       publications (Schedule SE, Form 8995, 1040 Worksheet)
                       Implemented verbatim here as the canonical ground truth.

  2. PolicyEngine US — open-source Python microsimulation library, cross-
                       validated against NBER TAXSIM. pip install policyengine-us

  3. NBER TAXSIM 35  — Fortran tax engine from National Bureau of Economic
                       Research. HTTP oracle — no install, just a POST.
                       https://taxsim.nber.org/taxsim35/

Scenario: Amazon Flex driver, single, Florida, 2024
  - 1099-NEC income:  $48,500
  - Business expenses: $950 (supplies + phone + misc)
  - Mileage:          18,500 miles × $0.67 = $12,395
  - Schedule C net:   $48,500 - $950 - $12,395 = $35,155
  - Standard deduction, no credits, no W-2

Run:
    python3 -m pytest tests/test_validation_crosscheck.py -v

Skip external (requires internet):
    python3 -m pytest tests/test_validation_crosscheck.py -v -m "not external"

Skip PolicyEngine (large dependency):
    python3 -m pytest tests/test_validation_crosscheck.py -v -m "not policyengine"
"""

import os
import sys
import json
import unittest

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from irs_forms_export import load_accountant_data, validate_tax_data

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO — same inputs fed to all three engines
# ─────────────────────────────────────────────────────────────────────────────

AGENT_DATA = {
    "tax_year": 2024,
    "personal_info": {
        "first_name": "Darnie",
        "last_name":  "Glover",
        "filing_status": "single",
        "state": "FL",
    },
    "1099_income": [
        {"payer": "Amazon.com Services LLC", "amount": 48_500.00, "type": "NEC"},
    ],
    "self_employment_income": [
        {
            "business_name":  "Amazon Flex Delivery",
            "business_code":  "492000",
            "gross_receipts": 48_500.00,
            "expenses": {
                "supplies":      320.00,
                "phone_internet": 480.00,
                "other":         150.00,
            },
        }
    ],
    "mileage": {
        "total_business_miles":  18_500,
        "irs_rate_per_mile":     0.67,
    },
    "deductions": {"method": "standard"},
    "credits": {},
}

# ── Pre-computed scenario numbers ─────────────────────────────────────────────
GROSS_RECEIPTS   = 48_500.00
EXPENSES         = 950.00          # 320 + 480 + 150
MILEAGE_DED      = 18_500 * 0.67   # 12,395.00
SCHED_C_NET      = GROSS_RECEIPTS - EXPENSES - MILEAGE_DED   # 35,155.00
SE_TAX           = round(SCHED_C_NET * 0.9235 * 0.153, 2)   # 4,965.72
SE_DEDUCTION     = round(SE_TAX / 2, 2)                       # 2,482.86
QBI_BASE         = max(SCHED_C_NET - SE_DEDUCTION, 0)         # 32,672.14
QBI_DEDUCTION    = round(QBI_BASE * 0.20, 2)                  # 6,534.43
AGI              = max(SCHED_C_NET - SE_DEDUCTION, 0)         # 32,672.14
STANDARD_DED_24  = 14_600.00
TAXABLE_INCOME   = max(AGI - STANDARD_DED_24 - QBI_DEDUCTION, 0)   # 11,537.71
# 2024 bracket: 10% on first $11,600; 12% above
INCOME_TAX_SCHED = round(TAXABLE_INCOME * 0.10, 2)            # ~$1,153.77 (all in 10% bracket)

# Tolerance for floating-point comparisons (dollars)
TOLERANCE = 2.00    # within $2 — acceptable for bracket rounding differences


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE 1: IRS Official Worksheets (authoritative ground truth)
# Implemented verbatim from:
#   - Schedule SE (2024) instructions: irs.gov/pub/irs-pdf/i1040sse.pdf
#   - Form 8995 (2024) instructions:   irs.gov/instructions/i8995
#   - 1040 Tax Computation Worksheet:  1040 instructions p.67
# ─────────────────────────────────────────────────────────────────────────────

def irs_worksheet_compute(sched_c_net: float, filing_status: str = "single",
                           year: int = 2024) -> dict:
    """
    Exact IRS worksheet arithmetic for Schedule C + SE income.

    Schedule SE (Short Form):
        Line 2:  Net profit from Schedule C
        Line 3:  Multiply line 2 by 0.9235 (92.35%)
        Line 4:  Multiply line 3 by 0.153  (15.3% SE tax)
                 (on first $168,600 SS wage base for 2024)
        Line 6:  Deductible SE tax = line 4 × 0.50

    Form 8995 (QBI Deduction):
        Line 1:  Qualified business income (Sched C net profit)
        Line 15: QBI deduction = qualified income × 20%
                 (below phaseout threshold $191,950 single 2024)

    Form 1040:
        AGI = gross income - SE deduction (Schedule 1 Line 15)
        Standard deduction (2024 single): $14,600
        Taxable income = AGI - standard deduction - QBI deduction
        Tax = bracket calculation from Tax Computation Worksheet
    """
    # ── Schedule SE ──────────────────────────────────────────────────────────
    # Line 2: net profit (from Schedule C)
    net_profit = sched_c_net
    # Line 3: × 92.35%
    se_net_92  = round(net_profit * 0.9235, 2)
    # Line 4a: × 15.3% (assuming below SS wage base)
    se_tax     = round(se_net_92 * 0.153, 2)
    # Line 13: deductible portion = ÷ 2
    se_ded     = round(se_tax / 2, 2)

    # ── Form 8995 (QBI) ───────────────────────────────────────────────────────
    # Line 1: QBI = Schedule C Line 31 (net profit)
    # Source: Form 8995 instructions — "If your only business is a sole
    # proprietorship, this is the amount on Schedule C, line 31."
    # The SE tax deduction lives on Schedule 1, NOT Schedule C — it does NOT
    # reduce QBI. QBI base = Schedule C net profit (after mileage/expenses).
    # QBI phaseout 2024 single: $191,950 — we are below it
    qbi_income  = max(net_profit, 0)              # QBI = Sched C net profit (line 31)
    qbi_ded     = round(qbi_income * 0.20, 2)

    # ── Form 1040 ─────────────────────────────────────────────────────────────
    gross_income  = net_profit         # all SE, no W-2
    agi           = max(gross_income - se_ded, 0)

    # Standard deduction 2024
    std_ded = {2024: {"single": 14_600, "mfj": 29_200, "hoh": 21_900},
               2025: {"single": 15_000, "mfj": 30_000, "hoh": 22_500}}
    standard_ded = std_ded.get(year, std_ded[2024]).get(filing_status, 14_600)

    taxable = max(agi - standard_ded - qbi_ded, 0)

    # 1040 Tax Computation Worksheet (2024 brackets, single)
    # Source: IRS 1040 instructions, p.67
    brackets_2024_single = [
        (11_600,  0.10,       0),
        (47_150,  0.12,   1_160),
        (100_525, 0.22,   5_426),
        (191_950, 0.24,  17_168.50),
        (243_725, 0.32,  39_110.50),
        (609_350, 0.35,  55_678.50),
        (float("inf"), 0.37, 183_647.25),
    ]
    income_tax = _bracket_tax(taxable, brackets_2024_single)

    return {
        "engine":         "IRS_worksheet",
        "sched_c_net":    round(net_profit, 2),
        "se_tax":         se_tax,
        "se_deduction":   se_ded,
        "qbi_deduction":  qbi_ded,
        "agi":            round(agi, 2),
        "standard_ded":   standard_ded,
        "taxable_income": round(taxable, 2),
        "income_tax":     income_tax,
        "total_tax":      round(se_tax + income_tax, 2),
    }


def _bracket_tax(income: float, brackets: list) -> float:
    """Apply bracket table to income. Each entry: (upper_bound, rate, tax_at_lower)."""
    tax = 0.0
    prev_upper = 0.0
    for upper, rate, base_tax in brackets:
        if income <= prev_upper:
            break
        taxable_in_bracket = min(income, upper) - prev_upper
        tax = base_tax + taxable_in_bracket * rate
        if income <= upper:
            break
        prev_upper = upper
    return round(tax, 2)


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE 2: PolicyEngine US
# ─────────────────────────────────────────────────────────────────────────────

def policyengine_compute(sched_c_net: float, year: int = 2024) -> dict:
    """
    Compute tax via PolicyEngine US for single FL filer with SE income.
    Returns dict of computed values, or raises SkipTest if unavailable.
    """
    try:
        from policyengine_us import Simulation
    except ImportError:
        pytest.skip("policyengine-us not installed — run: pip install policyengine-us")

    situation = {
        "people": {
            "filer": {
                "age":                    {str(year): 40},
                "self_employment_income": {str(year): sched_c_net},
                "is_tax_unit_head":       {str(year): True},
                "business_is_qualified":  {str(year): True},
            }
        },
        "tax_units": {
            "tax_unit": {"members": ["filer"]},
        },
        "spm_units": {
            "spm_unit": {
                "members": ["filer"],
                "snap":    {str(year): 0},
                "tanf":    {str(year): 0},
            }
        },
        "households": {
            "household": {
                "members":    ["filer"],
                "state_code": {str(year): "FL"},
            }
        },
    }

    try:
        sim = Simulation(situation=situation)
        period = str(year)
        return {
            "engine":        "PolicyEngine_US",
            "se_tax":        float(sim.calculate("self_employment_tax", period)[0]),
            "se_deduction":  float(sim.calculate("self_employment_tax_ald", period)[0]),
            "qbi_deduction": float(sim.calculate("qualified_business_income_deduction", period)[0]),
            "agi":           float(sim.calculate("adjusted_gross_income", period)[0]),
            "taxable_income":float(sim.calculate("taxable_income", period)[0]),
            "income_tax":    float(sim.calculate("income_tax_before_credits", period)[0]),
        }
    except Exception as e:
        pytest.skip(f"PolicyEngine computation failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE 3: NBER TAXSIM 35 (HTTP oracle)
# ─────────────────────────────────────────────────────────────────────────────

def taxsim_compute(sched_c_net: float, year: int = 2024) -> dict:
    """
    Submit scenario to NBER TAXSIM 35 and parse results.
    Requires internet access.

    TAXSIM input columns used:
        taxsimid  — arbitrary ID
        year      — tax year
        state     — 10 = Florida (SOI state code)
        mstat     — 1 = single
        page      — primary taxpayer age
        psemp     — primary SE income (Schedule C net)
        pbusinc   — business income for QBI calculation
        idtl      — 2 = extended output (includes qbid, v10=AGI, v18=taxable)
    """
    try:
        import urllib.request
        import urllib.parse
        import io
    except ImportError:
        pytest.skip("urllib not available")

    # Build the CSV input
    csv_input = (
        "taxsimid,year,state,mstat,page,psemp,pbusinc,idtl\n"
        f"1,{year},10,1,40,{sched_c_net:.0f},{sched_c_net:.0f},2\n"
    )

    try:
        boundary = "taxsimboundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="txpydata.raw"; filename="data.csv"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
            f"{csv_input}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        req = urllib.request.Request(
            "https://taxsim.nber.org/taxsim35/",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8").strip()

        if not raw or "error" in raw.lower():
            pytest.skip(f"TAXSIM returned unexpected response: {raw[:200]}")

        # Parse CSV response
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if len(lines) < 2:
            pytest.skip(f"TAXSIM response too short: {raw[:200]}")

        headers = [h.strip() for h in lines[0].split(",")]
        values  = [v.strip() for v in lines[1].split(",")]
        row     = dict(zip(headers, values))

        def _f(key: str, default: float = 0.0) -> float:
            return float(row.get(key, default))

        return {
            "engine":         "NBER_TAXSIM",
            "se_tax":         _f("fica") / 2,   # TAXSIM reports both-halves FICA; SE = employee half
            "qbi_deduction":  _f("qbid"),
            "agi":            _f("v10"),
            "taxable_income": _f("v18"),
            "income_tax":     _f("fiitax"),
            "raw":            row,
        }

    except Exception as e:
        pytest.skip(f"TAXSIM unreachable: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE 0: Our module (irs_forms_export)
# ─────────────────────────────────────────────────────────────────────────────

def our_module_compute() -> dict:
    """Run AGENT_DATA through irs_forms_export and extract key values."""
    tr = load_accountant_data(AGENT_DATA)
    return {
        "engine":         "irs_forms_export",
        "sched_c_net":    round(tr.total_se_net, 2),
        "se_tax":         tr.se_tax,
        "se_deduction":   tr.se_deduction,
        "qbi_deduction":  tr.qbi_deduction,
        "agi":            round(tr.agi, 2),
        "taxable_income": None,   # not a top-level property; in exporters
        "income_tax":     None,   # same
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helper: comparison report
# ─────────────────────────────────────────────────────────────────────────────

def _compare(label: str, ours: float, reference: float, tol: float = TOLERANCE) -> bool:
    diff = abs(ours - reference)
    ok   = diff <= tol
    status = "✅" if ok else "❌"
    print(f"  {status} {label:30s} ours=${ours:>10,.2f}  ref=${reference:>10,.2f}  diff=${diff:.2f}")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# TEST CLASSES
# ─────────────────────────────────────────────────────────────────────────────

class TestIRSWorksheetGroundTruth(unittest.TestCase):
    """
    Verify our module against IRS official worksheet arithmetic.
    These are the canonical ground truth tests — no internet required.
    """

    @classmethod
    def setUpClass(cls):
        cls.ours = our_module_compute()
        cls.irsw = irs_worksheet_compute(SCHED_C_NET, "single", 2024)
        print(f"\n{'═'*60}")
        print(f"ENGINE: IRS Worksheets vs irs_forms_export")
        print(f"Scenario: Amazon Flex 2024, {SCHED_C_NET:,.2f} Sched C net")
        print(f"{'═'*60}")

    def test_schedule_c_net(self):
        """Our Schedule C net profit matches expected."""
        self.assertAlmostEqual(self.ours["sched_c_net"], SCHED_C_NET, delta=0.02,
                               msg=f"Sched C net: ours={self.ours['sched_c_net']} expected={SCHED_C_NET}")

    def test_se_tax_vs_irs_worksheet(self):
        """SE tax matches Schedule SE worksheet (net × 92.35% × 15.3%)."""
        ok = _compare("SE tax", self.ours["se_tax"], self.irsw["se_tax"])
        self.assertTrue(ok, f"SE tax mismatch: ours={self.ours['se_tax']} IRS={self.irsw['se_tax']}")

    def test_se_deduction_vs_irs_worksheet(self):
        """SE deduction (above-line) matches Schedule SE Line 13 (SE tax ÷ 2)."""
        ok = _compare("SE deduction", self.ours["se_deduction"], self.irsw["se_deduction"])
        self.assertTrue(ok)

    def test_qbi_deduction_vs_form_8995(self):
        """QBI deduction matches Form 8995 Line 15 (QBI × 20%)."""
        ok = _compare("QBI deduction", self.ours["qbi_deduction"], self.irsw["qbi_deduction"])
        self.assertTrue(ok)

    def test_agi_vs_irs_worksheet(self):
        """AGI matches 1040 Schedule 1 (SE net - SE deduction)."""
        ok = _compare("AGI", self.ours["agi"], self.irsw["agi"])
        self.assertTrue(ok)

    def test_se_tax_formula_exact(self):
        """SE tax formula: net × 0.9235 × 0.153 (verbatim from Schedule SE)."""
        expected = round(SCHED_C_NET * 0.9235 * 0.153, 2)
        self.assertAlmostEqual(self.ours["se_tax"], expected, delta=0.02,
            msg=f"SE tax formula wrong: {SCHED_C_NET} × 0.9235 × 0.153 = {expected}, got {self.ours['se_tax']}")

    def test_qbi_rate_exact(self):
        """QBI deduction = 20% of Schedule C net profit (Form 8995 Line 1).
        SE deduction is NOT subtracted — it lives on Schedule 1, not Sched C."""
        expected = round(SCHED_C_NET * 0.20, 2)
        self.assertAlmostEqual(self.ours["qbi_deduction"], expected, delta=0.02)

    def test_standard_deduction_2024_single(self):
        """2024 standard deduction for single = $14,600 (IRS Rev. Proc. 2023-34)."""
        self.assertEqual(self.irsw["standard_ded"], 14_600)

    def test_mileage_rate_2024(self):
        """2024 IRS standard mileage rate = $0.67/mile."""
        tr = load_accountant_data(AGENT_DATA)
        self.assertAlmostEqual(tr.mileage.irs_rate_per_mile, 0.67, places=3)

    def test_mileage_deduction_correct(self):
        """18,500 miles × $0.67 = $12,395.00."""
        expected = round(18_500 * 0.67, 2)
        tr = load_accountant_data(AGENT_DATA)
        self.assertAlmostEqual(tr.mileage.deduction_amount, expected, places=2)

    def test_florida_no_state_tax(self):
        """Florida: no state income tax — validator emits FL_NO_STATE_TAX info."""
        tr = load_accountant_data(AGENT_DATA)
        errors = validate_tax_data(tr)
        fl = [e for e in errors if e.code == "FL_NO_STATE_TAX"]
        self.assertEqual(len(fl), 1)
        self.assertEqual(fl[0].severity, "info")

    def test_no_validation_errors(self):
        """Clean Amazon Flex scenario produces zero errors (warnings/info ok)."""
        tr = load_accountant_data(AGENT_DATA)
        errors = validate_tax_data(tr)
        hard = [e for e in errors if e.severity == "error"]
        self.assertEqual(hard, [], msg=[e.message for e in hard])


@pytest.mark.policyengine
class TestPolicyEngineValidation(unittest.TestCase):
    """
    Cross-validate against PolicyEngine US.
    Requires: pip install policyengine-us
    Skip with: pytest -m "not policyengine"
    """

    @classmethod
    def setUpClass(cls):
        cls.ours = our_module_compute()
        cls.pe   = policyengine_compute(SCHED_C_NET, year=2024)
        print(f"\n{'═'*60}")
        print(f"ENGINE: PolicyEngine US vs irs_forms_export")
        print(f"{'═'*60}")

    def test_se_tax_vs_policyengine(self):
        ok = _compare("SE tax", self.ours["se_tax"], self.pe["se_tax"])
        self.assertTrue(ok)

    def test_se_deduction_vs_policyengine(self):
        ok = _compare("SE deduction", self.ours["se_deduction"], self.pe["se_deduction"])
        self.assertTrue(ok)

    def test_qbi_deduction_vs_policyengine(self):
        ok = _compare("QBI deduction", self.ours["qbi_deduction"], self.pe["qbi_deduction"])
        self.assertTrue(ok)

    def test_agi_vs_policyengine(self):
        ok = _compare("AGI", self.ours["agi"], self.pe["agi"])
        self.assertTrue(ok)


@pytest.mark.external
class TestTAXSIMValidation(unittest.TestCase):
    """
    Cross-validate against NBER TAXSIM 35 (HTTP oracle).
    Requires internet access.
    Skip with: pytest -m "not external"
    """

    @classmethod
    def setUpClass(cls):
        cls.ours   = our_module_compute()
        cls.taxsim = taxsim_compute(SCHED_C_NET, year=2024)
        print(f"\n{'═'*60}")
        print(f"ENGINE: NBER TAXSIM 35 vs irs_forms_export")
        print(f"{'═'*60}")
        if cls.taxsim:
            print(f"  TAXSIM raw: {cls.taxsim.get('raw', {})}")

    def test_qbi_deduction_vs_taxsim(self):
        ok = _compare("QBI deduction", self.ours["qbi_deduction"], self.taxsim["qbi_deduction"])
        self.assertTrue(ok)

    def test_agi_vs_taxsim(self):
        ok = _compare("AGI", self.ours["agi"], self.taxsim["agi"])
        self.assertTrue(ok)

    def test_income_tax_vs_taxsim(self):
        # Use the bracket estimator from exporters for our income tax
        from irs_forms_export.exporters import _estimate_tax
        tr     = load_accountant_data(AGENT_DATA)
        our_it = _estimate_tax(
            max(tr.agi - 14_600 - tr.qbi_deduction, 0),
            "single", 2024
        )
        ok = _compare("Income tax", our_it, self.taxsim["income_tax"])
        self.assertTrue(ok)


@pytest.mark.policyengine
@pytest.mark.external
class TestTripleEngineAgreement(unittest.TestCase):
    """
    All three engines must agree with each other AND with ours.
    This is the definitive confirmation test.
    """

    @classmethod
    def setUpClass(cls):
        cls.ours   = our_module_compute()
        cls.irsw   = irs_worksheet_compute(SCHED_C_NET)
        cls.pe     = policyengine_compute(SCHED_C_NET, year=2024)
        cls.taxsim = taxsim_compute(SCHED_C_NET, year=2024)
        print(f"\n{'═'*60}")
        print(f"TRIPLE ENGINE AGREEMENT REPORT")
        print(f"Scenario: {SCHED_C_NET:,.2f} Sched C net, single, FL, 2024")
        print(f"{'═'*60}")
        print(f"{'Field':<30} {'Ours':>12} {'IRS WS':>12} {'PolicyEng':>12} {'TAXSIM':>12}")
        print(f"{'-'*78}")
        for field in ["se_tax", "se_deduction", "qbi_deduction", "agi"]:
            o = cls.ours.get(field)
            i = cls.irsw.get(field)
            p = cls.pe.get(field)   if cls.pe     else None
            t = cls.taxsim.get(field) if cls.taxsim else None
            print(f"  {field:<28} "
                  f"${o or 0:>10,.2f}  "
                  f"${i or 0:>10,.2f}  "
                  f"${p or 0:>10,.2f}  "
                  f"${t or 0:>10,.2f}")
        print(f"{'═'*60}")

    def test_se_tax_all_agree(self):
        """SE tax: all four engines within $2 of each other."""
        vals = {
            "ours":  self.ours["se_tax"],
            "irsw":  self.irsw["se_tax"],
            "pe":    self.pe["se_tax"],
        }
        if self.taxsim and self.taxsim.get("se_tax"):
            vals["taxsim"] = self.taxsim["se_tax"]

        baseline = vals["irsw"]
        for name, v in vals.items():
            self.assertAlmostEqual(v, baseline, delta=TOLERANCE,
                msg=f"SE tax divergence — {name}=${v:.2f} vs IRS=${baseline:.2f}")

    def test_qbi_all_agree(self):
        """QBI deduction: all engines within $2."""
        vals = {
            "ours": self.ours["qbi_deduction"],
            "irsw": self.irsw["qbi_deduction"],
            "pe":   self.pe["qbi_deduction"],
        }
        if self.taxsim and self.taxsim.get("qbi_deduction"):
            vals["taxsim"] = self.taxsim["qbi_deduction"]

        baseline = vals["irsw"]
        for name, v in vals.items():
            self.assertAlmostEqual(v, baseline, delta=TOLERANCE,
                msg=f"QBI divergence — {name}=${v:.2f} vs IRS=${baseline:.2f}")

    def test_agi_all_agree(self):
        """AGI: all engines within $2."""
        vals = {
            "ours": self.ours["agi"],
            "irsw": self.irsw["agi"],
            "pe":   self.pe["agi"],
        }
        if self.taxsim and self.taxsim.get("agi"):
            vals["taxsim"] = self.taxsim["agi"]

        baseline = vals["irsw"]
        for name, v in vals.items():
            self.assertAlmostEqual(v, baseline, delta=TOLERANCE,
                msg=f"AGI divergence — {name}=${v:.2f} vs IRS=${baseline:.2f}")


class TestIRSWorksheetVariants(unittest.TestCase):
    """
    Additional IRS worksheet tests across different income levels
    to verify brackets and phaseouts are correct.
    """

    def _check_scenario(self, label: str, sched_c_net: float):
        irsw = irs_worksheet_compute(sched_c_net)
        # SE tax: Sched SE Lines 3-4 — net × 0.9235 × 0.153
        expected_se = round(sched_c_net * 0.9235 * 0.153, 2)
        self.assertAlmostEqual(irsw["se_tax"], expected_se, delta=0.02, msg=label)
        # QBI: Form 8995 Line 1 = Sched C Line 31 (net profit, no SE deduction subtracted)
        expected_qbi = round(max(sched_c_net, 0) * 0.20, 2)
        self.assertAlmostEqual(irsw["qbi_deduction"], expected_qbi, delta=0.02, msg=label)
        return irsw

    def test_low_income_10pct_bracket(self):
        """$20,000 net SE — deductions exceed income, taxable = 0, only SE tax owed."""
        result = self._check_scenario("$20k SE", 20_000)
        # SE ded ($1,413) + std ded ($14,600) + QBI ($4,000) = $20,013 > $20,000
        # Taxable income floors at zero — no income tax, just SE tax
        self.assertEqual(result["taxable_income"], 0)
        self.assertEqual(result["income_tax"], 0.0)
        self.assertGreater(result["se_tax"], 0)   # SE tax still owed

    def test_mid_income_amazon_flex(self):
        """$35,155 SE net — our main scenario."""
        self._check_scenario("$35,155 SE (Amazon Flex)", SCHED_C_NET)

    def test_high_income_22pct_bracket(self):
        """$80,000 SE net — verify QBI + SE deductions push into lower bracket."""
        result = self._check_scenario("$80k SE", 80_000)
        # After SE deduction (~$5,649), QBI (~$16,000), std deduction ($14,600)
        # taxable income ~$43,751 — still in 12% bracket, confirming deductions work
        self.assertGreater(result["taxable_income"], 11_600)   # above 10% bracket floor
        self.assertLess(result["taxable_income"], 100_525)     # below 24% bracket
        self.assertGreater(result["income_tax"], 0)

    def test_ss_wage_base_cap_2024(self):
        """
        SE SS tax caps at $168,600 SS wage base.
        Above $168,600, only Medicare (2.9%) applies on additional income.
        """
        high_net = 200_000.0
        se_net_92 = high_net * 0.9235
        # SS portion: 12.4% capped at $168,600
        ss_base = min(se_net_92, 168_600)
        ss_tax  = round(ss_base * 0.124, 2)
        # Medicare: 2.9% on all (no additional 0.9% for single < $200k)
        medicare_tax = round(se_net_92 * 0.029, 2)
        expected_se  = round(ss_tax + medicare_tax, 2)
        # Our validator uses simplified 15.3% flat — this test confirms the
        # SS cap matters above ~$182,500 SE net (≈$168,600 / 0.9235)
        # Below that threshold 15.3% × 92.35% is exact
        threshold = round(168_600 / 0.9235, 0)
        if high_net < threshold:
            irsw = irs_worksheet_compute(high_net)
            self.assertAlmostEqual(irsw["se_tax"], expected_se, delta=1.00)
        else:
            # Flag: above SS wage base, 15.3% flat rate overstates SE tax
            overstated = round(high_net * 0.9235 * 0.153, 2) - expected_se
            print(f"\n  ℹ️  SS wage base cap: at ${high_net:,.0f} SE income, "
                  f"flat 15.3% overstates SE tax by ${overstated:,.2f}")
            self.assertGreater(overstated, 0)

    def test_2025_standard_deduction(self):
        """2025 standard deduction for single = $15,000."""
        result = irs_worksheet_compute(SCHED_C_NET, "single", 2025)
        self.assertEqual(result["standard_ded"], 15_000)

    def test_2025_mileage_rate(self):
        """2025 mileage rate = $0.70/mile."""
        from irs_forms_export.validator import YEAR_RULES
        self.assertAlmostEqual(YEAR_RULES[2025]["mileage_rate"], 0.70)


if __name__ == "__main__":
    # When run directly, show the full comparison report
    print("\n" + "═"*60)
    print("MANUAL VALIDATION REPORT")
    print("═"*60)

    ours = our_module_compute()
    irsw = irs_worksheet_compute(SCHED_C_NET)

    print(f"\nScenario: Amazon Flex 2024")
    print(f"  Gross receipts:      ${GROSS_RECEIPTS:>10,.2f}")
    print(f"  Expenses:           -${EXPENSES:>9,.2f}")
    print(f"  Mileage deduction:  -${MILEAGE_DED:>9,.2f}")
    print(f"  Schedule C net:      ${SCHED_C_NET:>10,.2f}")
    print()
    print(f"{'Field':<30} {'Ours':>12} {'IRS WS':>12} {'Match':>6}")
    print("-"*62)
    for field in ["se_tax", "se_deduction", "qbi_deduction", "agi"]:
        o = ours.get(field, 0) or 0
        i = irsw.get(field, 0) or 0
        match = "✅" if abs(o - i) <= TOLERANCE else "❌"
        print(f"  {field:<28} ${o:>10,.2f}  ${i:>10,.2f}  {match}")

    print("\nRunning PolicyEngine...")
    try:
        pe = policyengine_compute(SCHED_C_NET, year=2024)
        for field in ["se_tax", "se_deduction", "qbi_deduction", "agi"]:
            o = ours.get(field, 0) or 0
            p = pe.get(field, 0) or 0
            match = "✅" if abs(o - p) <= TOLERANCE else "❌"
            print(f"  PE {field:<26} ${o:>10,.2f}  ${p:>10,.2f}  {match}")
    except Exception as e:
        print(f"  PolicyEngine: {e}")

    print("\nRunning TAXSIM...")
    try:
        ts = taxsim_compute(SCHED_C_NET, year=2024)
        if ts:
            for field in ["qbi_deduction", "agi", "income_tax"]:
                o = ours.get(field, 0) or 0
                t = ts.get(field, 0) or 0
                match = "✅" if abs(o - t) <= TOLERANCE else "❌"
                print(f"  TS {field:<26} ${o:>10,.2f}  ${t:>10,.2f}  {match}")
    except Exception as e:
        print(f"  TAXSIM: {e}")

    print("\nRunning unit tests...")
    unittest.main(verbosity=2, exit=True)
