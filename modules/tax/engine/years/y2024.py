"""
y2024.py — Tax Year 2024 Rules
================================
Source: IRS Rev. Proc. 2023-34 | IR-2023-208
Filing deadline: April 15, 2025
"""

from tax_engine.years.base import TaxYear, YearRules


class TaxYear2024(TaxYear):

    def __init__(self):
        self.rules = YearRules(
            year=2024,
            is_projected=False,

            # ── Standard Deductions ──────────────────────────────────────────
            # Source: IRS Rev. Proc. 2023-34
            standard_deduction={
                "single":  14_600.0,
                "mfj":     29_200.0,
                "mfs":     14_600.0,
                "hoh":     21_900.0,
                "qss":     29_200.0,
            },

            # ── Ordinary Income Brackets ─────────────────────────────────────
            # Format: list of (rate, bottom_of_bracket)
            # Source: IRS Rev. Proc. 2023-34, Table 1
            brackets={
                "single": [
                    (0.10,   0.0),
                    (0.12,   11_600.0),
                    (0.22,   47_150.0),
                    (0.24,  100_525.0),
                    (0.32,  191_950.0),
                    (0.35,  243_725.0),
                    (0.37,  609_350.0),
                ],
                "mfj": [
                    (0.10,   0.0),
                    (0.12,   23_200.0),
                    (0.22,   94_300.0),
                    (0.24,  201_050.0),
                    (0.32,  383_900.0),
                    (0.35,  487_450.0),
                    (0.37,  731_200.0),
                ],
                "mfs": [
                    (0.10,   0.0),
                    (0.12,   11_600.0),
                    (0.22,   47_150.0),
                    (0.24,  100_525.0),
                    (0.32,  191_950.0),
                    (0.35,  243_725.0),
                    (0.37,  365_600.0),
                ],
                "hoh": [
                    (0.10,   0.0),
                    (0.12,   16_550.0),
                    (0.22,   63_100.0),
                    (0.24,  100_500.0),
                    (0.32,  191_950.0),
                    (0.35,  243_700.0),
                    (0.37,  609_350.0),
                ],
            },

            # ── Long-Term Capital Gains Brackets ─────────────────────────────
            # Source: IRS Rev. Proc. 2023-34, Table 5
            lt_cap_gains_brackets={
                "single": [
                    (0.00,  0.0),
                    (0.15,  47_025.0),
                    (0.20,  518_900.0),
                ],
                "mfj": [
                    (0.00,  0.0),
                    (0.15,  94_050.0),
                    (0.20,  583_750.0),
                ],
                "mfs": [
                    (0.00,  0.0),
                    (0.15,  47_025.0),
                    (0.20,  291_850.0),
                ],
                "hoh": [
                    (0.00,  0.0),
                    (0.15,  63_000.0),
                    (0.20,  551_350.0),
                ],
            },

            # ── Retirement & Account Contribution Limits ──────────────────────
            # Source: IRS Notice 2023-75
            contribution_limits={
                "401k":              23_000.0,   # employee elective deferral
                "401k_catchup_50":    7_500.0,   # if age 50+
                "ira":                7_000.0,   # traditional or Roth
                "ira_catchup":        1_000.0,   # if age 50+
                "hsa_self":           4_150.0,   # HDHP self-only coverage
                "hsa_family":         8_300.0,   # HDHP family coverage
                "hsa_catchup_55":     1_000.0,   # if age 55+
                "sep_ira_rate":       0.25,       # 25% of net SE income
                "sep_ira_max":       69_000.0,   # 2024 max
                "simple_ira":        16_000.0,
                "simple_ira_catchup": 3_500.0,
            },

            # ── AMT ──────────────────────────────────────────────────────────
            # Source: IRS Rev. Proc. 2023-34, Table 3
            amt_exemption={
                "single": 85_700.0,
                "mfj":   133_300.0,
                "mfs":    66_650.0,
            },
            amt_phaseout_start={
                "single": 609_350.0,
                "mfj":   1_218_700.0,
                "mfs":     609_350.0,
            },
            amt_rates=[(0.26, 0.0), (0.28, 232_600.0)],  # 28% over $232,600

            # ── Child Tax Credit ─────────────────────────────────────────────
            child_tax_credit_per_child=2_000.0,
            child_tax_credit_phaseout_start={
                "single": 200_000.0,
                "mfj":   400_000.0,
                "mfs":   200_000.0,
                "hoh":   200_000.0,
            },
            additional_child_tax_credit_rate=0.15,

            # ── Deduction Caps ───────────────────────────────────────────────
            salt_cap=10_000.0,             # TCJA cap | IRC §164(b)(6)
            mortgage_debt_limit=750_000.0,

            # ── QBI ──────────────────────────────────────────────────────────
            qbi_deduction_rate=0.20,
            qbi_available=True,

            # ── Personal Exemption (suspended under TCJA) ────────────────────
            personal_exemption=0.0,

            # ── Payroll ──────────────────────────────────────────────────────
            ss_wage_base=168_600.0,

            # ── Standard Mileage ─────────────────────────────────────────────
            # Source: IRS Notice 2024-08
            business_mileage_rate=0.67,    # $0.67/mile for business
        )

    def get_year(self) -> int:
        return 2024

    # ── 2024-specific notes ───────────────────────────────────────────────────
    NOTES = {
        "401k_catchup": "2024: uniform $7,500 catchup for age 50+",
        "ira_roth_limit_single": "Roth IRA phases out $146,000–$161,000 (single), "
                                  "$230,000–$240,000 (MFJ)",
        "filing_deadline": "April 15, 2025 (extension to Oct 15, 2025)",
    }
