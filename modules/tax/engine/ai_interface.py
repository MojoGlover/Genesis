"""
ai_interface.py — AI Tool Definition + Self-Registration
=========================================================
Defines the tax_engine as a callable tool for AI systems.
Compatible with:
  - OpenAI / LiteLLM function-calling format
  - Engineer0 local API (port 5001) tool registry
  - GENESIS tool registry (port 7860)
  - LangChain StructuredTool format
  - Generic REST endpoint format

SELF-REGISTRATION:
    auto_register() is called automatically when you do `import tax_engine`.
    It tries each registry in order and silently skips unavailable ones.
    Add your registry to the REGISTRIES list below.
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional

log = logging.getLogger("tax_engine")

# ─── Tool Definition (OpenAI / LiteLLM format) ───────────────────────────────

TaxEngineToolDef = {
    "type": "function",
    "function": {
        "name": "tax_calculator",
        "description": (
            "US federal tax calculator supporting tax years 2024, 2025 (primary), "
            "and 2026 (projected TCJA-sunset). Entries persist when switching years — "
            "set income/deductions once, compare across years. Returns full breakdown: "
            "gross income, AGI, taxable income, bracket detail, credits, SE tax, "
            "effective/marginal rates, and refund or amount owed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["calculate", "compare_years", "explain_concept",
                             "set_income", "set_deductions", "set_credits",
                             "set_withholding", "summary"],
                    "description": "What to do. Use 'calculate' for a single year result, "
                                   "'compare_years' for side-by-side 2024/2025/2026, "
                                   "'explain_concept' to define a tax term."
                },
                "year": {
                    "type": "integer",
                    "enum": [2024, 2025, 2026],
                    "description": "Tax year. Default 2025. 2026 values are TCJA-sunset projections."
                },
                "filing_status": {
                    "type": "string",
                    "enum": ["single", "mfj", "mfs", "hoh"],
                    "description": "single=Single, mfj=Married Filing Jointly, "
                                   "mfs=Married Filing Separately, hoh=Head of Household"
                },
                "income": {
                    "type": "object",
                    "description": "Income sources in dollars",
                    "properties": {
                        "w2":                  {"type": "number", "description": "W-2 wages"},
                        "freelance":           {"type": "number", "description": "1099-NEC / freelance"},
                        "business_net":        {"type": "number", "description": "Schedule C net profit"},
                        "interest":            {"type": "number", "description": "Interest income"},
                        "ordinary_dividends":  {"type": "number"},
                        "qualified_dividends": {"type": "number"},
                        "lt_capital_gains":    {"type": "number", "description": "Long-term capital gains"},
                        "st_capital_gains":    {"type": "number", "description": "Short-term capital gains"},
                        "rental_net":          {"type": "number"},
                        "social_security":     {"type": "number"},
                        "pension_annuity":     {"type": "number"},
                        "ira_distribution":    {"type": "number"},
                        "other":               {"type": "number"},
                    }
                },
                "deductions": {
                    "type": "object",
                    "description": "Deductions — above-the-line and Schedule A itemized",
                    "properties": {
                        "ira_contribution":         {"type": "number"},
                        "student_loan_interest":    {"type": "number"},
                        "hsa_contribution":         {"type": "number"},
                        "self_employed_health_ins": {"type": "number"},
                        "educator_expenses":        {"type": "number"},
                        "state_income_tax":         {"type": "number"},
                        "property_tax":             {"type": "number"},
                        "mortgage_interest":        {"type": "number"},
                        "charity_cash":             {"type": "number"},
                        "charity_noncash":          {"type": "number"},
                        "medical_expenses":         {"type": "number"},
                    }
                },
                "credits": {
                    "type": "object",
                    "properties": {
                        "child_tax_credit_children": {"type": "integer"},
                        "child_care_expenses":       {"type": "number"},
                        "education_credit":          {"type": "number"},
                        "ev_credit":                 {"type": "number"},
                        "other_credits":             {"type": "number"},
                    }
                },
                "withholding": {
                    "type": "object",
                    "properties": {
                        "federal":             {"type": "number", "description": "W-2 Box 2 total"},
                        "estimated_payments":  {"type": "number", "description": "Quarterly payments made"},
                    }
                },
                "concept": {
                    "type": "string",
                    "description": "Tax concept to explain (for action=explain_concept). "
                                   "E.g. 'agi', 'qbi', 'salt', 'tcja', 'amt'"
                },
                "num_dependents": {
                    "type": "integer",
                    "description": "Number of dependents (for personal exemption calc in 2026)"
                },
                "taxpayer_age": {
                    "type": "integer",
                    "description": "Taxpayer age (affects catchup contribution limits)"
                },
            },
            "required": ["action"],
        }
    }
}


# ─── Tool Executor ────────────────────────────────────────────────────────────

# Module-level calculator instance — persists across calls within a session
_session_calculator = None


def execute_tool(params: dict) -> dict:
    """
    Execute a tax_engine tool call from an AI system.
    Returns a JSON-serializable dict.
    """
    global _session_calculator

    action = params.get("action", "calculate")
    year = params.get("year", 2025)
    filing_status = params.get("filing_status", "single")
    num_dependents = params.get("num_dependents", 0)
    taxpayer_age = params.get("taxpayer_age", 40)

    # Import here to avoid circular at module load
    from tax_engine.calculator import TaxCalculator
    from tax_engine.concepts import TAX_CONCEPTS

    # ── Initialize or update session calculator ───────────────────────────────
    if _session_calculator is None:
        _session_calculator = TaxCalculator(
            filing_status=filing_status,
            taxpayer_age=taxpayer_age,
            num_dependents=num_dependents,
            default_year=year,
        )
    else:
        # Update filing status if provided
        if "filing_status" in params:
            _session_calculator.set_filing_status(filing_status)
        _session_calculator.num_dependents = num_dependents
        _session_calculator.taxpayer_age = taxpayer_age

    calc = _session_calculator

    # ── Apply income if provided ──────────────────────────────────────────────
    if "income" in params and params["income"]:
        calc.set_income(**params["income"])

    # ── Apply deductions if provided ──────────────────────────────────────────
    if "deductions" in params and params["deductions"]:
        calc.set_deductions(**params["deductions"])

    # ── Apply credits if provided ─────────────────────────────────────────────
    if "credits" in params and params["credits"]:
        calc.set_credits(**params["credits"])

    # ── Apply withholding if provided ─────────────────────────────────────────
    if "withholding" in params and params["withholding"]:
        calc.set_withholding(**params["withholding"])

    # ── Execute action ────────────────────────────────────────────────────────

    if action == "calculate" or action == "summary":
        result = calc.calculate(year)
        return {
            "year": result.year,
            "is_projected": result.is_projected,
            "summary": result.summary(),
            "data": result.to_dict(),
        }

    elif action == "compare_years":
        return {
            "comparison": calc.compare_years([2024, 2025, 2026]),
            "note": "2026 values are TCJA-sunset projections.",
        }

    elif action == "explain_concept":
        concept_key = params.get("concept", "").lower().replace(" ", "_").replace("-", "_")
        concept = TAX_CONCEPTS.get(concept_key)
        if concept:
            return {"concept": concept}
        # fuzzy search
        matches = {k: v for k, v in TAX_CONCEPTS.items() if concept_key in k}
        if matches:
            return {"matches": matches}
        return {
            "error": f"Concept '{concept_key}' not found.",
            "available": list(TAX_CONCEPTS.keys()),
        }

    elif action == "set_income":
        return {"status": "income updated", "entries": calc.export_entries()["income"]}

    elif action == "set_deductions":
        return {"status": "deductions updated", "entries": calc.export_entries()["deductions"]}

    elif action == "set_credits":
        return {"status": "credits updated", "entries": calc.export_entries()["credits"]}

    elif action == "set_withholding":
        return {"status": "withholding updated",
                "federal": calc._federal_withholding,
                "estimated": calc._estimated_payments}

    else:
        return {"error": f"Unknown action: {action}"}


# ─── Self-Registration ────────────────────────────────────────────────────────

def _register_engineer0() -> bool:
    """Try to register with Engineer0 local API (port 5001)."""
    import urllib.request
    payload = json.dumps({
        "tool_name": "tax_calculator",
        "tool_def": TaxEngineToolDef,
        "endpoint": "tax_engine://execute",  # local module call
        "version": "1.0.0",
        "description": "US federal tax calculator 2024/2025/2026",
    }).encode()
    req = urllib.request.Request(
        "http://localhost:5001/tools/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    urllib.request.urlopen(req, timeout=2)
    return True


def _register_genesis() -> bool:
    """Try to register with GENESIS (port 7860)."""
    import urllib.request
    payload = json.dumps({
        "plugin": "tax_engine",
        "tools": [TaxEngineToolDef],
        "version": "1.0.0",
    }).encode()
    req = urllib.request.Request(
        "http://localhost:7860/api/plugins/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    urllib.request.urlopen(req, timeout=2)
    return True


def _register_generic_file() -> bool:
    """
    Write tool definition to ~/.ai_tools/tax_engine.json
    Any tool-discovery system watching that dir will pick it up.
    """
    import os, pathlib
    tools_dir = pathlib.Path.home() / ".ai_tools"
    tools_dir.mkdir(exist_ok=True)
    tool_path = tools_dir / "tax_engine.json"
    tool_path.write_text(json.dumps({
        "tool": TaxEngineToolDef,
        "module": "tax_engine",
        "execute_fn": "tax_engine.ai_interface.execute_tool",
        "version": "1.0.0",
    }, indent=2))
    return True


def _register_langchain() -> bool:
    """Register as a LangChain StructuredTool if langchain is installed."""
    from langchain.tools import StructuredTool
    from langchain.tools.base import BaseTool  # noqa

    tool = StructuredTool.from_function(
        func=execute_tool,
        name="tax_calculator",
        description=TaxEngineToolDef["function"]["description"],
    )
    # Try to add to any active agent executor — best-effort
    try:
        import langchain
        if hasattr(langchain, "_tool_registry"):
            langchain._tool_registry["tax_calculator"] = tool
    except Exception:
        pass
    return True


# ── Registry list — add yours here ───────────────────────────────────────────
REGISTRIES = [
    ("Engineer0 (port 5001)",    _register_engineer0),
    ("GENESIS (port 7860)",      _register_genesis),
    ("Generic ~/.ai_tools file", _register_generic_file),
    ("LangChain StructuredTool", _register_langchain),
]


def auto_register(verbose: bool = False) -> Dict[str, bool]:
    """
    Try each registry. Called automatically on `import tax_engine`.
    Returns a dict of {registry_name: success_bool}.
    Set verbose=True to see results; otherwise runs silently.
    """
    results = {}
    for name, fn in REGISTRIES:
        try:
            fn()
            results[name] = True
            if verbose:
                log.info(f"✓ tax_engine registered with {name}")
        except Exception as e:
            results[name] = False
            if verbose:
                log.debug(f"  tax_engine: skipped {name} ({type(e).__name__})")
    return results


# ─── REST Endpoint Shim (for FastAPI / Flask integration) ────────────────────

def make_fastapi_router():
    """
    Returns a FastAPI router that exposes tax_engine as an HTTP API.
    Usage in your FastAPI app:
        from tax_engine.ai_interface import make_fastapi_router
        app.include_router(make_fastapi_router(), prefix="/tax")
    """
    try:
        from fastapi import APIRouter
        from pydantic import BaseModel

        router = APIRouter(tags=["tax_engine"])

        class ToolCall(BaseModel):
            action: str = "calculate"
            year: Optional[int] = 2025
            filing_status: Optional[str] = "single"
            income: Optional[Dict[str, Any]] = None
            deductions: Optional[Dict[str, Any]] = None
            credits: Optional[Dict[str, Any]] = None
            withholding: Optional[Dict[str, Any]] = None
            concept: Optional[str] = None
            num_dependents: Optional[int] = 0
            taxpayer_age: Optional[int] = 40

        @router.post("/calculate")
        def calculate_endpoint(call: ToolCall):
            return execute_tool(call.dict(exclude_none=True))

        @router.get("/tool_def")
        def get_tool_def():
            return TaxEngineToolDef

        @router.get("/concepts")
        def get_concepts():
            from tax_engine.concepts import TAX_CONCEPTS
            return TAX_CONCEPTS

        return router

    except ImportError:
        raise RuntimeError("FastAPI not installed. Run: pip install fastapi")
