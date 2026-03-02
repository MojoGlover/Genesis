"""Year rule registry — maps year int to TaxYear subclass."""
from tax_engine.years.y2024 import TaxYear2024
from tax_engine.years.y2025 import TaxYear2025
from tax_engine.years.y2026 import TaxYear2026

YEAR_REGISTRY = {
    2024: TaxYear2024,
    2025: TaxYear2025,
    2026: TaxYear2026,
}

def get_year(year: int):
    if year not in YEAR_REGISTRY:
        raise ValueError(f"Tax year {year} not supported. Available: {list(YEAR_REGISTRY)}")
    return YEAR_REGISTRY[year]()
