import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.baseline import BaselineReport, BaselineReportV1_1, LegacyBaselineReport, SuiteResult, parse_baseline
from app.evaluation.quality import GenerationQuality, QualityCase, QualityMetric
from app.features import FeatureFlag
from scripts.capture_baseline import (
    FIXTURE_PACK_VERSION, BaselineError, capture, capture_metadata, parse_metrics,
)


def capture_context():
    return {
        'source_revision': 'a' * 40,
        'dirty_tree': False,
        'feature_flags': {flag.value: False for flag in FeatureFlag},
        'environment': {
            'python_version': '3.13.0',
            'node_version': '22.0.0',
            'system': 'TestOS',
            'machine': 'test-architecture',
        },
        'fixture_pack_version': FIXTURE_PACK_VERSION,
    }


def quality_document():
    metric = QualityMetric.from_counts(1, 1)
    return GenerationQuality(
        case_success=metric,
        first_pass_proposal_validity=metric,
        repair_invocation=metric,
        repair_success=metric,
        source_import_validity=metric,
        production_build_success=metric,
        runtime_health=metric,
        verification_success=metric,
        publish_gate_decisions=metric,
        deterministic_hash_reuse=metric,
        cases=[QualityCase(id='unit-case', category='unit', passed=True, expected='pass', actual='pass')],
    )


def test_parse_metrics_handles_pass_and_failure_summaries():
    assert parse_metrics('17 passed in 2.3s') == (17, 0)
    assert parse_metrics('2 passed, 1 failed in 0.4s') == (2, 1)
    with pytest.raises(BaselineError):
        parse_metrics('not a test summary')


def test_capture_records_real_runner_results_and_compatibility():
    output = Path(os.environ['DATA_DIR']) / 'baseline-test.json'
    calls = []

    def fake_runner(command, **_kwargs):
        calls.append(command)
        summaries = {
            'backend': '17 passed in 0.2s',
            'frontend_unit': 'Tests 5 passed in 0.1s',
            'browser': '5 passed in 0.3s',
        }
        if 'pytest' in command:
            name = 'backend'
        elif 'playwright' in command:
            name = 'browser'
        else:
            name = 'frontend_unit'
        return SimpleNamespace(returncode=0, stdout=summaries[name], stderr='')

    result = capture(False, output, timeout=1, runner=fake_runner, metadata=capture_context(), skip_generation=True)
    assert result['suites']['backend']['passed'] == 17
    assert result['suites']['frontend_unit']['passed'] == 5
    assert result['suites']['browser']['passed'] == 5
    assert result['suites']['provider_smoke']['status'] == 'skipped'
    saved = json.loads(output.read_text())
    assert saved['schema_version'] == '1.1'
    assert saved['source_revision'] == 'a' * 40
    assert saved['dirty_tree'] is False
    assert saved['fixture_pack_version'] == FIXTURE_PACK_VERSION
    assert set(saved['feature_flags']) == {flag.value for flag in FeatureFlag}
    assert saved['compatibility']['source_formats'] == ['single-file', 'multi-file']
    assert isinstance(parse_baseline(saved), BaselineReportV1_1)
    assert len(calls) == 3

    quality_output = Path(os.environ['DATA_DIR']) / 'baseline-quality-test.json'
    result = capture(False, quality_output, timeout=1, runner=fake_runner,
                     metadata=capture_context(), quality=quality_document())
    saved = json.loads(quality_output.read_text())
    assert saved['schema_version'] == '1.2'
    assert saved['generation']['case_success'] == {'numerator': 1, 'denominator': 1, 'rate': 1.0}
    assert saved['generation']['cases'][0]['id'] == 'unit-case'
    assert isinstance(parse_baseline(saved), BaselineReport)
    assert result['generation']['case_success']['numerator'] == 1
    assert len(calls) == 6


def test_current_baseline_file_remains_valid_legacy_document():
    path = Path(__file__).parent / 'evals' / 'baseline.json'
    if not path.exists():
        return
    baseline = parse_baseline(json.loads(path.read_text()))
    assert isinstance(baseline, LegacyBaselineReport)
    assert baseline.schema_version == '1.0'
    assert {'backend', 'frontend_unit', 'browser', 'provider_smoke'} <= baseline.suites.model_dump().keys()
    assert baseline.captured_at.tzinfo is not None
    assert baseline.compatibility.source_formats == ['single-file', 'multi-file']


def test_checked_in_schema_matches_current_report_contract():
    path = Path(__file__).parent / 'evals' / 'baseline.schema.json'
    assert json.loads(path.read_text()) == BaselineReport.model_json_schema()


def test_capture_metadata_is_complete_and_excludes_command_details():
    def fake_runner(command, **_kwargs):
        if command == ['git', 'rev-parse', 'HEAD']:
            return SimpleNamespace(returncode=0, stdout='b' * 40 + '\n', stderr='')
        if command == ['git', 'status', '--porcelain']:
            return SimpleNamespace(returncode=0, stdout=' M doc/IMPLEMENTATION.md\n', stderr='')
        if command == ['node', '--version']:
            return SimpleNamespace(returncode=0, stdout='v22.14.0\n', stderr='')
        raise AssertionError(command)

    metadata = capture_metadata(runner=fake_runner)
    assert metadata['source_revision'] == 'b' * 40
    assert metadata['dirty_tree'] is True
    assert metadata['environment']['node_version'] == '22.14.0'
    assert set(metadata['feature_flags']) == {flag.value for flag in FeatureFlag}
    assert all(type(value) is bool for value in metadata['feature_flags'].values())
    serialized = json.dumps(metadata)
    assert 'doc/IMPLEMENTATION.md' not in serialized
    assert str(Path(__file__).resolve().parents[2]) not in serialized


def test_baseline_rejects_unknown_versions_and_extra_fields():
    with pytest.raises(ValueError, match='Unsupported baseline schema version'):
        parse_baseline({'schema_version': '2.0'})
    legacy = json.loads((Path(__file__).parent / 'evals' / 'baseline.json').read_text())
    legacy['unexpected'] = True
    with pytest.raises(ValueError):
        parse_baseline(legacy)


def test_skipped_suite_requires_an_explicit_reason():
    with pytest.raises(ValueError, match='must include a reason'):
        SuiteResult(status='skipped', passed=0, failed=0, duration_ms=0)
    with pytest.raises(ValueError, match='Only a skipped suite'):
        SuiteResult(status='passed', passed=1, failed=0, duration_ms=1, reason='not applicable')
