"""On-demand, per-application FastAPI processes with isolated Python environments."""

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import httpx
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sys
import time

from .backend_engine import runtime_requirements
from .config import settings
from .engine import validate_project_id
from .frontend_builder import PackageBuildError, write_source_files
from .jobs.context import current_job_context
from .jobs.models import JobCancelledError
from .jobs.processes import run_process


class RuntimeLaunchError(RuntimeError):
    pass


@dataclass
class ManagedRuntime:
    key: str
    project_id: str
    version: int
    channel: str
    process: asyncio.subprocess.Process
    port: int
    started_at: str
    reader: asyncio.Task
    last_used: float


class RuntimeManager:
    def __init__(self):
        self._runtimes: dict[str, ManagedRuntime] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._starting: set[str] = set()
        self._logs: dict[str, deque[str]] = {}
        self._errors: dict[str, str] = {}

    def _key(self, project_id: str, version: int, channel: str) -> str:
        validate_project_id(project_id)
        if version < 1 or channel not in {'preview', 'public'}:
            raise RuntimeLaunchError('Invalid application runtime coordinates')
        return f'{project_id}:v{version}:{channel}'

    def _lock(self, project_id: str) -> asyncio.Lock:
        return self._locks.setdefault(project_id, asyncio.Lock())

    def _paths(self, project_id: str, version: int) -> tuple[Path, Path, Path, Path]:
        root = settings.data_path / 'projects' / project_id
        return root, root / '.venv', root / 'versions' / f'v{version}', root / 'work'

    def _materialize(
        self, project_id: str, version: int, source: str, requirements: str,
        source_format: str, files: dict[str, str] | None,
    ) -> Path:
        _root, _environment, source_dir, work = self._paths(project_id, version)
        work.mkdir(parents=True, exist_ok=True)
        (work / 'tmp').mkdir(exist_ok=True)
        if source_format == 'multi-file':
            if files is None:
                raise RuntimeLaunchError('The multi-file backend package is unavailable')
            try:
                write_source_files(project_id, version, files)
            except PackageBuildError as exc:
                raise RuntimeLaunchError(str(exc)) from exc
            return source_dir / 'backend'
        source_dir.mkdir(parents=True, exist_ok=True)
        main = source_dir / 'main.py'
        dependencies = source_dir / 'requirements.txt'
        if main.exists() and main.read_text() != source:
            raise RuntimeLaunchError('The immutable version source does not match its artifact')
        main.write_text(source)
        dependencies.write_text(requirements)
        return source_dir

    async def ensure(
        self,
        project_id: str,
        version: int,
        channel: str,
        source: str,
        requirements: str,
        source_format: str = 'single-file',
        files: dict[str, str] | None = None,
    ) -> ManagedRuntime:
        key = self._key(project_id, version, channel)
        existing = self._runtimes.get(key)
        if existing and existing.process.returncode is None:
            existing.last_used = time.monotonic()
            return existing
        self._starting.add(key)
        try:
            async with self._lock(project_id):
                existing = self._runtimes.get(key)
                if existing and existing.process.returncode is None:
                    existing.last_used = time.monotonic()
                    return existing
                if existing:
                    await self._stop(key)
                source_dir = self._materialize(project_id, version, source, requirements, source_format, files)
                # A project has one active preview. Published versions have an
                # independent lifecycle and are never interrupted by previewing history.
                if channel == 'preview':
                    for other_key, runtime in list(self._runtimes.items()):
                        if runtime.project_id == project_id and runtime.channel == 'preview':
                            await self._stop(other_key)
                await self._make_capacity(key)
                environment = await self._ensure_environment(project_id, runtime_requirements(requirements))
                return await self._start(key, project_id, version, channel, environment, source_dir)
        finally:
            self._starting.discard(key)

    async def _ensure_environment(self, project_id: str, requirements: str) -> Path:
        root, environment, _source, work = self._paths(project_id, 1)
        python = environment / 'bin' / 'python'
        base_python = settings.runtime_python or sys.executable
        contract = '\n'.join((
            'physical-app-site-packages-v1', requirements, base_python,
            settings.runtime_pip_index_url,
        ))
        digest = hashlib.sha256(contract.encode()).hexdigest()
        root.mkdir(parents=True, exist_ok=True)
        env = self._clean_environment(work, environment)
        if not python.exists():
            await self._run_install(
                [base_python, '-m', 'venv', str(environment)],
                'create the application Python environment', env, work,
            )
        # Generated apps must never inherit the studio or machine site-packages.
        venv_config = environment / 'pyvenv.cfg'
        if venv_config.exists():
            venv_config.write_text(venv_config.read_text().replace(
                'include-system-site-packages = true', 'include-system-site-packages = false',
            ))
        for stale_link in environment.glob('lib/python*/site-packages/_forma_verified_studio.pth'):
            stale_link.unlink()
        requirements_file = root / 'requirements.current.txt'
        requirements_file.write_text(requirements)
        matches, dependency_detail = await self._dependencies_match(python, requirements_file, env, work)
        if not matches:
            try:
                await self._run_install(
                    [str(python), '-m', 'pip', '--isolated', 'install',
                     '--index-url', settings.runtime_pip_index_url,
                     '--disable-pip-version-check', '--no-input', '--force-reinstall',
                     '-r', str(requirements_file)],
                    'install the application dependencies into its virtual environment',
                    env, work, timeout=settings.runtime_install_timeout,
                )
            except RuntimeLaunchError as exc:
                raise RuntimeLaunchError(f'{exc} Dependency check: {dependency_detail}') from exc
        matches, dependency_detail = await self._dependencies_match(python, requirements_file, env, work)
        if not matches:
            raise RuntimeLaunchError(
                f'Packages are not correctly installed inside the application virtual environment: {dependency_detail}'
            )
        (environment / '.forma-requirements.sha256').write_text(digest)
        return python

    async def _dependencies_match(
        self, python: Path, requirements: Path, env: dict[str, str], cwd: Path,
    ) -> tuple[bool, str]:
        script = (
            'import importlib,importlib.metadata,pathlib,sys,sysconfig\n'
            'expected=[line.strip().split("==",1) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]\n'
            'site=pathlib.Path(sysconfig.get_path("purelib")).resolve()\n'
            'problems=[]\n'
            'for package,wanted in expected:\n'
            '    try:\n'
            '        distribution=importlib.metadata.distribution(package)\n'
            '        actual=distribution.version\n'
            '        dist_path=pathlib.Path(distribution.locate_file("")).resolve()\n'
            '        module_path=pathlib.Path(importlib.import_module(package.replace("-","_")).__file__).resolve()\n'
            '    except Exception as exc:\n'
            '        problems.append(f"{package} is unavailable: {type(exc).__name__}")\n'
            '        continue\n'
            '    if actual!=wanted: problems.append(f"{package} found {actual}, requires {wanted}")\n'
            '    if not dist_path.is_relative_to(site) or not module_path.is_relative_to(site):\n'
            '        problems.append(f"{package} is not installed inside the application virtual environment")\n'
            'print("; ".join(problems))\n'
            'sys.exit(bool(problems))\n'
        )
        try:
            result = await run_process(
                [str(python), '-c', script, str(requirements)], cwd, env, 20,
                'verify the application dependencies',
            )
        except TimeoutError:
            return False, 'dependency verification timed out'
        detail = result.output.strip()[:600]
        if result.returncode == 0:
            return True, 'verified in the application virtual environment'
        return False, detail or 'dependency verification failed'

    async def _run_install(
        self,
        command: list[str],
        action: str,
        env: dict[str, str],
        cwd: Path,
        timeout: int = 120,
    ) -> None:
        try:
            result = await run_process(command, cwd, env, timeout, action)
        except TimeoutError as exc:
            raise RuntimeLaunchError(f'Timed out while trying to {action}. Please retry.') from exc
        if result.returncode:
            # Package indexes and local paths can contain private configuration;
            # keep raw installer output out of API responses and activity history.
            raise RuntimeLaunchError(f'Could not {action}. Check the Python installation and network, then retry.')

    def _clean_environment(self, work: Path, environment: Path) -> dict[str, str]:
        return {
            'PATH': f'{environment / "bin"}:/usr/local/bin:/usr/bin:/bin',
            'HOME': str(work),
            'TMPDIR': str(work / 'tmp'),
            'PYTHONUNBUFFERED': '1',
            'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONNOUSERSITE': '1',
            'PIP_DISABLE_PIP_VERSION_CHECK': '1',
            'PIP_NO_INPUT': '1',
            'FORMA_GENERATED_APPLICATION': '1',
        }

    async def _start(
        self,
        key: str,
        project_id: str,
        version: int,
        channel: str,
        python: Path,
        source_dir: Path,
    ) -> ManagedRuntime:
        _root, environment, _source, work = self._paths(project_id, version)
        context = current_job_context()
        if context:
            context.raise_if_cancelled()
        tool_run_id = f'runtime-start:{key}'
        port = self._free_port()
        logs = self._logs.setdefault(key, deque(maxlen=120))
        logs.append(f'Starting FastAPI version {version} ({channel})')
        launcher = Path(__file__).with_name('runtime_launcher.py')
        process = await asyncio.create_subprocess_exec(
            str(python), str(launcher), str(settings.runtime_memory_mb), str(source_dir), str(port),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, cwd=work,
            env=self._clean_environment(work, environment), start_new_session=True,
        )
        if context:
            context.own_tool(tool_run_id, process.pid)
        reader = asyncio.create_task(self._drain_logs(key, process.stdout))
        runtime = ManagedRuntime(
            key=key, project_id=project_id, version=version, channel=channel,
            process=process, port=port, started_at=datetime.now(timezone.utc).isoformat(),
            reader=reader, last_used=time.monotonic(),
        )
        self._runtimes[key] = runtime
        try:
            await self._wait_until_healthy(runtime)
        except JobCancelledError:
            await self._stop(key)
            raise
        except Exception as exc:
            await self._stop(key)
            message = str(exc) if isinstance(exc, RuntimeLaunchError) else 'The application backend did not become healthy.'
            self._errors[key] = message
            raise RuntimeLaunchError(message) from exc
        else:
            self._errors.pop(key, None)
            logs.append('Health check passed; FastAPI is ready')
            return runtime
        finally:
            if context:
                context.release_tool(tool_run_id)

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            return listener.getsockname()[1]

    async def _drain_logs(self, key: str, stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        logs = self._logs.setdefault(key, deque(maxlen=120))
        try:
            while line := await stream.readline():
                logs.append(line.decode(errors='replace').rstrip()[:2000])
        except (ValueError, asyncio.CancelledError):
            if not logs or logs[-1] != 'Log stream closed':
                logs.append('Log stream closed')

    async def _wait_until_healthy(self, runtime: ManagedRuntime) -> None:
        url = f'http://127.0.0.1:{runtime.port}/api/health'
        deadline = time.monotonic() + settings.runtime_start_timeout
        context = current_job_context()
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            while time.monotonic() < deadline:
                if context:
                    context.raise_if_cancelled()
                if runtime.process.returncode is not None:
                    await asyncio.sleep(0)
                    tail = '\n'.join(list(self._logs[runtime.key])[-8:])
                    raise RuntimeLaunchError(f'The generated backend exited during startup.\n{tail[-2500:]}')
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
        raise RuntimeLaunchError('The backend did not pass its health check in time. Inspect the runtime log and retry.')

    async def request(
        self,
        project_id: str,
        version: int,
        channel: str,
        source: str,
        requirements: str,
        method: str,
        path: str,
        query: str,
        body: bytes,
        content_type: str,
        source_format: str = 'single-file',
        files: dict[str, str] | None = None,
    ) -> httpx.Response:
        runtime = await self.ensure(project_id, version, channel, source, requirements, source_format, files)
        if path.startswith('/') or '..' in path.split('/'):
            raise RuntimeLaunchError('Invalid generated API path')
        target = f'http://127.0.0.1:{runtime.port}/api/{path}'
        runtime.last_used = time.monotonic()
        headers = {'Accept': 'application/json'}
        if content_type:
            headers['Content-Type'] = content_type
        try:
            async with httpx.AsyncClient(timeout=settings.runtime_request_timeout, trust_env=False) as client:
                return await client.request(method, target, params=query, content=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise RuntimeLaunchError('The application backend did not respond in time.') from exc
        except httpx.HTTPError as exc:
            raise RuntimeLaunchError('The application backend is unavailable. Restart it from the Server panel and retry.') from exc

    async def status(self, project_id: str, version: int, check_health: bool = False) -> dict:
        key = self._key(project_id, version, 'preview')
        runtime = self._runtimes.get(key)
        running = bool(runtime and runtime.process.returncode is None)
        healthy = False
        if running and check_health and runtime:
            try:
                async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                    response = await client.get(f'http://127.0.0.1:{runtime.port}/api/health')
                healthy = response.status_code == 200
            except httpx.HTTPError:
                healthy = False
        elif running:
            healthy = True
        state = 'starting' if key in self._starting else 'running' if running else 'error' if self._errors.get(key) else 'stopped'
        return {
            'enabled': True, 'status': state, 'healthy': healthy, 'version': version,
            'started_at': runtime.started_at if runtime else None,
            'last_error': self._errors.get(key),
            'logs': '\n'.join(list(self._logs.get(key, []))[-60:]),
            'execution': 'isolated-process',
        }

    async def restart(
        self, project_id: str, version: int, source: str, requirements: str,
        source_format: str = 'single-file', files: dict[str, str] | None = None,
    ) -> dict:
        key = self._key(project_id, version, 'preview')
        async with self._lock(project_id):
            await self._stop(key)
        await self.ensure(project_id, version, 'preview', source, requirements, source_format, files)
        return await self.status(project_id, version, check_health=True)

    async def stop_project(self, project_id: str, channel: str | None = None, keep_version: int | None = None) -> None:
        validate_project_id(project_id)
        async with self._lock(project_id):
            for key, runtime in list(self._runtimes.items()):
                if runtime.project_id != project_id:
                    continue
                if channel and runtime.channel != channel:
                    continue
                if keep_version is not None and runtime.version == keep_version:
                    continue
                await self._stop(key)

    async def remove_project(self, project_id: str) -> None:
        await self.stop_project(project_id)
        root = settings.data_path / 'projects' / project_id
        if root.exists():
            shutil.rmtree(root)

    async def _make_capacity(self, requested_key: str) -> None:
        for key, runtime in list(self._runtimes.items()):
            if runtime.process.returncode is not None:
                await self._stop(key)
        if len(self._runtimes) < settings.runtime_max_processes:
            return
        now = time.monotonic()
        idle = [r for r in self._runtimes.values()
                if r.channel == 'preview' and now - r.last_used > settings.runtime_idle_seconds]
        candidates = idle or [r for r in self._runtimes.values()
                              if r.channel == 'preview' and r.key != requested_key]
        if candidates:
            oldest = min(candidates, key=lambda runtime: runtime.last_used)
            await self._stop(oldest.key)
            return
        raise RuntimeLaunchError('The runtime capacity is in use by published applications. Unpublish an unused app and retry.')

    async def _stop(self, key: str) -> None:
        runtime = self._runtimes.pop(key, None)
        if not runtime:
            return
        self._logs.setdefault(key, deque(maxlen=120)).append('Stopping application runtime')
        await self._terminate_process(runtime.process)
        try:
            await asyncio.wait_for(runtime.reader, timeout=2)
        except (TimeoutError, asyncio.CancelledError):
            runtime.reader.cancel()

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
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

    async def stop_all(self) -> None:
        for key in list(self._runtimes):
            await self._stop(key)


runtime_manager = RuntimeManager()


def runtime_bootstrap(project_id: str, version: int, published: bool) -> str:
    project = json.dumps(project_id)
    prefix = f'/apps/{project_id}/api' if published else f'/api/projects/{project_id}/runtime/{version}'
    base = json.dumps(prefix)
    private = 'false' if published else 'true'
    return f'''<script>(function(){{
const base={base},privatePreview={private},projectId={project};
async function api(path,options={{}}){{
  if(typeof path!=='string'||!path.startsWith('/')||path.startsWith('//')||path.includes('\\\\')||path.split('/').includes('..'))throw new Error('Invalid application API path');
  const url=new URL(base+path,window.location.origin),root=new URL(base+'/',window.location.origin);
  if(url.origin!==window.location.origin||!url.pathname.startsWith(root.pathname))throw new Error('Application API path escapes its runtime');
  const headers=new Headers(options.headers||{{}});
  if(options.body!==undefined&&!(options.body instanceof FormData)&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
  if(privatePreview){{const token=new URLSearchParams(window.location.search).get('access_token');if(token)headers.set('Authorization','Bearer '+token)}}
  const response=await fetch(url,{{...options,headers}}),type=response.headers.get('content-type')||'';
  if(response.status===204)return null;
  const data=type.includes('json')?await response.json():await response.text();
  if(!response.ok){{let message='Request failed ('+response.status+')';if(data&&typeof data.detail==='string')message=data.detail;else if(data&&Array.isArray(data.detail))message=data.detail.map(x=>x.msg||'Invalid input').join(', ');throw new Error(message)}}
  return data;
}}
window.Forma=Object.freeze({{api}});
const nativeFetch=window.fetch.bind(window);
window.fetch=async(input,init={{}})=>{{
  try{{
    const raw=input instanceof Request?input.url:String(input),url=new URL(raw,window.location.origin);
    if(url.origin===window.location.origin&&url.pathname.startsWith('/api/')&&!url.pathname.startsWith('/api/projects/')){{
      const headers=new Headers(init.headers||(input instanceof Request?input.headers:{{}}));
      if(privatePreview){{const token=new URLSearchParams(window.location.search).get('access_token');if(token)headers.set('Authorization','Bearer '+token)}}
      if(init.body!==undefined&&!(init.body instanceof FormData)&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
      const target=base+url.pathname.slice(4)+url.search;
      if(input instanceof Request){{const request=new Request(target,input);return nativeFetch(request,{{...init,headers}})}}
      return nativeFetch(target,{{...init,headers}});
    }}
  }}catch(_){{}}
  return nativeFetch(input,init);
}};
}})();</script>'''


def inject_runtime_bootstrap(html: str, project_id: str, version: int, published: bool) -> str:
    bootstrap = runtime_bootstrap(project_id, version, published)
    for pattern in (r'<head[^>]*>', r'<html[^>]*>'):
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return html[:match.end()] + bootstrap + html[match.end():]
    return bootstrap + html
