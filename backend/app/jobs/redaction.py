"""Shared redaction for tool output and persisted provenance."""

import re
from urllib.parse import urlsplit, urlunsplit

_SECRET = re.compile(r'(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s,;]+)')
_BEARER = re.compile(r'(?i)(bearer\s+)([a-z0-9._~+/=-]+)')
_URL = re.compile(r'https?://[^\s]+')
_SENSITIVE_KEYS = {'api_key', 'apikey', 'access_token', 'token', 'secret', 'password', 'authorization'}


def redact_output(text: str) -> str:
    text = _SECRET.sub(r'\1\2<redacted>', text)
    text = _BEARER.sub(r'\1<redacted>', text)

    def redact_url(match):
        raw = match.group(0)
        try:
            parts = urlsplit(raw)
            if not parts.hostname:
                return '<redacted-url>'
            host = parts.hostname
            if parts.port:
                host += f':{parts.port}'
            return urlunsplit((parts.scheme, host, parts.path, '', ''))
        except ValueError:
            return '<redacted-url>'
    return _URL.sub(redact_url, text)


def redact_metadata(value):
    """Recursively remove credentials while retaining non-sensitive provenance."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key)
            normalized = name.lower().replace('-', '_')
            sensitive = normalized in _SENSITIVE_KEYS or normalized.endswith(
                ('_api_key', '_access_token', '_secret', '_password'),
            )
            result[name] = '<redacted>' if sensitive else redact_metadata(item)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_metadata(item) for item in value]
    if isinstance(value, str):
        return redact_output(value)[:4000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]
