"""Cancellation-aware subprocess ownership, redaction, and cleanup."""

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import uuid

from .context import JobContext, current_job_context
from .models import JobCancelledError
from .redaction import redact_output
from .tool_runs import finish_tool_run, start_tool_run


class ProcessTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    output: str


async def _read_output(stream: asyncio.StreamReader, limit: int) -> str:
    output = bytearray()
    while chunk := await stream.read(4096):
        output.extend(chunk)
        if len(output) > limit:
            del output[:-limit]
    return redact_output(output.decode(errors='replace'))


async def terminate_process_group(process: asyncio.subprocess.Process, reader: asyncio.Task) -> None:
    """Stop only the process group created for one attempt and drain its output."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
    await reader


async def run_process(
    command: list[str],
    cwd: Path,
    env: dict,
    timeout: float,
    action: str = 'run process',
    context: JobContext | None = None,
    tool_run_id: str | None = None,
    output_limit: int = 8000,
) -> ProcessResult:
    if timeout <= 0:
        raise ValueError('Process timeout must be positive')
    if output_limit <= 0:
        raise ValueError('Process output limit must be positive')
    context = context or current_job_context()
    telemetry = None
    if tool_run_id is None:
        executable = Path(command[0]).name
        telemetry = start_tool_run(
            action, executable, {'command': command, 'cwd': str(cwd), 'timeout': timeout},
            provenance={'action': action, 'executable': executable, 'timeout_seconds': timeout},
        )
        if telemetry:
            tool_run_id = telemetry.id
    try:
        process = await asyncio.create_subprocess_exec(
            *command, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True,
        )
    except Exception as exc:
        finish_tool_run(telemetry, 'failed', error=f'{type(exc).__name__}: {exc}')
        raise
    tool_run_id = tool_run_id or f'process-{uuid.uuid4().hex}'
    if context:
        context.own_tool(tool_run_id, process.pid)
    reader = asyncio.create_task(_read_output(process.stdout, output_limit))
    waiter = asyncio.create_task(process.wait())
    cancellation_waiter = asyncio.create_task(context.cancellation.wait()) if context else None
    try:
        pending = {waiter, *([cancellation_waiter] if cancellation_waiter else [])}
        done, _ = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if cancellation_waiter in done:
            await terminate_process_group(process, reader)
            raise JobCancelledError('Generation cancelled. Retry this stage.')
        if waiter not in done:
            await terminate_process_group(process, reader)
            raise ProcessTimeoutError(f'Timed out while trying to {action}. Please retry.')
        result = ProcessResult(process.returncode, await reader)
        finish_tool_run(
            telemetry, 'succeeded' if result.returncode == 0 else 'failed',
            provenance={'returncode': result.returncode},
            error=None if result.returncode == 0 else result.output[-2000:],
        )
        return result
    except JobCancelledError as exc:
        if process.returncode is None:
            await terminate_process_group(process, reader)
        finish_tool_run(telemetry, 'cancelled', error=str(exc))
        raise
    except asyncio.CancelledError as exc:
        await terminate_process_group(process, reader)
        finish_tool_run(telemetry, 'cancelled', error=f'{type(exc).__name__}: {exc}')
        raise
    except Exception as exc:
        if process.returncode is None:
            await terminate_process_group(process, reader)
        finish_tool_run(telemetry, 'failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        waiter.cancel()
        if cancellation_waiter:
            cancellation_waiter.cancel()
        await asyncio.gather(waiter, cancellation_waiter, return_exceptions=True) if cancellation_waiter else None
        if context:
            context.release_tool(tool_run_id)
