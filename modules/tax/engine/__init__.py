"""
tax engine — US Federal Tax Calculation Core
=============================================
Framework-agnostic calculation library. No HTTP, no registration.
GENESIS routing is handled by modules/tax/module.py.

Supports tax years: 2024, 2025 (primary), 2026 (TCJA-sunset projected)
Entries persist across year switches — same data, different rules applied.

Usage:
    from modules.tax.engine.calculator import TaxCalculator
    calc = TaxCalculator(filing_status="single")
    calc.set_income(w2=75000, freelance=12000)
    result_2025 = calc.calculate(2025)
    result_2026 = calc.calculate(2026)   # same entries, 2026 projected rules
"""

from modules.tax.engine.calculator import TaxCalculator
from modules.tax.engine.concepts import TAX_CONCEPTS

__version__ = "1.0.0"
__tax_years__ = [2024, 2025, 2026]
__all__ = ["TaxCalculator", "TAX_CONCEPTS"]
