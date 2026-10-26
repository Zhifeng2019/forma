"""AppSpec parsing, content hashing, and persisted document envelopes."""

import json

from pydantic import ValidationError

from ..jobs.idempotency import canonical_input_hash
from ..llm import GenerationError
from .types import AppSpec

APPSPEC_SCHEMA_VERSION = '1.0'
COMPILER_VERSION = '1.0'
APPSPEC_PATH = 'appspec.json'
BUILD_MANIFEST_PATH = 'build-manifest.json'
SPEC_ARTIFACT_PATHS = (APPSPEC_PATH, BUILD_MANIFEST_PATH)


class AppSpecError(GenerationError):
    """An AppSpec cannot be validated or compiled under studio policy."""


def parse_appspec(value: AppSpec | dict) -> AppSpec:
    if isinstance(value, AppSpec):
        return value
    try:
        return AppSpec.model_validate(value)
    except ValidationError as exc:
        details = []
        for error in exc.errors()[:8]:
            location = '.'.join(str(part) for part in error['loc']) or 'spec'
            details.append(f'{location}: {error["msg"]}')
        suffix = '; '.join(details)
        if len(exc.errors()) > 8:
            suffix += f'; and {len(exc.errors()) - 8} more errors'
        raise AppSpecError(f'Invalid AppSpec — {suffix}') from exc


def appspec_hash(spec: AppSpec) -> str:
    return canonical_input_hash(spec.model_dump(mode='json', exclude_none=True))


def appspec_document(spec: AppSpec) -> str:
    document = {
        'schema_version': APPSPEC_SCHEMA_VERSION,
        'compiler_version': COMPILER_VERSION,
        'spec_hash': appspec_hash(spec),
        'spec': spec.model_dump(mode='json', exclude_none=True),
    }
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
