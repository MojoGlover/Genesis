"""
y2025.py — Tax Year 2025 Rules  ← PRIMARY YEAR
================================================
Source: IRS Rev. Proc. 2024-40 | IR-2024-273
Filing deadline: April 15, 2026
"""

from tax_engine.years.base import TaxYear, YearRules


class TaxYear2025(TaxYear):

    def __init__(self):
        self.rules = YearRules(
            year=2025,
            is_projected=False,

            # ── Standard Deductions ──────────────────────────────────────────
            # Source: IRS Rev. Proc. 2024-40
            standard_deduction={
                "single":  15_000.0,
                "mfj":     30_000.0,
                "mfs":     15_000.0,
                "hoh":     22_500.0,
                "qss":     30_000.0,
            },

            # ── Ordinary Income Brackets ─────────────────────────────────────
            # Source: IRS Rev. Proc. 2024-40, Table 1
            brackets={
                "single": [
                    (0.10,   0.0),
                    (0.12,   11_925.0),
                    (0.22,   48_475.0),
                    (0.24,  103_350.0),
                    (0.32,  197_300.0),
                    (0.35,  250_525.0),
                    (0.37,  626_350.0),
                ],
                "mfj": [
                    (0.10,   0.0),
                    (0.12,   23_850.0),
                    (0.22,   96_950.0),
                    (0.24,  206_700.0),
                    (0.32,  394_600.0),
                    (0.35,  501_050.0),
                    (0.37,  751_600.0),
                ],
                "mfs": [
                    (0.10,   0.0),
                    (0.12,   11_925.0),
                    (0.22,   48_475.0),
                    (0.24,  103_350.0),
                    (0.32,  197_300.0),
                    (0.35,  250_525.0),
                    (0.37,  375_800.0),
                ],
                "hoh": [
                    (0.10,   0.0),
                    (0.12,   17_000.0),
                    (0.22,   64_850.0),
                    (0.24,  103_350.0),
                    (0.32,  197_300.0),
                    (0.35,  250_500.0),
                    (0.37,  626_350.0),
                ],
            },

            # ── Long-Term Capital Gains Brackets ─────────────────────────────
            # Source: IRS Rev. Proc. 2024-40
            lt_cap_gains_brackets={
                "single": [
                    (0.00,  0.0),
                    (0.15,  48_350.0),
                    (0.20,  533_400.0),
                ],
                "mfj": [
                    (0.00,  0.0),
                    (0.15,  96_700.0),
                    (0.20,  600_050.0),
                ],
                "mfs": [
                    (0.00,  0.0),
                    (0.15,  48_350.0),
                    (0.20,  300_000.0),
                ],
                "hoh": [
                    (0.00,  0.0),
                    (0.15,  64_750.0),
                    (0.20,  566_700.0),
                ],
            },

            # ── Retirement & Account Contribution Limits ──────────────────────
            # Source: IRS Notice 2024-80
            contribution_limits={
                "401k":               23_500.0,  # employee elective deferral
                "401k_catchup_50":     7_500.0,  # age 50-59 and 64+
                "401k_catchup_60_63": 11_250.0,  # NEW in 2025 (SECURE 2.0): ages 60-63
                "ira":                 7_000.0,  # traditional or Roth (unchanged)
                "ira_catchup":         1_000.0,  # age 50+ (not yet inflation-indexed)
                "hsa_self":            4_300.0,  # HDHP self-only
                "hsa_family":          8_550.0,  # HDHP family
                "hsa_catchup_55":      1_000.0,  # age 55+
                "sep_ira_rate":        0.25,
                "sep_ira_max":        70_000.0,
                "simple_ira":         16_500.0,
                "simple_ira_catchup":  3_500.0,
            },

            # ── AMT ──────────────────────────────────────────────────────────
            # Source: IRS Rev. Proc. 2024-40, Table 3
            amt_exemption={
                "single":  88_100.0,
                "mfj":    137_000.0,
                "mfs":     68_500.0,
            },
            amt_phaseout_start={
                "single":   626_350.0,
                "mfj":    1_252_700.0,
                "mfs":      626_350.0,
            },
            amt_rates=[(0.26, 0.0), (0.28, 239_100.0)],

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
            salt_cap=10_000.0,
            mortgage_debt_limit=750_000.0,

            # ── QBI ──────────────────────────────────────────────────────────
            qbi_deduction_rate=0.20,
            qbi_available=True,     # LAST year under TCJA unless renewed

            # ── Personal Exemption ───────────────────────────────────────────
            personal_exemption=0.0,  # still suspended under TCJA

            # ── Payroll ──────────────────────────────────────────────────────
            ss_wage_base=176_100.0,

            # ── Standard Mileage ─────────────────────────────────────────────
            # Source: IRS Notice 2025-5
            business_mileage_rate=0.70,   # $0.70/mile
        )

    def get_year(self) -> int:
        return 2025

    # ── 2025-specific notes ───────────────────────────────────────────────────
    NOTES = {
        "secure_2_0_catchup": (
            "SECURE 2.0 Act introduced enhanced 401k catchup for ages 60-63: "
            "$11,250 in 2025 (instead of $7,500)."
        ),
        "tcja_expiry_warning": (
            "TCJA individual provisions expire Dec 31, 2025 unless Congress acts. "
            "This affects: standard deduction, brackets, SALT cap, QBI, CTC, AMT, "
            "estate tax exemption, and more."
        ),
        "ira_roth_limit_single": (
            "Roth IRA phases out $150,000–$165,000 (single), "
            "$236,000–$246,000 (MFJ)."
        ),
        "filing_deadline": "April 15, 2026 (extension to Oct 15, 2026)",
        "primary_year": "This is the PRIMARY calculation year for this module.",
    }
