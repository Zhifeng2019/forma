import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.capture_baseline import BaselineError, capture, parse_metrics


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

    result = capture(False, output, timeout=1, runner=fake_runner)
    assert result['suites']['backend']['passed'] == 17
    assert result['suites']['frontend_unit']['passed'] == 5
    assert result['suites']['browser']['passed'] == 5
    assert result['suites']['provider_smoke']['status'] == 'skipped'
    saved = json.loads(output.read_text())
    assert saved['schema_version'] == '1.0'
    assert saved['compatibility']['source_formats'] == ['single-file', 'multi-file']
    assert len(calls) == 3


def test_current_baseline_file_has_expected_shape():
    path = Path(__file__).parent / 'evals' / 'baseline.json'
    if not path.exists():
        return
    baseline = json.loads(path.read_text())
    assert baseline['schema_version'] == '1.0'
    assert {'backend', 'frontend_unit', 'browser', 'provider_smoke'} <= baseline['suites'].keys()
    assert 'captured_at' in baseline and 'compatibility' in baseline
