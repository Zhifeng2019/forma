"""Docker-backed generated-application sandbox with strict filesystem and resource limits."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import uuid

from .backend_engine import runtime_requirements
from .config import settings
from .jobs.context import current_job_context
from .jobs.processes import run_process
from .jobs.redaction import redact_output


class SandboxError(RuntimeError):
    pass


def _clean_environment(root: Path) -> dict:
    return {
        'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
        'HOME': str(root), 'TMPDIR': str(root / 'tmp'), 'NO_COLOR': '1',
        'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
    }


async def _docker(command: list[str], cwd: Path | None = None, check: bool = True) -> str:
    process = await asyncio.create_subprocess_exec(
        'docker', *command, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    output = (await process.communicate())[0].decode(errors='replace').strip()
    if check and process.returncode:
        raise SandboxError(redact_output(output)[:2000] or f'Docker command failed: {command[0]}')
    return output


class DockerSandboxProcess:
    def __init__(self, name: str, logs: asyncio.subprocess.Process, pid: int):
        self.name = name
        self.logs = logs
        self.stdout = logs.stdout
        self.pid = pid

    @property
    def returncode(self) -> int | None:
        result = subprocess.run(
            ['docker', 'inspect', '--format', '{{json .State}}', self.name],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode:
            return 255
        state = json.loads(result.stdout)
        if state.get('Running') or state.get('Restarting'):
            return None
        return int(state.get('ExitCode') or 0)

    async def wait(self) -> int:
        output = await _docker(['wait', self.name], check=False)
        try:
            return int(output.splitlines()[-1])
        except (ValueError, IndexError):
            return 255

    async def stop(self) -> None:
        await _docker(['stop', '--timeout', '5', self.name], check=False)
        await _docker(['rm', '--force', self.name], check=False)
        if self.logs.returncode is None:
            self.logs.terminate()
        await self.logs.wait()


class DockerSandbox:
    def __init__(self, base_image: str = 'python:3.13-slim'):
        self.base_image = base_image

    def _dockerfile(self) -> str:
        return f'''FROM {self.base_image}
WORKDIR /app
ARG PIP_INDEX_URL
COPY requirements.txt /app/requirements.txt
RUN python -m venv /app/venv && /app/venv/bin/pip install --no-cache-dir \
    --disable-pip-version-check --index-url "$PIP_INDEX_URL" -r /app/requirements.txt
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
'''

    def _tag(self, project_id: str, version: int, requirements: str) -> str:
        import hashlib
        digest = hashlib.sha256((self.base_image + requirements).encode()).hexdigest()[:20]
        return f'forma-sandbox-{project_id[:12]}-v{version}-{digest}'

    async def _prepare_image(self, project_id: str, version: int, requirements: str) -> str:
        root = settings.data_path / 'projects' / project_id / 'sandbox'
        root.mkdir(parents=True, exist_ok=True)
        (root / 'tmp').mkdir(exist_ok=True)
        requirements = runtime_requirements(requirements)
        (root / 'requirements.txt').write_text(requirements)
        (root / 'Dockerfile').write_text(self._dockerfile())
        tag = self._tag(project_id, version, requirements)
        existing = await _docker(['image', 'inspect', '--format', '{{.Id}}', tag], check=False)
        if existing.startswith('sha256:'):
            return tag
        env = _clean_environment(root)
        result = await run_process(
            ['docker', 'build', '--build-arg', f'PIP_INDEX_URL={settings.runtime_pip_index_url}',
             '--quiet', '--tag', tag, str(root)], root, env,
            settings.runtime_install_timeout, 'Build the application sandbox image',
        )
        if result.returncode:
            raise SandboxError(f'The sandbox image build failed:\n{result.output[-3000:]}')
        return tag

    def run_arguments(
        self, tag: str, name: str, source_dir: Path, work: Path, port: int,
    ) -> list[str]:
        uid, gid = (os.getuid(), os.getgid()) if os.getuid() else (1000, 1000)
        launcher = Path(__file__).with_name('runtime_launcher.py').resolve()
        return [
            'run', '--detach', '--rm', '--name', name,
            '--user', f'{uid}:{gid}', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--pids-limit', '128', '--memory', f'{settings.runtime_memory_mb}m', '--cpus', '1',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
            '--mount', f'type=bind,src={source_dir.resolve()},dst=/app/source,readonly',
            '--mount', f'type=bind,src={work.resolve()},dst=/app/work',
            '--mount', f'type=bind,src={launcher},dst=/app/runtime_launcher.py,readonly',
            '--workdir', '/app/work', '--env', 'HOME=/app/work',
            '--env', 'PYTHONUNBUFFERED=1', '--env', 'PYTHONDONTWRITEBYTECODE=1',
            '--env', 'FORMA_GENERATED_APPLICATION=1', '--env', 'PIP_NO_INPUT=1',
            '--env', 'FORMA_RUNTIME_HOST=0.0.0.0', '--publish', f'127.0.0.1:{port}:{port}', tag,
            '/app/venv/bin/python', '/app/runtime_launcher.py',
            str(settings.runtime_memory_mb), '/app/source', str(port),
        ]

    async def start(
        self, project_id: str, version: int, channel: str,
        source_dir: Path, port: int, requirements: str, work: Path,
    ) -> DockerSandboxProcess:
        tag = await self._prepare_image(project_id, version, requirements)
        context = current_job_context()
        if context:
            context.raise_if_cancelled()
        name = f'forma-app-{project_id[:12]}-v{version}-{channel}-{uuid.uuid4().hex[:10]}'
        work.mkdir(parents=True, exist_ok=True)
        try:
            await _docker(self.run_arguments(tag, name, source_dir, work, port))
            state = json.loads(await _docker(['inspect', '--format', '{{json .State}}', name]))
            logs = await asyncio.create_subprocess_exec(
                'docker', 'logs', '--follow', name,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            return DockerSandboxProcess(name, logs, int(state['Pid']))
        except Exception:
            await _docker(['rm', '--force', name], check=False)
            raise


sandbox_manager = DockerSandbox()
