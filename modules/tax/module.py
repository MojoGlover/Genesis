"""
tax — GENESIS Capability Module
=================================
US federal tax calculator for 2024, 2025 (primary), and 2026 (TCJA-sunset projected).

Entries persist across year switches — set income/deductions once,
compare results across years without re-entering data.

Auto-discovered by GENESIS ModuleRegistry at startup.
Drop this folder in modules/ and restart — no other file changes needed.

HTTP Endpoints (mounted at /tax/...):
    POST /tax/calculate          Calculate taxes for a specific year
    POST /tax/compare            Side-by-side 2024 / 2025 / 2026
    GET  /tax/concepts           All tax term definitions
    GET  /tax/concepts/{term}    Single term definition
    POST /tax/schedule_c         Calculate Schedule C net profit
    GET  /tax/years              Supported years + projection warnings

Session state is per-request (stateless HTTP). For persistent sessions,
pass your entries on every request or use the export/import pattern.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from modules.base import ModuleBase

# Engine lives in the engine/ sub-package
from modules.tax.engine.calculator import TaxCalculator
from modules.tax.engine.concepts import TAX_CONCEPTS
from modules.tax.engine.forms.schedule_c import ScheduleC

logger = logging.getLogger(__name__)


# ─── Request / Response Models ────────────────────────────────────────────────

class IncomeInput(BaseModel):
    w2:                   float = 0.0
    freelance:            float = 0.0
    business_net:         float = 0.0
    interest:             float = 0.0
    ordinary_dividends:   float = 0.0
    qualified_dividends:  float = 0.0
    lt_capital_gains:     float = 0.0
    st_capital_gains:     float = 0.0
    rental_net:           float = 0.0
    social_security:      float = 0.0
    pension_annuity:      float = 0.0
    ira_distribution:     float = 0.0
    other:                float = 0.0


class DeductionInput(BaseModel):
    ira_contribution:         float = 0.0
    student_loan_interest:    float = 0.0
    hsa_contribution:         float = 0.0
    self_employed_health_ins: float = 0.0
    educator_expenses:        float = 0.0
    alimony_paid:             float = 0.0
    state_income_tax:         float = 0.0
    property_tax:             float = 0.0
    mortgage_interest:        float = 0.0
    points_paid:              float = 0.0
    mortgage_insurance:       float = 0.0
    charity_cash:             float = 0.0
    charity_noncash:          float = 0.0
    medical_expenses:         float = 0.0
    investment_interest:      float = 0.0
    casualty_losses:          float = 0.0


class CreditInput(BaseModel):
    child_tax_credit_children:  int   = 0
    child_care_expenses:        float = 0.0
    child_care_dependents:      int   = 0
    education_credit:           float = 0.0
    retirement_savings_credit:  float = 0.0
    ev_credit:                  float = 0.0
    other_credits:              float = 0.0


class WithholdingInput(BaseModel):
    federal:             float = 0.0
    estimated_payments:  float = 0.0


class TaxRequest(BaseModel):
    year:            int            = Field(2025, description="2024, 2025, or 2026")
    filing_status:   str            = Field("single", description="single | mfj | mfs | hoh")
    taxpayer_age:    int            = Field(40)
    num_dependents:  int            = Field(0)
    income:          IncomeInput    = Field(default_factory=IncomeInput)
    deductions:      DeductionInput = Field(default_factory=DeductionInput)
    credits:         CreditInput    = Field(default_factory=CreditInput)
    withholding:     WithholdingInput = Field(default_factory=WithholdingInput)


class CompareRequest(BaseModel):
    years:           List[int]      = Field([2024, 2025, 2026])
    filing_status:   str            = Field("single")
    taxpayer_age:    int            = Field(40)
    num_dependents:  int            = Field(0)
    income:          IncomeInput    = Field(default_factory=IncomeInput)
    deductions:      DeductionInput = Field(default_factory=DeductionInput)
    credits:         CreditInput    = Field(default_factory=CreditInput)
    withholding:     WithholdingInput = Field(default_factory=WithholdingInput)


class ScheduleCRequest(BaseModel):
    business_name:              str   = "My Business"
    gross_receipts:             float = 0.0
    returns_allowances:         float = 0.0
    cogs:                       float = 0.0
    other_income:               float = 0.0
    advertising:                float = 0.0
    car_and_truck:              float = 0.0
    commissions_fees:           float = 0.0
    contract_labor:             float = 0.0
    depreciation_179:           float = 0.0
    insurance:                  float = 0.0
    legal_professional:         float = 0.0
    office:                     float = 0.0
    rent_vehicles_equip:        float = 0.0
    rent_other_property:        float = 0.0
    repairs_maintenance:        float = 0.0
    supplies:                   float = 0.0
    taxes_licenses:             float = 0.0
    travel:                     float = 0.0
    meals:                      float = 0.0
    utilities:                  float = 0.0
    wages:                      float = 0.0
    software_subscriptions:     float = 0.0
    phone_internet:             float = 0.0
    education_training:         float = 0.0
    other_expenses:             float = 0.0
    home_office_sqft:           float = 0.0
    home_total_sqft:            float = 0.0
    home_expenses:              float = 0.0
    use_simplified_home_office: bool  = False
    business_miles:             float = 0.0
    mileage_rate:               float = 0.70


# ─── Helper ───────────────────────────────────────────────────────────────────

def _build_calculator(req: TaxRequest | CompareRequest) -> TaxCalculator:
    """Build a TaxCalculator from a request body."""
    calc = TaxCalculator(
        filing_status=req.filing_status,
        taxpayer_age=req.taxpayer_age,
        num_dependents=req.num_dependents,
        default_year=getattr(req, "year", 2025),
    )
    calc.set_income(**req.income.dict())
    calc.set_deductions(**req.deductions.dict())
    calc.set_credits(**req.credits.dict())
    calc.set_withholding(
        federal=req.withholding.federal,
        estimated_payments=req.withholding.estimated_payments,
    )
    return calc


# ─── Module ───────────────────────────────────────────────────────────────────

class Module(ModuleBase):
    """GENESIS tax capability module."""

    def __init__(self) -> None:
        self._request_count: int = 0
        self._error_count:   int = 0

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "tax"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return (
            "US federal tax calculator — 2024, 2025 (primary), 2026 (TCJA-sunset projected). "
            "Supports W-2, self-employment, investments, Schedule C. "
            "Entries persist across year switches."
        )

    @property
    def tags(self) -> List[str]:
        return ["tax", "finance", "calculator"]

    # ── Routes ────────────────────────────────────────────────────────────────

    @property
    def router(self) -> APIRouter:
        r = APIRouter(prefix="/tax", tags=["tax"])

        # ── POST /tax/calculate ───────────────────────────────────────────────
        @r.post("/calculate", summary="Calculate federal taxes for a single year")
        async def calculate(req: TaxRequest):
            try:
                calc = _build_calculator(req)
                result = calc.calculate(req.year)
                self._request_count += 1
                return {
                    "year":             result.year,
                    "filing_status":    result.filing_status,
                    "is_projected":     result.is_projected,
                    "projection_warning": result.projection_warning or None,
                    "summary":          result.summary(),
                    "data":             result.to_dict(),
                }
            except Exception as exc:
                self._error_count += 1
                logger.error(f"[tax] calculate error: {exc}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /tax/compare ─────────────────────────────────────────────────
        @r.post("/compare", summary="Side-by-side comparison across years")
        async def compare(req: CompareRequest):
            try:
                calc = _build_calculator(req)
                results = {}
                for yr in req.years:
                    if yr not in (2024, 2025, 2026):
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unsupported year: {yr}. Use 2024, 2025, or 2026."
                        )
                    r = calc.calculate(yr)
                    results[str(yr)] = r.to_dict()

                self._request_count += 1
                return {
                    "years":      req.years,
                    "comparison": calc.compare_years(req.years),
                    "detail":     results,
                    "note": (
                        "2026 values are TCJA-sunset projections — "
                        "verify before use if legislation changes."
                        if 2026 in req.years else None
                    ),
                }
            except HTTPException:
                raise
            except Exception as exc:
                self._error_count += 1
                logger.error(f"[tax] compare error: {exc}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /tax/concepts ─────────────────────────────────────────────────
        @r.get("/concepts", summary="All tax term definitions")
        async def get_concepts():
            return {"concepts": TAX_CONCEPTS, "count": len(TAX_CONCEPTS)}

        # ── GET /tax/concepts/{term} ──────────────────────────────────────────
        @r.get("/concepts/{term}", summary="Look up a single tax term")
        async def get_concept(term: str):
            key = term.lower().replace("-", "_").replace(" ", "_")
            concept = TAX_CONCEPTS.get(key)
            if concept:
                return concept
            # fuzzy match
            matches = {k: v for k, v in TAX_CONCEPTS.items() if key in k}
            if matches:
                return {"matches": matches}
            raise HTTPException(
                status_code=404,
                detail=f"Term '{term}' not found.",
            )

        # ── POST /tax/schedule_c ──────────────────────────────────────────────
        @r.post("/schedule_c", summary="Calculate Schedule C net profit/loss")
        async def schedule_c(req: ScheduleCRequest):
            try:
                sc = ScheduleC(**req.dict())
                net = sc.calculate()
                self._request_count += 1
                return {
                    "net_profit":  net,
                    "summary":     sc.summary(),
                    "detail":      sc.to_dict(),
                    "tip": (
                        "Pass net_profit as business_net in /tax/calculate "
                        "to include in your full tax picture."
                    ),
                }
            except Exception as exc:
                self._error_count += 1
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /tax/years ────────────────────────────────────────────────────
        @r.get("/years", summary="Supported tax years and notes")
        async def get_years():
            return {
                "supported": [2024, 2025, 2026],
                "primary": 2025,
                "years": {
                    "2024": {
                        "status": "final",
                        "filing_deadline": "April 15, 2025",
                        "standard_deduction": {"single": 14600, "mfj": 29200, "hoh": 21900},
                    },
                    "2025": {
                        "status": "final",
                        "filing_deadline": "April 15, 2026",
                        "standard_deduction": {"single": 15000, "mfj": 30000, "hoh": 22500},
                    },
                    "2026": {
                        "status": "⚠️ PROJECTED — TCJA-sunset scenario",
                        "filing_deadline": "April 15, 2027",
                        "standard_deduction": {"single": 8500, "mfj": 17000, "hoh": 12500},
                        "warning": (
                            "2026 values assume TCJA expires Dec 31, 2025. "
                            "If Congress extends TCJA, values will be closer to 2025. "
                            "Verify before use."
                        ),
                    },
                },
            }

        return r

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_startup(self) -> None:
        logger.info(
            f"[tax] module ready — years: 2024, 2025, 2026 | "
            f"routes: /tax/calculate, /tax/compare, /tax/concepts, "
            f"/tax/schedule_c, /tax/years"
        )

    async def on_shutdown(self) -> None:
        logger.info(
            f"[tax] shutdown — "
            f"{self._request_count} requests, {self._error_count} errors"
        )

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        return {
            "status":          "ok",
            "module":          self.name,
            "version":         self.version,
            "supported_years": [2024, 2025, 2026],
            "primary_year":    2025,
            "request_count":   self._request_count,
            "error_count":     self._error_count,
            "concepts_loaded": len(TAX_CONCEPTS),
        }
