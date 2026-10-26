"""Capture a reproducible v1.4 baseline without contacting an LLM provider."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
COMPATIBILITY = {
    'source_formats': ['single-file', 'multi-file'],
    'backend_modes': ['static', 'fastapi'],
    'publish_states': ['published', 'unpublished'],
    'history_states': ['current', 'historical'],
    'fixtures': [
        'empty-python-init', 'native-fetch-adapter', 'missing-requirements',
        'truncated-model-output', 'invalid-json', 'invalid-package-structure',
    ],
}


class BaselineError(RuntimeError):
    pass


def parse_metrics(output: str) -> tuple[int, int]:
    passed_matches = re.findall(r'(\d+) passed', output)
    failed_matches = re.findall(r'(\d+) failed', output)
    if not passed_matches and not failed_matches:
        raise BaselineError(f'Unable to parse test summary: {output[-500:]}')
    return int(passed_matches[-1] if passed_matches else 0), int(failed_matches[-1] if failed_matches else 0)


def run_suite(name: str, command: list[str], cwd: Path, timeout: int, env: dict[str, str], runner=subprocess.run) -> dict:
    started = time.monotonic()
    result = runner(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    output = (result.stdout or '') + '\n' + (result.stderr or '')
    if result.returncode:
        raise BaselineError(f'{name} failed:\n{output[-2500:]}')
    passed, failed = parse_metrics(output)
    return {
        'status': 'passed' if failed == 0 else 'failed',
        'passed': passed, 'failed': failed,
        'duration_ms': round((time.monotonic() - started) * 1000),
    }


def skipped(reason: str) -> dict:
    return {'status': 'skipped', 'reason': reason, 'passed': 0, 'failed': 0, 'duration_ms': 0}


def write_baseline(output: Path, suites: dict[str, dict], source: str = 'local-regression-suite') -> dict:
    baseline = {
        'schema_version': '1.0',
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'source': source,
        'suites': suites,
        'compatibility': COMPATIBILITY,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(baseline, indent=2) + '\n')
    return baseline


def capture(skip_browser: bool, output: Path, timeout: int, runner=subprocess.run) -> dict:
    python = sys.executable
    npm, npx = shutil.which('npm'), shutil.which('npx')
    if not npm or not npx:
        raise BaselineError('npm and npx are required to capture the complete baseline.')
    suites = {
        'backend': run_suite('backend', [python, '-m', 'pytest', '-q'], ROOT / 'backend', timeout, dict(os.environ), runner),
        'frontend_unit': run_suite('frontend_unit', [npm, 'test'], ROOT / 'frontend', timeout, dict(os.environ), runner),
        'browser': skipped('--skip-browser was supplied') if skip_browser else run_suite(
            'browser', [npx, 'playwright', 'test'], ROOT / 'frontend', timeout,
            {**os.environ, 'FORMA_TEST_BACKEND_PORT': '18010', 'FORMA_TEST_FRONTEND_PORT': '18011'}, runner,
        ),
        'provider_smoke': skipped('real-provider evaluation is opt-in and is not part of baseline capture'),
    }
    return write_baseline(output, suites)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-browser', action='store_true', help='Skip Playwright while capturing backend and frontend units.')
    parser.add_argument('--output', type=Path, default=ROOT / 'backend' / 'tests' / 'evals' / 'baseline.json')
    parser.add_argument('--timeout', type=int, default=900, help='Per-suite timeout in seconds.')
    args = parser.parse_args()
    result = capture(args.skip_browser, args.output, args.timeout)
    print(json.dumps({'output': str(args.output), 'suites': result['suites']}, indent=2))


if __name__ == '__main__':
    main()
