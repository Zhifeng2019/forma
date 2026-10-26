"""Compile validated AppSpecs and scoped source into deterministic packages."""

from dataclasses import dataclass

from ..backend_engine import BACKEND_PATH, REQUIREMENTS_PATH, has_forma_api, validate_application
from ..jobs.idempotency import canonical_input_hash
from ..source_packages import validate_source_package
from .dependencies import compile_dependency_files
from .manifest import (
    build_manifest, normalize_source_files, normalize_spec_manifest, validate_manifest,
)
from .schema import AppSpecError, appspec_hash, parse_appspec
from .types import AppSpec


@dataclass(frozen=True)
class CompiledPackage:
    spec: AppSpec
    files: dict[str, str]
    manifest: dict
    spec_hash: str
    source_hash: str


def _compile_single_file(spec: AppSpec, source_files: dict[str, str]) -> dict[str, str]:
    files = dict(source_files)
    html = files.get('index.html', '')
    if spec.architecture.backend_mode == 'fastapi':
        html, python_source, requirements = validate_application(
            html, files.get(BACKEND_PATH, ''), spec.dependencies.python,
        )
        files.update({
            'index.html': html,
            BACKEND_PATH: python_source,
            REQUIREMENTS_PATH: requirements,
        })
        return files
    if not isinstance(html, str) or '<html' not in html.lower() or '</html>' not in html.lower():
        raise AppSpecError('The generated application was not a complete HTML document.')
    if len(html) > 250_000:
        raise AppSpecError('The generated application is too large. Split this phase into a smaller change.')
    if has_forma_api(html):
        raise AppSpecError('A frontend-only single-file application must not call a backend API.')
    files['index.html'] = html.strip()
    return files


def compile_package(
    spec: AppSpec | dict, source_files: dict[str, str] | None = None, phase: int = 1,
) -> CompiledPackage:
    """Validate cross-contract policy before returning any buildable source."""
    spec = normalize_spec_manifest(parse_appspec(spec))
    source_format = spec.architecture.source_format
    synthesized = source_files is None
    if synthesized:
        from .source import synthesize_source
        source_files = synthesize_source(spec, phase)
    files = normalize_source_files(source_files, source_format)
    files = compile_dependency_files(spec, files)
    validate_manifest(spec, files)
    if source_format == 'multi-file':
        files = validate_source_package(files, spec.architecture.backend_mode, spec.dependencies.python)
    else:
        files = _compile_single_file(spec, files)
    validate_manifest(spec, files)
    spec_hash = appspec_hash(spec)
    source_hash = canonical_input_hash(files)
    manifest = build_manifest(spec, files, spec_hash)
    manifest['source_hash'] = source_hash
    if synthesized:
        manifest['generation'] = {'mode': 'appspec', 'phase': phase}
    return CompiledPackage(spec, files, manifest, spec_hash, source_hash)
