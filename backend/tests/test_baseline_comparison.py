import copy
import json
from pathlib import Path

from app.evaluation.baseline import BaselineReport
from app.evaluation.compare import compare_baselines, compare_generation, semantic_equal
from app.features import FeatureFlag
from scripts.capture_baseline import COMPATIBILITY, FIXTURE_PACK_VERSION

EVALUATIONS = Path(__file__).parent / 'evals'


def generation_document():
    return json.loads((EVALUATIONS / 'generation.json').read_text(encoding='utf-8'))


def baseline_document():
    suite = {'status': 'passed', 'passed': 10, 'failed': 0, 'duration_ms': 100}
    return BaselineReport(
        schema_version='1.2',
        captured_at='2026-10-28T00:00:00+00:00',
        source='comparison-test',
        source_revision='a' * 40,
        dirty_tree=False,
        feature_flags={flag.value: False for flag in FeatureFlag},
        environment={'python_version': '3.13.0', 'node_version': '22.0.0',
                     'system': 'TestOS', 'machine': 'test-architecture'},
        fixture_pack_version=FIXTURE_PACK_VERSION,
        suites={
            'backend': suite, 'frontend_unit': suite,
            'browser': {'status': 'skipped', 'reason': 'test skip', 'passed': 0, 'failed': 0, 'duration_ms': 0},
            'provider_smoke': {'status': 'skipped', 'reason': 'opt-in', 'passed': 0, 'failed': 0, 'duration_ms': 0},
        },
        compatibility=COMPATIBILITY,
        generation=generation_document(),
    ).model_dump(mode='json')


def test_semantic_identity_ignores_capture_time_and_durations():
    reference = baseline_document()
    candidate = copy.deepcopy(reference)
    candidate['captured_at'] = '2026-10-28T01:00:00+00:00'
    for suite in candidate['suites'].values():
        if suite['status'] != 'skipped':
            suite['duration_ms'] = 999_999
    assert semantic_equal(reference, candidate)
    assert compare_baselines(reference, candidate)['passed']


def test_comparison_reports_case_and_metric_regressions():
    reference = generation_document()
    candidate = copy.deepcopy(reference)
    failed = next(case for case in candidate['cases'] if case['id'] == 'verification:static-single')
    failed['passed'] = False
    failed['actual'] = 'browser failed'
    failed['error'] = 'injected regression'
    candidate['case_success']['numerator'] = 21
    candidate['case_success']['rate'] = 21 / 22
    candidate['verification_success']['numerator'] = 1
    candidate['verification_success']['rate'] = 0.5

    result = compare_generation(reference, candidate)
    assert not result['passed']
    case_issue = next(issue for issue in result['issues'] if issue['code'] == 'case_failed')
    assert case_issue['case_id'] == 'verification:static-single'
    assert case_issue['actual'] == 'browser failed'
    metric_issue = next(issue for issue in result['issues']
                        if issue['code'] == 'metric_regression' and issue['metric'] == 'verification_success')
    assert metric_issue['expected'] == '>= 1.0' and metric_issue['actual'] == 0.5


def test_comparison_uses_directional_thresholds_from_accepted_report():
    reference = generation_document()
    candidate = copy.deepcopy(reference)
    candidate['repair_invocation']['numerator'] = 4
    candidate['repair_invocation']['rate'] = 4 / 9
    result = compare_generation(reference, candidate)
    regression = next(issue for issue in result['issues'] if issue['code'] == 'metric_regression')
    assert regression['metric'] == 'repair_invocation'
    assert regression['expected'] == '<= 0.3333333333333333'
    assert regression['actual'] == 4 / 9
    assert result['thresholds']['repair_invocation']['maximum_rate'] == 3 / 9

    candidate['repair_invocation']['numerator'] = 2
    candidate['repair_invocation']['rate'] = 2 / 9
    assert compare_generation(reference, candidate)['passed']
