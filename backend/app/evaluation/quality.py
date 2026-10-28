"""Deterministic generation-quality outcomes, independent of timing and provider availability."""

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualityModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class QualityMetric(QualityModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0, le=1)

    @classmethod
    def from_counts(cls, numerator: int, denominator: int) -> 'QualityMetric':
        return cls(numerator=numerator, denominator=denominator,
                   rate=None if denominator == 0 else numerator / denominator)

    @model_validator(mode='after')
    def validate_rate(self):
        if self.numerator > self.denominator:
            raise ValueError('Metric numerator cannot exceed its denominator')
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if expected is None:
            if self.rate is not None:
                raise ValueError('A zero-denominator metric must have an unknown rate')
        elif self.rate is None or not math.isclose(self.rate, expected, rel_tol=0, abs_tol=1e-12):
            raise ValueError('Metric rate must equal numerator divided by denominator')
        return self


class QualityCase(QualityModel):
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    passed: bool
    expected: str = Field(min_length=1)
    actual: str = Field(min_length=1)
    error: str | None = None


class GenerationQuality(QualityModel):
    schema_version: str = Field(default='1.0', pattern=r'^1\.0$')
    case_success: QualityMetric
    first_pass_proposal_validity: QualityMetric
    repair_invocation: QualityMetric
    repair_success: QualityMetric
    source_import_validity: QualityMetric
    production_build_success: QualityMetric
    runtime_health: QualityMetric
    verification_success: QualityMetric
    publish_gate_decisions: QualityMetric
    deterministic_hash_reuse: QualityMetric
    cases: list[QualityCase]
