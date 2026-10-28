import asyncio
import os
from pathlib import Path

import pytest

from app.evaluation.quality import QualityMetric
from scripts.evaluate_generation import evaluate_generation_quality

TEST_DATA = Path(os.environ['DATA_DIR'])


def test_quality_metric_validation_is_explicit():
    assert QualityMetric.from_counts(0, 0).rate is None
    assert QualityMetric.from_counts(2, 4).rate == 0.5
    with pytest.raises(ValueError, match='cannot exceed'):
        QualityMetric(numerator=3, denominator=2, rate=1.0)
    with pytest.raises(ValueError, match='must equal'):
        QualityMetric(numerator=1, denominator=2, rate=1.0)
    with pytest.raises(ValueError, match='unknown rate'):
        QualityMetric(numerator=0, denominator=0, rate=0.0)


def test_generation_quality_corpus_passes_every_case():
    workspace = TEST_DATA / 'generation-quality-corpus'
    report = asyncio.run(evaluate_generation_quality(workspace))
    expected = {
        'case_success': (22, 22),
        'first_pass_proposal_validity': (5, 9),
        'repair_invocation': (3, 9),
        'repair_success': (3, 3),
        'source_import_validity': (12, 12),
        'production_build_success': (2, 2),
        'runtime_health': (2, 2),
        'verification_success': (2, 2),
        'publish_gate_decisions': (2, 2),
        'deterministic_hash_reuse': (5, 5),
    }
    for name, counts in expected.items():
        metric = getattr(report, name)
        assert (metric.numerator, metric.denominator) == counts, name
    assert report.case_success.rate == 1.0
    assert len({case.id for case in report.cases}) == 22
    assert all(case.passed and case.error is None for case in report.cases)
    assert str(workspace) not in report.model_dump_json()
