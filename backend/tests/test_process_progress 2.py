import asyncio
import os
from pathlib import Path
import sys

import pytest

from app.jobs import processes
from app.jobs.processes import ProcessTimeoutError, run_process


@pytest.fixture(autouse=True)
def short_progress_window(monkeypatch):
    monkeypatch.setattr(processes, 'PROGRESS_WINDOW_SECONDS', 0.5)
    monkeypatch.setattr(processes, 'MIN_PROGRESS_CPU_SECONDS', 0.2)


def python(code):
    return [sys.executable, '-c', code]


def run(code, timeout, max_timeout=None):
    return asyncio.run(run_process(
        python(code), Path.cwd(), dict(os.environ), timeout, 'run a test process', max_timeout=max_timeout,
    ))


def test_stuck_process_stops_at_timeout_without_extension():
    with pytest.raises(ProcessTimeoutError, match='stopped making progress'):
        run('import time; time.sleep(30)', 0.5, max_timeout=20)


def test_process_printing_progress_continues_past_timeout():
    code = 'import time\nfor i in range(8):\n    print(i, flush=True); time.sleep(0.25)\nprint("done")'
    result = run(code, 0.5, max_timeout=20)
    assert result.returncode == 0 and 'done' in result.output


def test_silent_cpu_bound_process_continues_past_timeout():
    code = 'import time\nend = time.time() + 2.0\nwhile time.time() < end:\n    pass\nprint("done")'
    result = run(code, 0.5, max_timeout=20)
    assert 'done' in result.output


def test_working_process_still_stops_at_the_hard_limit():
    code = 'import time\nwhile True:\n    print(".", flush=True); time.sleep(0.1)'
    with pytest.raises(ProcessTimeoutError, match='the longest allowed'):
        run(code, 0.5, max_timeout=1.5)


def test_default_has_no_extension():
    code = 'import time\nwhile True:\n    print(".", flush=True); time.sleep(0.1)'
    with pytest.raises(ProcessTimeoutError, match='the longest allowed'):
        run(code, 0.5)
