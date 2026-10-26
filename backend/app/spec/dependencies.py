"""Studio-owned dependency compilation for AppSpec packages."""

import re

from ..backend_engine import REQUIREMENTS_PATH, reviewed_requirements
from ..source_packages import FRONTEND_DEPENDENCIES, frontend_package_json, frontend_vite_config
from .schema import AppSpecError
from .types import AppSpec


def compile_dependency_files(spec: AppSpec, source_files: dict[str, str]) -> dict[str, str]:
    files = dict(source_files)
    architecture = spec.architecture
    if architecture.source_format == 'multi-file':
        expected_npm = set(FRONTEND_DEPENDENCIES)
        requested_npm = set(spec.dependencies.npm)
        if requested_npm != expected_npm:
            missing = sorted(expected_npm - requested_npm)
            extra = sorted(requested_npm - expected_npm)
            raise AppSpecError(f'Multi-file npm dependencies must match the reviewed set; missing={missing}, unsupported={extra}')
        files['frontend/package.json'] = frontend_package_json()
        files['frontend/vite.config.js'] = frontend_vite_config()
    normalized_python = set()
    for package in spec.dependencies.python:
        normalized = re.sub(r'[-_.]+', '-', package).lower()
        if normalized in normalized_python:
            raise AppSpecError(f'Duplicate Python dependency after normalization: {package}')
        normalized_python.add(normalized)
    if architecture.backend_mode == 'fastapi':
        files[REQUIREMENTS_PATH] = reviewed_requirements(spec.dependencies.python)
    return files
