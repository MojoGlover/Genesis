"""
agent/api/routes.py — Math agent custom endpoints.

Mounted by server.py at boot. This is the OPEN slot for per-agent HTTP endpoints.
"""
from __future__ import annotations

import math as _math

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

router = APIRouter()

VALID_OPERATIONS = {"add", "subtract", "multiply", "divide"}


class SolveRequest(BaseModel):
    operation: str
    a: int = Field(ge=0, le=9)
    b: int = Field(ge=0, le=9)

    @field_validator("operation")
    @classmethod
    def operation_must_be_valid(cls, v: str) -> str:
        if v not in VALID_OPERATIONS:
            raise ValueError(f"operation must be one of: {', '.join(sorted(VALID_OPERATIONS))}")
        return v


class SolveResponse(BaseModel):
    result:    int
    operation: str
    input:     dict


@router.post("/solve", response_model=SolveResponse)
async def solve(req: SolveRequest):
    if req.operation == "divide" and req.b == 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Division by zero")

    if req.operation == "add":
        result = req.a + req.b
    elif req.operation == "subtract":
        result = req.a - req.b
    elif req.operation == "multiply":
        result = req.a * req.b
    elif req.operation == "divide":
        result = _math.floor(req.a / req.b)

    return SolveResponse(
        result=result,
        operation=req.operation,
        input={"a": req.a, "b": req.b},
    )
