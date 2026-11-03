"""Read-only review of historical AppSpec artifacts."""

import json

from .schema import (
    APPSPEC_SCHEMA_VERSION, COMPILER_VERSION, AppSpecError, appspec_hash, parse_appspec,
)


def appspec_review(content: str | None) -> dict:
    if content is None:
        return {'appspec': None, 'appspec_valid': None, 'appspec_error': None}
    try:
        envelope = json.loads(content)
        if not isinstance(envelope, dict):
            raise AppSpecError('AppSpec review requires a JSON object envelope.')
        if envelope.get('schema_version') != APPSPEC_SCHEMA_VERSION:
            raise AppSpecError('Unsupported AppSpec schema version.')
        if envelope.get('compiler_version') != COMPILER_VERSION:
            raise AppSpecError('Unsupported AppSpec compiler version.')
        spec = parse_appspec(envelope.get('spec'))
        if envelope.get('spec_hash') != appspec_hash(spec):
            raise AppSpecError('AppSpec content hash does not match the stored contract.')
        return {'appspec': envelope, 'appspec_valid': True, 'appspec_error': None}
    except (json.JSONDecodeError, AppSpecError, TypeError, AttributeError) as exc:
        return {'appspec': None, 'appspec_valid': False, 'appspec_error': str(exc)}
