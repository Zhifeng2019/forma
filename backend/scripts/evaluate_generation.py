"""Evaluate deterministic generation quality from the checked-in fixture corpus."""

import argparse
import asyncio
from collections import defaultdict
from contextlib import contextmanager
from functools import partial
import inspect
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for import_path in (ROOT / 'backend', ROOT / 'backend' / 'tests'):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import httpx  # noqa: E402

from app.backend_engine import BACKEND_PATH, REQUIREMENTS_PATH, runtime_requirements  # noqa: E402
from app.config import Settings, settings  # noqa: E402
from app.engine import assemble_source_package, complete_package  # noqa: E402
from app.evaluation.quality import GenerationQuality, QualityCase, QualityMetric  # noqa: E402
from app.frontend_builder import ensure_frontend_build  # noqa: E402
from app.llm import complete  # noqa: E402
from app.runtime import runtime_manager  # noqa: E402
from app.security import create_token, encrypt_secret  # noqa: E402
from app.source_packages import validate_source_package  # noqa: E402
from app.spec.compiler import compile_package  # noqa: E402
from app.spec.schema import parse_appspec  # noqa: E402
from app.spec.service import compile_legacy_package, spec_artifacts  # noqa: E402
from app.verification.runner import verify_package  # noqa: E402
from fixtures.loader import FixturePack  # noqa: E402


class QualityEvaluationError(RuntimeError):
    pass


class FakeResponse:
    def __init__(self, content, finish_reason='stop'):
        self.status_code = 200
        self.text = content
        self._payload = {'choices': [{'finish_reason': finish_reason, 'message': {'content': content}}]}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses, **_kwargs):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append({'url': url, **kwargs})
        return self.responses.pop(0)


@contextmanager
def evaluation_settings(workspace):
    previous = {
        'data_dir': settings.data_dir,
        'appspec_v1': settings.appspec_v1,
        'acceptance_gate_v1': settings.acceptance_gate_v1,
        'durable_jobs_v1': settings.durable_jobs_v1,
        'studio_base_url': settings.studio_base_url,
    }
    settings.data_dir = str(workspace.data_dir)
    settings.appspec_v1 = True
    settings.acceptance_gate_v1 = True
    settings.durable_jobs_v1 = False
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(settings, name, value)


class QualityEvaluation:
    def __init__(self, pack, workspace):
        self.pack = pack
        self.workspace = workspace
        self.cases = []
        self.counts = defaultdict(lambda: [0, 0])
        self.prepared = {}
        self.studio_process = None

    def count(self, name, passed):
        self.counts[name][1] += 1
        self.counts[name][0] += int(bool(passed))

    async def case(
        self, case_id, category, expected, operation,
        first_valid=None, repair_invoked=False, source_checked=False, metric=None,
    ):
        passed = True
        error = None
        try:
            result = operation()
            actual = await result if inspect.isawaitable(result) else result
            if not isinstance(actual, str) or not actual:
                actual = 'passed'
        except Exception as exc:  # A failed case is evidence, not a reason to lose the remaining results.
            passed = False
            error = str(exc).replace(str(self.workspace.data_dir), '<workspace>')[:400]
            actual = f'{type(exc).__name__}: {error}'
        if first_valid is not None:
            self.count('first_pass_proposal_validity', passed and first_valid)
            self.count('repair_invocation', repair_invoked)
            if repair_invoked:
                self.count('repair_success', passed)
        if source_checked:
            self.count('source_import_validity', passed)
        if metric:
            self.count(metric, passed)
        self.count('case_success', passed)
        self.cases.append(QualityCase(
            id=case_id, category=category, passed=passed, expected=expected,
            actual=actual, error=error,
        ))

    def provider_document(self, key):
        return json.loads(self.pack.read_resource(self.pack.manifest.providers[key]))

    def compile_files(self, package_key, files=None):
        package = self.pack.manifest.packages[package_key]
        project = {
            'name': package.name, 'brief': package.brief,
            'backend_mode': package.backend_mode, 'source_format': package.source_format,
        }
        return compile_legacy_package(
            project, self.pack.package_files(package_key) if files is None else files,
            Settings(appspec_v1=True),
        )

    def prepare_project(self, package_key):
        if package_key in self.prepared:
            return self.prepared[package_key]
        result = self.workspace.materialize_project(f'{package_key}-current-unpublished')
        compiled = self.compile_files(package_key)
        artifacts = {**compiled.files, **spec_artifacts(compiled)}
        with self.workspace.database(result.workspace_db) as db:
            for path, content in artifacts.items():
                db.execute('INSERT OR REPLACE INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                           (result.project_id, 'build', path, content, result.current_version))
        for path, content in compiled.files.items():
            target = result.project_dir / 'versions' / f'v{result.current_version}' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.prepared[package_key] = (result, compiled)
        return result, compiled

    async def repair_json(self, key, finish_reason):
        client = FakeClient([
            FakeResponse(self.pack.read_resource(self.pack.manifest.providers[key]), finish_reason),
            FakeResponse(json.dumps(self.provider_document('legacy-package'))),
        ])
        provider = {
            'name': 'Fixture Provider', 'model': 'fixture-model',
            'base_url': 'http://fixture.invalid/v1',
            'api_key_encrypted': encrypt_secret('not-a-real-key'),
        }
        with patch('httpx.AsyncClient', lambda **_kwargs: client):
            result = await complete(provider, 'Evaluate a fixture', 'Return a valid package')
        self.compile_files('static-single', result['files'])
        return f'repaired-{len(client.calls)}-calls'

    async def repair_package(self):
        calls = []

        async def fake_complete(_provider, _system, _prompt):
            calls.append(_prompt)
            if len(calls) == 1:
                return self.provider_document('invalid-package-structure')
            return {'files': self.pack.package_files('fastapi-multi')}

        with patch('app.engine.complete', fake_complete):
            await complete_package({}, 'Fixture repair', 'Repair one invalid package', 1, '', 'fastapi', {})
        return f'repaired-{len(calls)}-calls'

    async def run_provider_cases(self):
        for key, provider in self.pack.manifest.providers.items():
            expected = f'{provider.expected.category}:{provider.expected.handling}'
            repair = provider.expected.handling == 'repair-once'
            first_valid = not repair and provider.expected.handling != 'reject'
            source_checked = key not in {'missing-requirements', 'invalid-appspec-contract'}
            if key == 'legacy-package':
                operation = partial(self.compile_files, 'static-single', self.provider_document(key)['files'])
            elif key == 'truncated-model-output':
                operation = partial(self.repair_json, key, 'length')
            elif key == 'invalid-json':
                operation = partial(self.repair_json, key, 'stop')
            elif key == 'invalid-package-structure':
                operation = self.repair_package
            elif key == 'missing-requirements':
                def normalize():
                    enriched = runtime_requirements(self.provider_document(key)['files']['requirements.txt'])
                    assert enriched.count('email-validator==') == 1
                    assert runtime_requirements(enriched) == enriched
                    return 'normalized'
                operation = normalize
            elif key == 'empty-python-init':
                def accept_empty_init():
                    files = self.pack.package_files('fastapi-multi')
                    files['backend/app/__init__.py'] = self.provider_document(key)['files']['backend/app/__init__.py']
                    validate_source_package(files, 'fastapi')
                    return 'accepted'
                operation = accept_empty_init
            elif key == 'native-fetch-adapter':
                operation = partial(self.compile_files, 'fastapi-single', self.provider_document(key)['files'])
            elif key == 'invalid-appspec-contract':
                def reject_contract():
                    try:
                        parse_appspec(self.provider_document(key))
                    except Exception as exc:
                        if type(exc).__name__ == 'AppSpecError':
                            return 'rejected'
                        raise
                    raise AssertionError('Invalid AppSpec was accepted')
                operation = reject_contract
            elif key == 'partial-package-overlay':
                def overlay():
                    merged = assemble_source_package(
                        self.pack.package_files('static-multi'), self.provider_document(key)['files'],
                    )
                    validate_source_package(merged, 'static')
                    return 'overlaid'
                operation = overlay
            else:
                raise AssertionError(f'No quality operation for provider fixture {key}')
            await self.case(
                f'provider:{key}', 'provider', expected, operation,
                first_valid=first_valid, repair_invoked=repair, source_checked=source_checked,
            )

    async def run_hash_cases(self):
        for key in self.pack.manifest.packages:
            def deterministic(package_key=key):
                first = self.compile_files(package_key)
                second = self.compile_files(package_key)
                assert first.files == second.files
                assert first.source_hash == second.source_hash
                assert first.spec_hash == second.spec_hash
                return 'identical'
            await self.case(f'hash:{key}', 'determinism', 'identical-hashes', deterministic,
                            source_checked=True, metric='deterministic_hash_reuse')

        def deterministic_appspec():
            source = self.pack.package_files('fastapi-multi')
            first = compile_package(parse_appspec(self.pack.appspec('item-manager')), source)
            second = compile_package(parse_appspec(self.pack.appspec('item-manager')), dict(reversed(list(source.items()))))
            assert first.manifest == second.manifest
            assert first.source_hash == second.source_hash and first.spec_hash == second.spec_hash
            return 'identical'
        await self.case('hash:item-manager', 'determinism', 'identical-hashes', deterministic_appspec,
                        source_checked=True, metric='deterministic_hash_reuse')

    async def run_execution_cases(self):
        for key in ('static-multi', 'fastapi-multi'):
            result, compiled = self.prepare_project(key)

            async def build(result=result, compiled=compiled):
                html = await ensure_frontend_build(result.user_id, result.project_id, 1, compiled.files)
                assert 'id="root"' in html
                return 'built'
            await self.case(f'build:{key}', 'build', 'production-build', build,
                            metric='production_build_success')

        for key in ('fastapi-single', 'fastapi-multi'):
            result, compiled = self.prepare_project(key)

            async def healthy(result=result, compiled=compiled, key=key):
                response = await runtime_manager.request(
                    result.project_id, 1, 'preview', compiled.files[BACKEND_PATH], compiled.files[REQUIREMENTS_PATH],
                    'GET', 'health', '', b'', '', source_format=compiled.spec.architecture.source_format,
                    files=compiled.files,
                )
                assert response.status_code == 200 and response.json()['status'] == 'ok'
                return 'healthy'
            await self.case(f'runtime:{key}', 'runtime', 'runtime-health', healthy,
                            metric='runtime_health')

    async def start_studio(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        env = {
            **os.environ, 'DATA_DIR': str(self.workspace.data_dir),
            'SECRET_KEY': settings.secret_key,
            'RUNTIME_PYTHON': sys.executable, 'STUDIO_BASE_URL': url,
            'APPSPEC_V1': 'true', 'ACCEPTANCE_GATE_V1': 'true', 'DURABLE_JOBS_V1': 'false',
        }
        self.studio_process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port),
            cwd=ROOT / 'backend', env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        settings.studio_base_url = url
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            for _ in range(60):
                if self.studio_process.returncode is not None:
                    raise QualityEvaluationError('The temporary verification studio exited during startup')
                try:
                    response = await client.get(f'{url}/api/health')
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
        raise QualityEvaluationError('The temporary verification studio did not become healthy')

    async def stop_studio(self):
        if self.studio_process and self.studio_process.returncode is None:
            try:
                os.killpg(self.studio_process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.studio_process.wait(), timeout=5)
            except TimeoutError:
                try:
                    os.killpg(self.studio_process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await self.studio_process.wait()
        self.studio_process = None

    async def run_verification_and_gate_cases(self):
        await self.start_studio()
        for key in ('static-single', 'fastapi-multi'):
            result, _compiled = self.prepare_project(key)

            async def verified(result=result):
                report = await verify_package(result.user_id, result.project_id, 1, force=True)
                assert report['can_publish'], report['summary']
                return report['status']
            await self.case(f'verification:{key}', 'verification', 'full-verification', verified,
                            metric='verification_success')

        result, _compiled = self.prepare_project('static-single')

        async def publish_valid(result=result):
            token = create_token(result.user_id)
            async with httpx.AsyncClient(base_url=settings.studio_base_url, timeout=180, trust_env=False) as client:
                response = await client.post(f'/api/projects/{result.project_id}/publish',
                                             headers={'Authorization': f'Bearer {token}'}, json={})
                assert response.status_code == 200, response.text
                return 'published'
        await self.case('gate:valid-release', 'publish-gate', 'publish-allowed', publish_valid,
                        metric='publish_gate_decisions')

        rejected = self.workspace.materialize_project('static-history')

        async def reject_invalid(rejected=rejected):
            token = create_token(rejected.user_id)
            async with httpx.AsyncClient(base_url=settings.studio_base_url, timeout=60, trust_env=False) as client:
                response = await client.post(f'/api/projects/{rejected.project_id}/publish',
                                             headers={'Authorization': f'Bearer {token}'}, json={})
                assert response.status_code == 409, response.text
                public = await client.get(f'/apps/{rejected.project_id}/')
                assert public.status_code == 200 and 'Fixture version 1' in public.text
                return 'rejected-preserved'
        await self.case('gate:invalid-release', 'publish-gate', 'reject-and-preserve', reject_invalid,
                        metric='publish_gate_decisions')

    async def run(self):
        await self.run_provider_cases()
        await self.run_hash_cases()
        await self.run_execution_cases()
        try:
            await self.run_verification_and_gate_cases()
        finally:
            await self.stop_studio()

    def finish(self):
        return GenerationQuality(
            case_success=QualityMetric.from_counts(*self.counts['case_success']),
            first_pass_proposal_validity=QualityMetric.from_counts(*self.counts['first_pass_proposal_validity']),
            repair_invocation=QualityMetric.from_counts(*self.counts['repair_invocation']),
            repair_success=QualityMetric.from_counts(*self.counts['repair_success']),
            source_import_validity=QualityMetric.from_counts(*self.counts['source_import_validity']),
            production_build_success=QualityMetric.from_counts(*self.counts['production_build_success']),
            runtime_health=QualityMetric.from_counts(*self.counts['runtime_health']),
            verification_success=QualityMetric.from_counts(*self.counts['verification_success']),
            publish_gate_decisions=QualityMetric.from_counts(*self.counts['publish_gate_decisions']),
            deterministic_hash_reuse=QualityMetric.from_counts(*self.counts['deterministic_hash_reuse']),
            cases=self.cases,
        )


async def _evaluate(workspace_root: Path, require_success: bool) -> GenerationQuality:
    pack = FixturePack()
    workspace = pack.workspace(workspace_root.resolve())
    evaluation = QualityEvaluation(pack, workspace)
    with evaluation_settings(workspace):
        try:
            await evaluation.run()
        finally:
            await runtime_manager.stop_all()
    report = evaluation.finish()
    failures = [case.id for case in report.cases if not case.passed]
    if require_success and failures:
        raise QualityEvaluationError(f'Generation-quality cases failed: {", ".join(failures)}')
    return report


async def evaluate_generation_quality(
    workspace_root: Path | None = None, require_success: bool = True,
) -> GenerationQuality:
    if workspace_root is not None:
        return await _evaluate(workspace_root, require_success)
    temporary_root = ROOT / 'data' / 'test-runtimes'
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='forma-quality-', dir=temporary_root) as directory:
        return await _evaluate(Path(directory), require_success)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, help='Empty temporary directory for generated evaluation artifacts.')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'backend' / 'tests' / 'evals' / 'generation.json')
    parser.add_argument('--allow-failures', action='store_true', help='Write a report even when quality cases fail.')
    args = parser.parse_args()
    report = asyncio.run(evaluate_generation_quality(args.workspace, require_success=not args.allow_failures))
    document = report.model_dump(mode='json')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + '\n')
    metrics = {name: value for name, value in document.items() if isinstance(value, dict) and 'numerator' in value}
    print(json.dumps({'output': str(args.output), 'metrics': metrics}, indent=2))


if __name__ == '__main__':
    main()
