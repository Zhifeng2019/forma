import pytest

from app.evaluation.quality import QualityMetric


def test_quality_metric_validation_is_explicit():
    assert QualityMetric.from_counts(0, 0).rate is None
    assert QualityMetric.from_counts(2, 4).rate == 0.5
    with pytest.raises(ValueError, match='cannot exceed'):
        QualityMetric(numerator=3, denominator=2, rate=1.0)
    with pytest.raises(ValueError, match='must equal'):
        QualityMetric(numerator=1, denominator=2, rate=1.0)
    with pytest.raises(ValueError, match='unknown rate'):
        QualityMetric(numerator=0, denominator=0, rate=0.0)
