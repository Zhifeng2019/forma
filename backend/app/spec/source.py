"""Synthesize a complete application from a validated AppSpec."""

from .contract import entity_contract
from .schema import AppSpecError
from .source_backend import backend_sources
from .source_frontend import frontend_sources
from .types import AppSpec


def synthesize_source(spec: AppSpec, phase: int = 1) -> dict[str, str]:
    if phase not in {1, 2, 3}:
        raise AppSpecError('AppSpec source generation phase must be 1, 2, or 3.')
    contract = entity_contract(spec)
    files = frontend_sources(spec, contract, phase)
    if spec.architecture.backend_mode == 'fastapi':
        files.update(backend_sources(contract, spec.product.name, spec.architecture.source_format))
    return files
