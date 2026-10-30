"""Typed feature flags for optional studio infrastructure."""

from enum import StrEnum

from .config import Settings, settings


class FeatureFlag(StrEnum):
    DURABLE_JOBS_V1 = 'durable_jobs_v1'
    SANDBOX_V1 = 'sandbox_v1'


class FeatureDisabledError(RuntimeError):
    pass


def feature_enabled(flag: FeatureFlag, config: Settings | None = None) -> bool:
    config = config or settings
    return bool(getattr(config, flag.value))


def enabled_features(config: Settings | None = None) -> frozenset[FeatureFlag]:
    return frozenset(flag for flag in FeatureFlag if feature_enabled(flag, config))


def require_feature(flag: FeatureFlag, config: Settings | None = None) -> None:
    if not feature_enabled(flag, config):
        raise FeatureDisabledError(f'{flag.value} is not enabled on this studio')
