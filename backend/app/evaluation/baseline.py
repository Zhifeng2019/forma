"""Validation for current and legacy evaluation baseline documents."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReportModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SuiteResult(ReportModel):
    status: Literal['passed', 'failed', 'skipped']
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    reason: str | None = None

    @model_validator(mode='after')
    def validate_outcome(self):
        if self.status == 'skipped':
            if not self.reason or not self.reason.strip():
                raise ValueError('A skipped suite must include a reason')
            if self.passed or self.failed or self.duration_ms:
                raise ValueError('A skipped suite cannot contain results or duration')
        elif self.reason is not None:
            raise ValueError('Only a skipped suite can include a skip reason')
        if self.status == 'passed' and self.failed:
            raise ValueError('A passed suite cannot contain failed tests')
        return self


class SuiteResults(ReportModel):
    backend: SuiteResult
    frontend_unit: SuiteResult
    browser: SuiteResult
    provider_smoke: SuiteResult


class Compatibility(ReportModel):
    source_formats: list[Literal['single-file', 'multi-file']]
    backend_modes: list[Literal['static', 'fastapi']]
    publish_states: list[Literal['published', 'unpublished']]
    history_states: list[Literal['current', 'historical']]
    fixtures: list[str]


class FeatureFlags(ReportModel):
    durable_jobs_v1: bool
    appspec_v1: bool
    acceptance_gate_v1: bool
    specialist_workers_v1: bool
    sandbox_v1: bool


class EnvironmentMetadata(ReportModel):
    python_version: str = Field(min_length=1)
    node_version: str = Field(min_length=1)
    system: str = Field(min_length=1)
    machine: str = Field(min_length=1)


class BaselineDocument(ReportModel):
    captured_at: datetime
    source: str = Field(min_length=1)
    suites: SuiteResults
    compatibility: Compatibility

    @field_validator('captured_at')
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('captured_at must include a timezone')
        return value


class LegacyBaselineReport(BaselineDocument):
    """The original report remains valid without fabricated capture metadata."""

    schema_version: Literal['1.0']


class BaselineReport(BaselineDocument):
    """Current capture contract with explicit reproducibility provenance."""

    schema_version: Literal['1.1']
    source_revision: str = Field(pattern=r'^[0-9a-f]{40}$')
    dirty_tree: bool
    feature_flags: FeatureFlags
    environment: EnvironmentMetadata
    fixture_pack_version: str = Field(min_length=1)


def parse_baseline(document: dict) -> BaselineReport | LegacyBaselineReport:
    if not isinstance(document, dict):
        raise ValueError('A baseline report must be a JSON object')
    version = document.get('schema_version')
    if version == '1.0':
        return LegacyBaselineReport.model_validate(document)
    if version == '1.1':
        return BaselineReport.model_validate(document)
    raise ValueError(f'Unsupported baseline schema version: {version!r}')
