import asyncio
import uuid

from app import engine
from app.database import workspace_db, workspace_for
from app.source_packages import local_source_package

PLAN = '''# Plan

## Phase 1 — Foundation
Shell and reading list overview.

## Phase 2 — Core workflow
Add, rate, and archive books through /api/books.

## Phase 3 — Release polish
Accessibility and empty states.
'''


def make_project(user_id: int) -> str:
    project_id = uuid.uuid4().hex
    workspace_for(user_id)
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(id,name,brief,stage,stage_index,backend_mode,backend_reason,source_format)
                      VALUES(?,?,?,?,?,?,?,?)''', (
            project_id, 'Shelf', 'A shared reading list for a book club.', 'discovery', 0,
            'fastapi', 'Selected when this project was created.', 'multi-file',
        ))
    return project_id


def test_phase_plan_extracts_only_the_requested_phase():
    assert engine.phase_plan(PLAN, 2).startswith('## Phase 2')
    assert '/api/books' in engine.phase_plan(PLAN, 2)
    assert 'Accessibility' not in engine.phase_plan(PLAN, 2)
    assert engine.phase_plan('No headings here', 1) == 'No headings here'


def test_every_stage_builds_on_the_approved_upstream_documents(monkeypatch):
    user_id = 970100
    project_id = make_project(user_id)
    prompts: list[str] = []

    async def fake_complete(_provider, _system, prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {'document': '# Shelf\nPRODUCT-MARKER: members rate books together.',
                    'backend_required': True, 'backend_reason': 'Shared club data.'}
        if len(prompts) == 2:
            return {'document': '# Design\nDESIGN-MARKER: warm paper palette.'}
        if len(prompts) == 3:
            return {'document': PLAN}
        return {'files': local_source_package('Shelf', 'A shared reading list.', 1, 'fastapi'),
                'python_dependencies': []}

    async def skip_build(*_args, **_kwargs):
        return '<html></html>'

    monkeypatch.setattr(engine, 'complete', fake_complete)
    monkeypatch.setattr(engine, 'ensure_frontend_build', skip_build)
    provider = {'name': 'Test', 'model': 'test-model'}
    for _ in range(4):
        asyncio.run(engine.generate_stage(user_id, project_id, provider))

    _discovery, design, plan, build = prompts
    assert 'PRODUCT-MARKER' in design
    assert 'PRODUCT-MARKER' in plan and 'DESIGN-MARKER' in plan
    assert 'PRODUCT-MARKER' in build and 'DESIGN-MARKER' in build
    assert 'Shell and reading list overview' in build and '/api/books' not in build
    assert 'frontend/src/App.tsx' in build
    with workspace_db(user_id) as db:
        project = db.execute('SELECT stage,current_version,status FROM projects WHERE id=?', (project_id,)).fetchone()
        paths = {row['path'] for row in db.execute(
            'SELECT path FROM artifacts WHERE project_id=? AND version=1', (project_id,))}
    assert dict(project) == {'stage': 'build', 'current_version': 1, 'status': 'ready'}
    assert {'frontend/src/App.tsx', 'frontend/tsconfig.json', 'backend/app/api.py'} <= paths
