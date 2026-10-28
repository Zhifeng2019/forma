import asyncio
from datetime import datetime, timezone
import json

from app.database import workspace_db
from app.frontend_builder import ensure_frontend_build, ensure_node_environment
from app.jobs.context import reset_job_context
from app.jobs.leases import lease_next_job
from app.jobs.service import create_job
from app.runtime import ManagedRuntime, runtime_manager
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from test_tool_runs import activate
from test_verification_runner import dummy_check, verification_project


def project_attempt(user_id, project_id):
    with workspace_db(user_id) as db:
        job_id, _ = create_job(db, project_id, 'build', 'provenance-input', 'advance-stage', 'provenance-trace')
        attempt = lease_next_job(db, 'provenance-worker', job_id=job_id)
    return job_id, attempt


def test_frontend_build_staging_promotion_and_cache_provenance():
    user_id = 960400
    project_id = verification_project(user_id, [dummy_check()])
    job_id, attempt = project_attempt(user_id, project_id)
    package = compile_package(local_default_appspec(
        'Verifier App', 'Exercise deterministic verification.', 'multi-file', 'static',
    ))

    async def scenario():
        token = activate(user_id, project_id, job_id, attempt)
        try:
            first = await ensure_frontend_build(user_id, project_id, 1, package.files, 'spec-fixture')
            second = await ensure_frontend_build(user_id, project_id, 1, package.files, 'spec-fixture')
            assert first == second
            await ensure_node_environment(user_id)
        finally:
            reset_job_context(token)

    asyncio.run(scenario())
    with workspace_db(user_id) as db:
        rows = db.execute('SELECT * FROM tool_runs WHERE job_id=? ORDER BY rowid', (job_id,)).fetchall()
    by_name = {}
    for row in rows:
        by_name.setdefault(row['tool_name'], []).append(row)
    assert len(by_name['frontend.staging']) == 1 and len(by_name['frontend.promotion']) == 1
    assert len(by_name['frontend.build']) == 1 and len(by_name['Frontend production build']) == 1
    for name in ('frontend.staging', 'frontend.promotion', 'frontend.build', 'Frontend production build'):
        for row in by_name[name]:
            provenance = json.loads(row['provenance'])
            assert row['status'] == 'succeeded' and provenance['spec_hash'] == 'spec-fixture'
            assert provenance['source_hash'] == package.source_hash
            assert provenance['package_hash'] and provenance['build_digest']
            assert provenance['vite_version'] and provenance['duration_ms'] >= 0
    assert json.loads(by_name['frontend.build'][0]['provenance'])['cache_hit'] is True
    process = json.loads(by_name['Frontend production build'][0]['provenance'])
    assert process['executable_version'] and process['studio_python_version'] and process['platform']
    node_cache = [row for row in by_name['node.environment']
                  if json.loads(row['provenance'])['cache_hit'] is True]
    assert node_cache
    assert json.loads(node_cache[-1]['provenance'])['dependency_versions']['vite']


def test_runtime_reuse_records_cache_source_spec_and_package():
    user_id = 960401
    project_id = verification_project(user_id, [dummy_check()])
    job_id, attempt = project_attempt(user_id, project_id)

    class Process:
        returncode = None

    async def scenario():
        runtime = ManagedRuntime(
            key=f'{project_id}:v1:preview', project_id=project_id, version=1, channel='preview',
            process=Process(), port=65535, started_at=datetime.now(timezone.utc).isoformat(),
            reader=asyncio.create_task(asyncio.sleep(0)), last_used=0,
        )
        runtime_manager._runtimes[runtime.key] = runtime
        token = activate(user_id, project_id, job_id, attempt)
        try:
            reused = await runtime_manager.ensure(
                project_id, 1, 'preview', 'from fastapi import FastAPI\napp = FastAPI()\n', '',
                spec_hash='runtime-spec',
            )
            assert reused is runtime
        finally:
            reset_job_context(token)
            runtime_manager._runtimes.pop(runtime.key, None)

    asyncio.run(scenario())
    with workspace_db(user_id) as db:
        row = db.execute("SELECT * FROM tool_runs WHERE job_id=? AND tool_name='runtime.reuse'", (job_id,)).fetchone()
    provenance = json.loads(row['provenance'])
    assert row['status'] == 'succeeded' and provenance['cache_hit'] is True
    assert provenance['spec_hash'] == 'runtime-spec' and provenance['source_hash']
    assert provenance['package_hash'] and provenance['duration_ms'] >= 0
