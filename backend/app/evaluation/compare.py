"""Semantic baseline identity and accepted-threshold regression comparison."""

import json
from pathlib import Path

from .baseline import parse_baseline
from .quality import GenerationQuality

METRIC_NAMES = (
    'case_success', 'first_pass_proposal_validity', 'repair_invocation', 'repair_success',
    'source_import_validity', 'production_build_success', 'runtime_health',
    'verification_success', 'publish_gate_decisions', 'deterministic_hash_reuse',
)
LOWER_IS_BETTER = {'repair_invocation'}
TOLERANCE = 1e-12


def semantic_generation(document: dict) -> dict:
    """Quality reports have no volatile fields, so validated content is canonical."""
    return GenerationQuality.model_validate(document).model_dump(mode='json')


def semantic_baseline(document: dict) -> dict:
    """Remove only capture-time and duration fields before identity comparison."""
    report = parse_baseline(document)
    document = report.model_dump(mode='json')
    document.pop('captured_at', None)
    for suite in document['suites'].values():
        suite.pop('duration_ms', None)
    return document


def semantic_equal(first: dict, second: dict) -> bool:
    return semantic_baseline(first) == semantic_baseline(second)


def issue(code, metric, expected, actual, case_id=None):
    result = {'code': code, 'metric': metric, 'expected': expected, 'actual': actual}
    if case_id:
        result['case_id'] = case_id
    return result


def compare_generation(reference: dict, candidate: dict) -> dict:
    reference = GenerationQuality.model_validate(reference)
    candidate = GenerationQuality.model_validate(candidate)
    issues = []
    reference_cases = {case.id: case for case in reference.cases}
    candidate_cases = {case.id: case for case in candidate.cases}
    if len(reference_cases) != len(reference.cases) or len(candidate_cases) != len(candidate.cases):
        issues.append(issue('duplicate_case', 'cases', 'unique case IDs', 'duplicate case IDs'))
    for case_id, expected_case in reference_cases.items():
        actual_case = candidate_cases.get(case_id)
        if actual_case is None:
            issues.append(issue('missing_case', 'cases', expected_case.expected, 'missing', case_id))
            continue
        if (actual_case.category, actual_case.expected) != (expected_case.category, expected_case.expected):
            issues.append(issue('case_contract_changed', 'cases', expected_case.expected,
                                actual_case.expected, case_id))
        if not actual_case.passed:
            issues.append(issue('case_failed', 'cases', expected_case.expected,
                                actual_case.actual, case_id))
    for case_id in candidate_cases.keys() - reference_cases.keys():
        issues.append(issue('unexpected_case', 'cases', 'absent', 'present', case_id))

    thresholds = {}
    for name in METRIC_NAMES:
        expected = getattr(reference, name)
        actual = getattr(candidate, name)
        direction = 'maximum_rate' if name in LOWER_IS_BETTER else 'minimum_rate'
        thresholds[name] = {'denominator': expected.denominator, direction: expected.rate}
        if expected.denominator != actual.denominator:
            issues.append(issue('denominator_changed', name, expected.denominator, actual.denominator))
        if expected.rate is None:
            continue
        regressed = (actual.rate is None or actual.rate > expected.rate + TOLERANCE
                     if name in LOWER_IS_BETTER else
                     actual.rate is None or actual.rate + TOLERANCE < expected.rate)
        if regressed:
            operator = '<=' if name in LOWER_IS_BETTER else '>='
            issues.append(issue('metric_regression', name, f'{operator} {expected.rate}', actual.rate))
    return {'passed': not issues, 'thresholds': thresholds, 'issues': issues}


def compare_baselines(reference: dict, candidate: dict) -> dict:
    reference = parse_baseline(reference)
    candidate = parse_baseline(candidate)
    if not hasattr(reference, 'generation') or not hasattr(candidate, 'generation'):
        raise ValueError('Quality comparison requires schema 1.2 baseline documents')
    issues = []
    if reference.fixture_pack_version != candidate.fixture_pack_version:
        issues.append(issue('fixture_pack_changed', 'fixture_pack_version',
                            reference.fixture_pack_version, candidate.fixture_pack_version))
    suite_thresholds = {}
    for name, expected in reference.suites:
        actual = getattr(candidate.suites, name)
        suite_thresholds[name] = {
            'minimum_passed': expected.passed,
            'maximum_failed': expected.failed,
        }
        if expected.status == 'passed' and actual.status == 'skipped':
            issues.append(issue('suite_skipped', name, expected.status, actual.status))
        if actual.passed < expected.passed:
            issues.append(issue('suite_regression', name, expected.passed, actual.passed))
        if actual.failed > expected.failed or (actual.status == 'failed' and expected.status != 'failed'):
            issues.append(issue('suite_failed', name, expected.failed, actual.failed))
    quality = compare_generation(reference.generation.model_dump(mode='json'),
                                 candidate.generation.model_dump(mode='json'))
    issues.extend(quality['issues'])
    return {
        'passed': not issues,
        'thresholds': {'fixture_pack_version': reference.fixture_pack_version,
                       'suites': suite_thresholds, 'generation': quality['thresholds']},
        'issues': issues,
    }


def compare_baseline_files(reference: Path, candidate: Path) -> dict:
    return compare_baselines(
        json.loads(reference.read_text(encoding='utf-8')),
        json.loads(candidate.read_text(encoding='utf-8')),
    )


def load_generation(path: Path) -> GenerationQuality:
    return GenerationQuality.model_validate(json.loads(path.read_text(encoding='utf-8')))
