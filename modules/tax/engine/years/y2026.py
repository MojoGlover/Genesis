"""
y2026.py — Tax Year 2026 Rules  ⚠️ PROJECTED / ESTIMATED
==========================================================
⚠️  ALL VALUES IN THIS FILE ARE PROJECTED OR ESTIMATED.
    They represent the TCJA-sunset scenario (provisions expire Dec 31, 2025).
    Congress may extend or modify any of these. Verify before filing.

If TCJA provisions are extended by legislation, 2026 will look much more
like 2025. This file represents the DEFAULT EXPIRATION scenario.

Sources used for projections:
- IRC as written pre-TCJA (pre-2018 law)
- CBO / Tax Policy Center inflation projections
- IRS historical bracket indexing patterns
"""

from tax_engine.years.base import TaxYear, YearRules


# ─── PROJECTION CONFIDENCE LEVELS ────────────────────────────────────────────
# HIGH   = directly from pre-TCJA law, just inflation-adjusted
# MEDIUM = estimated based on indexing patterns
# LOW    = political uncertainty; could change significantly
CONFIDENCE = {
    "brackets":             "HIGH — pre-2017 rates, inflation-projected thresholds",
    "standard_deduction":   "HIGH — returns to pre-TCJA formula, inflation-projected",
    "personal_exemption":   "MEDIUM — pre-2017 amount + inflation estimate",
    "salt_cap":             "HIGH — cap expires, returns to full deductibility",
    "child_tax_credit":     "HIGH — reverts to $1,000 per pre-2017 law",
    "qbi":                  "HIGH — §199A expires Dec 31, 2025",
    "amt_exemption":        "MEDIUM — drops significantly without TCJA inflation boost",
    "contribution_limits":  "HIGH — indexed independently, not TCJA-dependent",
    "legislative_risk":     "LOW CONFIDENCE — any legislation changes everything",
}


class TaxYear2026(TaxYear):

    def __init__(self):
        self.rules = YearRules(
            year=2026,
            is_projected=True,
            projection_notes=(
                "⚠️  TCJA SUNSET SCENARIO — projected if no legislative action. "
                "If TCJA is extended, values will be closer to 2025. "
                "All bracket thresholds are estimates using ~2.5% inflation adjustment "
                "from pre-2017 law. Personal exemption estimated at ~$5,300 "
                "(2017 value of $4,050 + inflation). Verify all values before use."
            ),

            # ── Standard Deductions ──────────────────────────────────────────
            # ⚠️ PROJECTED: Roughly HALF of 2025 values.
            # Pre-TCJA formula returns. Estimated with ~2.5% annual inflation.
            # 2017 single: $6,350 → ~$8,300-8,500 by 2026
            # 2017 MFJ: $12,700 → ~$16,600-17,000 by 2026
            standard_deduction={
                "single":  8_500.0,    # ⚠️ PROJECTED — was $15,000 in 2025
                "mfj":    17_000.0,    # ⚠️ PROJECTED — was $30,000 in 2025
                "mfs":     8_500.0,    # ⚠️ PROJECTED
                "hoh":    12_500.0,    # ⚠️ PROJECTED — was $22,500 in 2025
                "qss":    17_000.0,    # ⚠️ PROJECTED
            },

            # ── Ordinary Income Brackets ─────────────────────────────────────
            # ⚠️ PROJECTED: Pre-2017 7-bracket structure returns.
            # Rates: 10%, 15%, 25%, 28%, 33%, 35%, 39.6%
            # Thresholds estimated with ~2.5% inflation from 2017 levels.
            brackets={
                "single": [
                    (0.10,   0.0),
                    (0.15,  12_000.0),    # ⚠️ est — was $9,325 in 2017
                    (0.25,  48_000.0),    # ⚠️ est — was $37,950 in 2017
                    (0.28, 100_000.0),    # ⚠️ est — was $91,900 in 2017
                    (0.33, 200_000.0),    # ⚠️ est — was $191,650 in 2017
                    (0.35, 420_000.0),    # ⚠️ est — was $416,700 in 2017
                    (0.396, 480_000.0),   # ⚠️ est — was $418,400 in 2017
                ],
                "mfj": [
                    (0.10,   0.0),
                    (0.15,  24_000.0),    # ⚠️ est
                    (0.25,  96_000.0),    # ⚠️ est
                    (0.28, 160_000.0),    # ⚠️ est
                    (0.33, 240_000.0),    # ⚠️ est
                    (0.35, 420_000.0),    # ⚠️ est
                    (0.396, 480_000.0),   # ⚠️ est
                ],
                "mfs": [
                    (0.10,   0.0),
                    (0.15,  12_000.0),    # ⚠️ est
                    (0.25,  48_000.0),    # ⚠️ est
                    (0.28,  80_000.0),    # ⚠️ est
                    (0.33, 120_000.0),    # ⚠️ est
                    (0.35, 210_000.0),    # ⚠️ est
                    (0.396, 240_000.0),   # ⚠️ est
                ],
                "hoh": [
                    (0.10,   0.0),
                    (0.15,  17_000.0),    # ⚠️ est
                    (0.25,  65_000.0),    # ⚠️ est
                    (0.28, 100_000.0),    # ⚠️ est
                    (0.33, 200_000.0),    # ⚠️ est
                    (0.35, 420_000.0),    # ⚠️ est
                    (0.396, 480_000.0),   # ⚠️ est
                ],
            },

            # ── Long-Term Capital Gains Brackets ─────────────────────────────
            # ⚠️ PROJECTED: Pre-2017 structure returns.
            # 0%/15%/20% structure is permanent law (not TCJA) — likely stays.
            # Thresholds estimated.
            lt_cap_gains_brackets={
                "single": [
                    (0.00,  0.0),
                    (0.15,  50_000.0),    # ⚠️ est
                    (0.20, 550_000.0),    # ⚠️ est
                ],
                "mfj": [
                    (0.00,  0.0),
                    (0.15, 100_000.0),    # ⚠️ est
                    (0.20, 620_000.0),    # ⚠️ est
                ],
                "mfs": [
                    (0.00,  0.0),
                    (0.15,  50_000.0),    # ⚠️ est
                    (0.20, 310_000.0),    # ⚠️ est
                ],
                "hoh": [
                    (0.00,  0.0),
                    (0.15,  67_000.0),    # ⚠️ est
                    (0.20, 580_000.0),    # ⚠️ est
                ],
            },

            # ── Contribution Limits ──────────────────────────────────────────
            # NOT TCJA-dependent — indexed separately. Projected 2026 values.
            contribution_limits={
                "401k":               24_500.0,   # ⚠️ projected (~+$1k from 2025)
                "401k_catchup_50":     7_500.0,   # likely unchanged
                "401k_catchup_60_63": 11_250.0,   # SECURE 2.0 — permanent
                "ira":                 7_000.0,   # may not adjust (sub-$1k increment)
                "ira_catchup":         1_000.0,
                "hsa_self":            4_500.0,   # ⚠️ projected
                "hsa_family":          8_950.0,   # ⚠️ projected
                "hsa_catchup_55":      1_000.0,
                "sep_ira_rate":        0.25,
                "sep_ira_max":        72_000.0,   # ⚠️ projected
                "simple_ira":         17_000.0,   # ⚠️ projected
                "simple_ira_catchup":  3_500.0,
            },

            # ── AMT ──────────────────────────────────────────────────────────
            # ⚠️ PROJECTED: Without TCJA, AMT exemption drops sharply.
            # Pre-2017: Single $54,300, MFJ $84,500 (2017 values, not adjusted well)
            # More people would be AMT-liable again.
            amt_exemption={
                "single":  70_000.0,   # ⚠️ PROJECTED — was $88,100 in 2025
                "mfj":    109_000.0,   # ⚠️ PROJECTED — was $137,000 in 2025
                "mfs":     54_500.0,   # ⚠️ PROJECTED
            },
            amt_phaseout_start={
                "single":  500_000.0,  # ⚠️ PROJECTED — was $626,350 in 2025
                "mfj":   1_000_000.0,  # ⚠️ PROJECTED
                "mfs":     500_000.0,  # ⚠️ PROJECTED
            },
            amt_rates=[(0.26, 0.0), (0.28, 239_100.0)],  # rates unchanged

            # ── Child Tax Credit ─────────────────────────────────────────────
            # ⚠️ Pre-2017 law: $1,000 per child, no inflation adjustment
            child_tax_credit_per_child=1_000.0,   # ⚠️ drops from $2,000
            child_tax_credit_phaseout_start={
                "single":  75_000.0,   # ⚠️ PROJECTED — much lower threshold
                "mfj":    110_000.0,   # ⚠️ PROJECTED
                "mfs":     55_000.0,   # ⚠️ PROJECTED
                "hoh":     75_000.0,   # ⚠️ PROJECTED
            },
            additional_child_tax_credit_rate=0.15,

            # ── SALT — No Cap in 2026 ────────────────────────────────────────
            # ⚠️ PROJECTED: TCJA cap expires. Full state/local tax deductible again.
            salt_cap=float("inf"),     # ⚠️ cap removed — full deduction returns

            mortgage_debt_limit=1_000_000.0,   # ⚠️ reverts to $1M pre-TCJA limit

            # ── QBI — EXPIRES ────────────────────────────────────────────────
            # §199A sunsets Dec 31, 2025. No QBI deduction in 2026.
            qbi_deduction_rate=0.0,
            qbi_available=False,       # ⚠️ QBI deduction gone

            # ── Personal Exemption Returns ───────────────────────────────────
            # ⚠️ PROJECTED: $4,050 in 2017 + ~$1,250 inflation = ~$5,300
            personal_exemption=5_300.0,  # ⚠️ PROJECTED per person + dependent

            # ── Payroll ──────────────────────────────────────────────────────
            ss_wage_base=183_000.0,    # ⚠️ projected

            business_mileage_rate=0.72,  # ⚠️ projected
        )

    def get_year(self) -> int:
        return 2026

    # ── Key 2026 Changes Summary ──────────────────────────────────────────────
    CHANGES_FROM_2025 = {
        "standard_deduction":  "⚠️ Drops ~43% — single $15k→~$8.5k, MFJ $30k→~$17k",
        "brackets":            "⚠️ Rates change — top rate 37%→39.6%, 22%/24%→25%/28%",
        "personal_exemption":  "⚠️ Returns at ~$5,300/person — reduces taxable income",
        "child_tax_credit":    "⚠️ Drops $2,000→$1,000 per child",
        "salt_cap":            "⚠️ $10,000 cap removed — full state/local tax deductible",
        "qbi":                 "⚠️ §199A expires — 20% pass-through deduction GONE",
        "amt":                 "⚠️ Exemption drops — more middle-income filers hit AMT",
        "mortgage_limit":      "Returns to $1M from $750k",
        "legislative_note":    "Any TCJA extension changes all of the above.",
    }

    NOTES = {
        "warning": (
            "⚠️  2026 values are TCJA-sunset projections. If Congress extends TCJA, "
            "use 2025 values as the baseline and adjust only what changed. "
            "This file should be updated when legislation is signed."
        ),
        "planning_tip": (
            "Consider accelerating income into 2025 (lower rates) and deferring "
            "deductions to 2026 (if SALT cap removed, itemizing becomes more valuable)."
        ),
    }
