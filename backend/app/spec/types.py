"""Typed, versioned Application Specification contracts."""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SpecModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ProductSpec(SpecModel):
    name: str = Field(min_length=1, max_length=120)
    brief: str = Field(min_length=1, max_length=12_000)
    users: list[str] = Field(default_factory=list, max_length=12)
    primary_workflow: str = Field(min_length=1, max_length=2000)
    acceptance_goals: list[str] = Field(default_factory=list, max_length=12)


class ArchitectureSpec(SpecModel):
    backend_mode: Literal['static', 'fastapi']
    source_format: Literal['single-file', 'multi-file']
    state_ownership: Literal['browser', 'server']


class EntityFieldSpec(SpecModel):
    name: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    kind: Literal['string', 'text', 'integer', 'number', 'boolean', 'date', 'datetime', 'uuid']
    required: bool = True
    constraints: dict[str, str | int | float | bool] = Field(default_factory=dict)


class EntitySpec(SpecModel):
    name: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]*$')
    fields: list[EntityFieldSpec] = Field(min_length=1, max_length=24)
    relationships: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def unique_fields(self) -> Self:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f'Entity {self.name} contains duplicate fields')
        return self


class ApiOperationSpec(SpecModel):
    name: str = Field(min_length=1, max_length=120)
    method: Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
    path: str = Field(pattern=r'^/api(?:/|$)')
    entity: str | None = None
    errors: list[str] = Field(default_factory=list, max_length=12)


class FrontendSpec(SpecModel):
    components: list[str] = Field(default_factory=list, max_length=32)
    routes: list[str] = Field(default_factory=list, max_length=32)
    state_adapter: Literal['browser-local', 'forma-api']
    accessibility: list[str] = Field(default_factory=list, max_length=16)


class DependencySpec(SpecModel):
    python: list[str] = Field(default_factory=list, max_length=16)
    npm: list[str] = Field(default_factory=list, max_length=16)

    @field_validator('python', 'npm')
    @classmethod
    def unversioned_names(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError('Dependencies must not contain duplicates')
        for value in values:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+|@[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
                raise ValueError(f'Dependency must be an unversioned reviewed package name: {value}')
        return values


class ManifestFileSpec(SpecModel):
    path: str = Field(min_length=1, max_length=240)
    owner: Literal['supervisor', 'frontend', 'backend', 'legacy']
    max_bytes: int = Field(default=140_000, ge=1, le=250_000)


class ManifestSpec(SpecModel):
    files: list[ManifestFileSpec] = Field(min_length=1, max_length=24)
    generation_order: list[str] = Field(default_factory=list, max_length=24)


class AcceptanceCheckSpec(SpecModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal['build', 'api', 'persistence', 'browser', 'migration', 'security']
    target: str = Field(min_length=1, max_length=240)


class AppSpec(SpecModel):
    schema_version: Literal['1.0'] = '1.0'
    compiler_version: Literal['1.0'] = '1.0'
    product: ProductSpec
    architecture: ArchitectureSpec
    entities: list[EntitySpec] = Field(default_factory=list, max_length=16)
    api: list[ApiOperationSpec] = Field(default_factory=list, max_length=32)
    frontend: FrontendSpec
    dependencies: DependencySpec = Field(default_factory=DependencySpec)
    manifest: ManifestSpec
    acceptance: list[AcceptanceCheckSpec] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def consistent_contract(self) -> Self:
        architecture = self.architecture
        expected_state = 'server' if architecture.backend_mode == 'fastapi' else 'browser'
        expected_adapter = 'forma-api' if architecture.backend_mode == 'fastapi' else 'browser-local'
        if architecture.state_ownership != expected_state:
            raise ValueError(f'{architecture.backend_mode} architecture requires {expected_state} state ownership')
        if self.frontend.state_adapter != expected_adapter:
            raise ValueError(f'{architecture.backend_mode} architecture requires the {expected_adapter} frontend adapter')
        if architecture.backend_mode == 'static' and self.dependencies.python:
            raise ValueError('Frontend-only applications cannot declare Python dependencies')
        if architecture.source_format == 'single-file' and self.dependencies.npm:
            raise ValueError('Single-file applications cannot declare npm dependencies')

        entity_names = [entity.name for entity in self.entities]
        if len(entity_names) != len(set(entity_names)):
            raise ValueError('AppSpec contains duplicate entity names')
        known_entities = set(entity_names)
        for entity in self.entities:
            unknown = set(entity.relationships) - known_entities
            if unknown:
                raise ValueError(f'Entity {entity.name} references unknown entities: {", ".join(sorted(unknown))}')
        operation_keys = set()
        api_paths = set()
        for operation in self.api:
            if operation.entity and operation.entity not in known_entities:
                raise ValueError(f'API operation {operation.name} references unknown entity {operation.entity}')
            key = (operation.method, operation.path)
            if key in operation_keys:
                raise ValueError(f'Duplicate API operation: {operation.method} {operation.path}')
            operation_keys.add(key)
            api_paths.add(operation.path)
        for check in self.acceptance:
            if check.kind == 'api' and check.target.startswith('/api') and check.target not in api_paths:
                raise ValueError(f'Acceptance check {check.name} references unknown API path {check.target}')

        manifest_paths = [item.path for item in self.manifest.files]
        if len(manifest_paths) != len(set(manifest_paths)):
            raise ValueError('AppSpec manifest contains duplicate paths')
        if len(self.manifest.generation_order) != len(set(self.manifest.generation_order)):
            raise ValueError('Manifest generation order contains duplicate paths')
        unknown_paths = set(self.manifest.generation_order) - set(manifest_paths)
        if unknown_paths:
            raise ValueError(f'Generation order references undeclared paths: {", ".join(sorted(unknown_paths))}')
        return self
