import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import sys

import pytest

from app import llm
from app.jobs.context import JobContext, activate_job_context, reset_job_context
from app.jobs.models import JobCancelledError
from app.jobs.processes import ProcessTimeoutError, run_process
from app.runtime import ManagedRuntime, runtime_manager
from app.security import encrypt_secret


def provider():
    return {
        'name': 'Cancellation Provider', 'model': 'fixture-model',
        'base_url': 'https://api.example.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }


def process_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_process_cancellation_kills_only_attempt_owned_group():
    async def scenario():
        event = asyncio.Event()
        context = JobContext(930001, 'project', 'job', 1, 'trace', event)
        unrelated = await asyncio.create_subprocess_exec(
            sys.executable, '-c', 'import time; time.sleep(60)',
            stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        try:
            task = asyncio.create_task(run_process(
                [sys.executable, '-c', 'import time; time.sleep(60)'], Path.cwd(), dict(os.environ), 30,
                context=context, tool_run_id='owned-child',
            ))
            for _ in range(100):
                if context.tool_owners:
                    break
                await asyncio.sleep(0.01)
            owned_pid = context.tool_owners['owned-child'].process_group_id
            event.set()
            with pytest.raises(JobCancelledError):
                await task
            assert not process_exists(owned_pid)
            assert unrelated.returncode is None
            assert context.tool_owners == {}
        finally:
            try:
                os.killpg(unrelated.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await unrelated.wait()

    asyncio.run(scenario())


def test_process_timeout_and_output_redaction():
    async def scenario():
        script = (
            "print('api_key=super-secret token=abc123');"
            "print('https://user:pass@example.com/path?api_key=secret')"
        )
        result = await run_process([sys.executable, '-c', script], Path.cwd(), dict(os.environ), 2)
        assert result.returncode == 0
        assert 'super-secret' not in result.output and 'abc123' not in result.output
        assert 'user:pass' not in result.output and 'api_key=secret' not in result.output
        assert 'example.com/path' in result.output
        with pytest.raises(ProcessTimeoutError):
            await run_process(
                [sys.executable, '-c', 'import time; time.sleep(2)'], Path.cwd(), dict(os.environ), 0.05,
            )

    asyncio.run(scenario())


def test_provider_request_cancels_in_flight_without_retry(monkeypatch):
    class BlockingClient:
        def __init__(self, **_kwargs):
            self.calls = 0
            self.started = asyncio.Event()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **_kwargs):
            self.calls += 1
            self.started.set()
            await asyncio.sleep(30)
            raise AssertionError('Request should have been cancelled')

    async def scenario():
        event = asyncio.Event()
        context = JobContext(930002, 'project', 'job', 1, 'trace', event)
        token = activate_job_context(context)
        client = BlockingClient()
        monkeypatch.setattr('httpx.AsyncClient', lambda **_kwargs: client)
        try:
            task = asyncio.create_task(llm.complete(provider(), 'System', 'Prompt'))
            await asyncio.wait_for(client.started.wait(), timeout=2)
            event.set()
            with pytest.raises(JobCancelledError):
                await task
            assert client.calls == 1
        finally:
            reset_job_context(token)

    asyncio.run(scenario())


def test_provider_cancellation_stops_before_schema_fallback(monkeypatch):
    class Response:
        status_code = 400
        text = 'schema unsupported'

    class FallbackClient:
        def __init__(self, **_kwargs):
            self.calls = 0
            self.first_response = asyncio.Event()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **_kwargs):
            self.calls += 1
            self.first_response.set()
            return Response()

    async def scenario():
        event = asyncio.Event()
        context = JobContext(930003, 'project', 'job', 1, 'trace', event)
        token = activate_job_context(context)
        client = FallbackClient()
        monkeypatch.setattr('httpx.AsyncClient', lambda **_kwargs: client)
        try:
            task = asyncio.create_task(llm.complete_with_schema(
                provider(), 'System', 'Prompt', {'type': 'object'}, 'fixture_schema',
            ))
            await asyncio.wait_for(client.first_response.wait(), timeout=2)
            event.set()
            with pytest.raises(JobCancelledError):
                await task
            assert client.calls == 1
        finally:
            reset_job_context(token)

    asyncio.run(scenario())


def test_runtime_cancellation_preserves_unrelated_public_runtime():
    async def scenario():
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-c', 'import time; time.sleep(60)',
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        runtime = ManagedRuntime(
            key='unrelated-public', project_id='other-project', version=1, channel='public',
            process=process, port=65535, started_at=datetime.now(timezone.utc).isoformat(),
            reader=asyncio.create_task(asyncio.sleep(0)), last_used=0,
        )
        runtime_manager._runtimes[runtime.key] = runtime
        event = asyncio.Event()
        context = JobContext(930004, 'project', 'job', 1, 'trace', event)
        event.set()
        token = activate_job_context(context)
        try:
            with pytest.raises(JobCancelledError):
                await runtime_manager._start(
                    'cancelled-start', 'cancelled-project', 1, 'preview', Path(sys.executable), Path('/not-used'),
                )
            with pytest.raises(JobCancelledError):
                await runtime_manager._wait_until_healthy(runtime)
            assert process.returncode is None
            assert context.tool_owners == {}
        finally:
            reset_job_context(token)
            runtime_manager._runtimes.pop(runtime.key, None)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()

    asyncio.run(scenario())
