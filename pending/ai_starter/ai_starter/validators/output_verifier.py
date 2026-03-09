"""Verify LLM outputs and tool results for quality and safety."""

import re
from typing import Any

from pydantic import BaseModel


class VerificationResult(BaseModel):
    """Result of output verification."""
    passed: bool
    confidence: float  # 0.0 to 1.0
    issues: list[str] = []
    metadata: dict[str, Any] = {}


class OutputVerifier:
    """Verifies LLM outputs and tool results."""

    @staticmethod
    def verify_json_format(text: str) -> VerificationResult:
        """Verify that output contains valid JSON."""
        import json
        
        # Try to find JSON in text
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if not json_match:
            return VerificationResult(
                passed=False,
                confidence=0.0,
                issues=["No JSON found in output"],
            )
        
        try:
            json.loads(json_match.group(0))
            return VerificationResult(passed=True, confidence=1.0)
        except json.JSONDecodeError as e:
            return VerificationResult(
                passed=False,
                confidence=0.0,
                issues=[f"Invalid JSON: {e}"],
            )

    @staticmethod
    def verify_tool_output(output: str, expected_patterns: list[str] | None = None) -> VerificationResult:
        """Verify tool output meets expectations."""
        issues = []
        
        # Check for errors
        if "error" in output.lower() or "failed" in output.lower():
            issues.append("Output contains error indicators")
        
        # Check expected patterns
        if expected_patterns:
            for pattern in expected_patterns:
                if not re.search(pattern, output, re.IGNORECASE):
                    issues.append(f"Missing expected pattern: {pattern}")
        
        passed = len(issues) == 0
        confidence = 1.0 if passed else 0.5
        
        return VerificationResult(
            passed=passed,
            confidence=confidence,
            issues=issues,
        )

    @staticmethod
    def verify_safety(text: str, blocked_patterns: list[str] | None = None) -> VerificationResult:
        """Verify output doesn't contain unsafe content."""
        blocked_patterns = blocked_patterns or [
            r'password\s*[:=]\s*\S+',
            r'api[_-]?key\s*[:=]\s*\S+',
            r'secret\s*[:=]\s*\S+',
            r'token\s*[:=]\s*\S+',
        ]
        
        issues = []
        for pattern in blocked_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                issues.append(f"Found potentially sensitive data: {pattern}")
        
        return VerificationResult(
            passed=len(issues) == 0,
            confidence=1.0 if len(issues) == 0 else 0.0,
            issues=issues,
        )

    @staticmethod
    def verify_completeness(text: str, min_length: int = 10) -> VerificationResult:
        """Verify output is complete and not truncated."""
        issues = []
        
        if len(text) < min_length:
            issues.append(f"Output too short (< {min_length} chars)")
        
        # Check for truncation indicators
        if text.endswith("...") or "truncated" in text.lower():
            issues.append("Output appears truncated")
        
        return VerificationResult(
            passed=len(issues) == 0,
            confidence=1.0 if len(issues) == 0 else 0.7,
            issues=issues,
        )
