import pytest
from pydantic import ValidationError

from app.config import Settings
from app.features import FeatureDisabledError, FeatureFlag, enabled_features, feature_enabled, require_feature


def test_flags_default_to_standard_behavior():
    config = Settings(durable_jobs_v1=False, sandbox_v1=False)
    assert enabled_features(config) == frozenset()
    for flag in FeatureFlag:
        assert feature_enabled(flag, config) is False


def test_one_flag_does_not_enable_other_workstreams():
    config = Settings(durable_jobs_v1=True, sandbox_v1=False)
    assert feature_enabled(FeatureFlag.DURABLE_JOBS_V1, config) is True
    assert enabled_features(config) == frozenset({FeatureFlag.DURABLE_JOBS_V1})
    require_feature(FeatureFlag.DURABLE_JOBS_V1, config)
    with pytest.raises(FeatureDisabledError, match='sandbox_v1'):
        require_feature(FeatureFlag.SANDBOX_V1, config)


def test_invalid_boolean_flag_is_rejected():
    with pytest.raises(ValidationError):
        Settings(durable_jobs_v1='not-a-boolean')
