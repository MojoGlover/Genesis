"""Pydantic-based schema validation for inputs and outputs."""

from typing import Any, Type

from pydantic import BaseModel, ValidationError


class ValidationResult(BaseModel):
    """Result of validation check."""
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


class SchemaValidator:
    """Validates data against Pydantic schemas."""

    @staticmethod
    def validate(data: dict[str, Any], schema: Type[BaseModel]) -> ValidationResult:
        """Validate data against a Pydantic model."""
        try:
            schema(**data)
            return ValidationResult(valid=True)
        except ValidationError as e:
            errors = [f"{err['loc'][0]}: {err['msg']}" for err in e.errors()]
            return ValidationResult(valid=False, errors=errors)

    @staticmethod
    def validate_tool_args(
        args: dict[str, Any],
        required: list[str],
        optional: list[str] | None = None,
    ) -> ValidationResult:
        """Validate tool arguments."""
        optional = optional or []
        errors = []
        warnings = []

        # Check required args
        for arg in required:
            if arg not in args:
                errors.append(f"Missing required argument: {arg}")

        # Check for unknown args
        known_args = set(required) | set(optional)
        for arg in args:
            if arg not in known_args:
                warnings.append(f"Unknown argument: {arg}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
