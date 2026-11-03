"""Read-only compatibility with specifications stored by the retired AppSpec compiler."""

from .schema import AppSpecError, appspec_hash, parse_appspec
from .types import AppSpec

__all__ = ['AppSpec', 'AppSpecError', 'appspec_hash', 'parse_appspec']
