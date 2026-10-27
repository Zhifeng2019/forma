import json
import re
from datetime import datetime, timezone
from .database import workspace_db
from .local_engine import product_document, design_document, plan_document, application_html
from .llm import complete, GenerationError
from .backend_engine import (
    BACKEND_PATH, REQUIREMENTS_PATH, application_prompt,
    local_backend_html, local_backend_source, recommend_backend, validate_application,
)
from .frontend_builder import ensure_frontend_build
from .source_packages import local_source_package, package_prompt, validate_source_package
from .features import FeatureFlag, feature_enabled
from .jobs.runner import run_generation_job
from .spec.contract import entity_contract
from .spec.generator import propose_appspec
from .spec.legacy_adapter import legacy_appspec
from .spec.schema import APPSPEC_PATH, SPEC_ARTIFACT_PATHS, appspec_document, parse_appspec
from .spec.service import compile_legacy_package, generate_appspec_package, spec_artifacts

STAGES = ['discovery', 'design', 'plan', 'build', 'review', 'deploy']
STAGE_LABELS = {
    'discovery': 'Product description', 'design': 'Experience design',
    'plan': 'Implementation plan', 'build': 'Phased implementation',
    'review': 'Review & improve', 'deploy': 'Ready to publish'
}
_running: set[str] = set()


def now():
    return datetime.now(timezone.utc).isoformat()


def add_message(db, project_id, role, content, kind='chat', metadata=None):
    db.execute('INSERT INTO messages(project_id,role,content,kind,metadata) VALUES(?,?,?,?,?)',
               (project_id, role, content, kind, json.dumps(metadata or {})))


def add_event(db, project_id, message, level='info'):
    db.execute('INSERT INTO events(project_id,message,level) VALUES(?,?,?)', (project_id, message, level))


def save_artifact(db, project_id, stage, path, content, version):
    db.execute('INSERT OR REPLACE INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
               (project_id, stage, path, content, version))


def get_project(db, project_id):
    return db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()


def generation_source_files(db, project_id: str, version: int) -> dict[str, str]:
    return {row['path']: row['content'] for row in db.execute(
        "SELECT path,content FROM artifacts WHERE project_id=? AND version=? AND path NOT IN (?,?) AND path NOT LIKE 'acceptance/%'",
        (project_id, version, *SPEC_ARTIFACT_PATHS),
    )}


def generation_appspec(db, project, version: int):
    if version < 0:
        return None
    row = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                     (project['id'], APPSPEC_PATH, version)).fetchone()
    if row:
        return json.loads(row['content'])
    files = generation_source_files(db, project['id'], version)
    if not files:
        return None
    return legacy_appspec(project, files).model_dump(mode='json', exclude_none=True)


async def review_appspec(db, project, provider, brief: str, feedback: str = ''):
    spec = parse_appspec(await propose_appspec(
        provider, project['name'], brief, project['source_format'], project['backend_mode'],
        phase=1, feedback=feedback, current_spec=generation_appspec(db, project, 0),
    ))
    entity_contract(spec)
    save_artifact(db, project['id'], 'plan', APPSPEC_PATH, appspec_document(spec), 0)
    add_event(db, project['id'], 'AppSpec draft is ready for contract review')
    return spec


def compile_with_appspec(project, files: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    if not feature_enabled(FeatureFlag.APPSPEC_V1):
        return files, {}
    compiled = compile_legacy_package(project, files)
    return compiled.files, spec_artifacts(compiled)


def provider_for_user(control, user_id):
    pref = control.execute('SELECT provider_id FROM preferences WHERE user_id=?', (user_id,)).fetchone()
    if not pref or not pref['provider_id']:
        return None
    row = control.execute('SELECT * FROM providers WHERE id=? AND enabled=1', (pref['provider_id'],)).fetchone()
    return dict(row) if row else None


def assemble_source_package(current_files: dict[str, str], generated_files: dict[str, str]) -> dict[str, str]:
    """Overlay model changes on the last complete package; never depend on partial file lists."""
    if not isinstance(generated_files, dict):
        raise GenerationError('The model must return a files object for the project package.')
    return {**current_files, **generated_files}


async def complete_package(
    provider: dict, name: str, brief: str, phase: int, feedback: str,
    backend_mode: str, current_files: dict[str, str],
) -> dict[str, str]:
    system = 'You are an expert React and FastAPI engineer. Generate a coherent multi-file project package.'
    result = await complete(provider, system, package_prompt(name, brief, phase, feedback, backend_mode, current_files))
    try:
        files = assemble_source_package(current_files, result.get('files', {}))
        return validate_source_package(files, backend_mode, result.get('python_dependencies'))
    except GenerationError as exc:
        adapter = str(result.get('files', {}).get('frontend/src/api.js', ''))[:4000]
        repair = package_prompt(name, brief, phase, feedback, backend_mode, current_files) + (
            f'\nThe previous response failed package validation: {exc}\n'
            f'Problematic frontend/src/api.js:\n{adapter or "Not supplied"}\n'
            'Regenerate the complete corrected package. Follow every required path and API contract exactly.'
        )
        result = await complete(provider, system, repair)
        try:
            files = assemble_source_package(current_files, result.get('files', {}))
            return validate_source_package(files, backend_mode, result.get('python_dependencies'))
        except GenerationError as second_error:
            excerpt = str(result.get('files', {}).get('frontend/src/api.js', ''))[:500]
            available = ', '.join(result.get('files', {}).keys())[:1800]
            raise GenerationError(f'{second_error} Available files: {available}. Offending frontend/src/api.js excerpt: {excerpt}') from second_error


async def generate_stage(
    user_id: int, project_id: str, provider: dict | None, feedback: str = '', revise: bool = False,
):
    if not feature_enabled(FeatureFlag.DURABLE_JOBS_V1):
        await _generate_stage_legacy(user_id, project_id, provider, feedback, revise)
        return
    with workspace_db(user_id) as db:
        project = get_project(db, project_id)
        if not project:
            return
        stage = project['stage']
        action = 'revise-stage' if revise else 'advance-stage'
        input_data = {
            'project_id': project_id,
            'stage': stage,
            'version': project['current_version'],
            'backend_mode': project['backend_mode'],
            'source_format': project['source_format'],
            'feedback': feedback,
            'revise': revise,
        }
    await run_generation_job(
        user_id, project_id, stage, action, input_data,
        lambda: _generate_stage_legacy(user_id, project_id, provider, feedback, revise),
    )


async def _generate_stage_legacy(
    user_id: int, project_id: str, provider: dict | None, feedback: str = '', revise: bool = False,
):
    if project_id in _running:
        raise GenerationError('This project is already being updated.')
    _running.add(project_id)
    try:
        with workspace_db(user_id) as db:
            project = get_project(db, project_id)
            if not project:
                return
            db.execute("UPDATE projects SET status='working',updated_at=? WHERE id=?", (now(), project_id))
            stage = project['stage']
            engine_label = f'{provider["name"]} · {provider["model"]}' if provider else 'Forma Local'
            add_event(db, project_id, f'{STAGE_LABELS.get(stage, stage)} started with {engine_label}')
        try:
            if stage == 'discovery':
                await _advance(db_user=user_id, project_id=project_id, provider=provider)
            else:
                await _advance(db_user=user_id, project_id=project_id, provider=provider, feedback=feedback, revise=revise)
        except Exception as exc:
            with workspace_db(user_id) as db:
                db.execute("UPDATE projects SET status='error',updated_at=? WHERE id=?", (now(), project_id))
                add_event(db, project_id, str(exc), 'error')
                add_message(db, project_id, 'agent', f'I hit a problem: {exc}', 'error')
    finally:
        _running.discard(project_id)


async def _advance(
    db_user: int, project_id: str, provider: dict | None, feedback: str = '', revise: bool = False,
):
    with workspace_db(db_user) as db:
        project = get_project(db, project_id)
        stage, name = project['stage'], project['name']
        brief = project['brief'] + (f"\n\nAdditional product direction:\n{project['description']}" if project['description'] else '')
        version = project['current_version']
        if stage == 'discovery':
            content = product_document(name, brief)
            result = {}
            if provider:
                result = await complete(provider, 'You are a senior product strategist and pragmatic software architect.',
                    f'Product name: {name}\nUser brief: {brief}\nReturn {{"document":"markdown...","backend_required":false,"backend_reason":"short evidence-based reason"}}. The document needs vision, users, core workflow, scope and success criteria. Choose backend_required only when the first release genuinely needs shared/server-side data, authentication, transactions, file handling, or integrations; a browser-only tool does not need a backend.')
                content = result.get('document', content)
            backend_mode = project['backend_mode']
            reason = project['backend_reason']
            if backend_mode == 'auto':
                required, reason = recommend_backend(project['brief'])
                if isinstance(result.get('backend_required'), bool):
                    required = result['backend_required']
                    reason = str(result.get('backend_reason') or reason).strip()[:500]
                backend_mode = 'fastapi' if required else 'static'
            elif not reason:
                reason = 'Selected when this project was created.'
            db.execute('UPDATE projects SET backend_mode=?,backend_reason=? WHERE id=?',
                       (backend_mode, reason, project_id))
            save_artifact(db, project_id, 'discovery', 'product.md', content, 0)
            add_event(db, project_id,
                      f'Architecture: {"FastAPI backend" if backend_mode == "fastapi" else "frontend only"} — {reason}')
            next_stage, index = 'design', 1
            message = 'The product description is ready. Review the scope, then approve it to move into experience design.'
        elif stage == 'design':
            backend_mode = project['backend_mode']
            content = design_document(name, backend_mode, project['backend_reason'])
            if provider:
                result = await complete(provider, 'You are a staff product designer and architect.',
                    f'Product: {name}\nBrief: {brief}\nSelected architecture: {backend_mode}\nArchitecture reason: {project["backend_reason"]}\nReturn {{"document":"markdown..."}} covering visual direction, UX, information architecture, frontend and the selected backend architecture. Do not change the architecture. For FastAPI apps, document the /api contract and the Forma.api frontend bridge.')
                content = result.get('document', content)
            save_artifact(db, project_id, 'design', 'design.md', content, 0)
            next_stage, index = 'plan', 2
            message = 'The experience and technical design are ready for your feedback.'
        elif stage == 'plan':
            backend_mode = project['backend_mode']
            content = plan_document(name, backend_mode)
            if provider:
                result = await complete(provider, 'You are a pragmatic technical lead.',
                    f'Product: {name}\nBrief: {brief}\nSelected architecture: {backend_mode}\nReturn {{"document":"markdown..."}} with exactly three implementation phases. Each phase must end in a shareable working page. For FastAPI apps, evolve the frontend and Python API together and include health and persistence checks.')
                content = result.get('document', content)
            save_artifact(db, project_id, 'plan', 'plan.md', content, 0)
            if feature_enabled(FeatureFlag.APPSPEC_V1):
                await review_appspec(db, project, provider, brief)
            next_stage, index = 'build', 3
            message = 'The implementation is split into three shareable phases. Approve the plan to start building.'
        elif stage in {'build', 'review'}:
            # Feedback refines the current phase; only explicit approval advances it.
            phase = max(1, project['phase_index']) if revise else min(3, project['phase_index'] + 1)
            version += 1
            backend_mode = project['backend_mode']
            source_format = project['source_format']
            appspec_enabled = feature_enabled(FeatureFlag.APPSPEC_V1)
            if appspec_enabled:
                compiled = await generate_appspec_package(
                    project, provider, phase, feedback,
                    generation_appspec(db, project, version - 1), brief=brief,
                )
                files, provenance = compiled.files, spec_artifacts(compiled)
            elif source_format == 'multi-file':
                current_files = generation_source_files(db, project_id, version - 1)
                if provider:
                    files = await complete_package(provider, name, brief, phase, feedback, backend_mode, current_files)
                else:
                    files = local_source_package(name, brief, phase, backend_mode)
            elif backend_mode == 'fastapi':
                current = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? ORDER BY version DESC LIMIT 1',
                                     (project_id, 'index.html')).fetchone()
                current_backend = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? ORDER BY version DESC LIMIT 1',
                                             (project_id, BACKEND_PATH)).fetchone()
                if provider:
                    result = await complete(
                        provider,
                        'You are an expert full-stack engineer. Build a polished single-file HTML frontend and a focused, secure FastAPI backend as one coherent application.',
                        application_prompt(name, brief, phase, feedback,
                                           current['content'] if current else '',
                                           current_backend['content'] if current_backend else ''),
                    )
                    html, python_source, requirements = validate_application(
                        result.get('html', ''), result.get('python', result.get('backend', '')),
                        result.get('requirements'),
                    )
                else:
                    html, python_source, requirements = validate_application(
                        local_backend_html(name, brief, phase), local_backend_source(name),
                    )
            else:
                if provider:
                    current = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? ORDER BY version DESC LIMIT 1',
                                         (project_id, 'index.html')).fetchone()
                    result = await complete(provider, 'You are an expert frontend engineer. Return a complete, polished, responsive single-file HTML application. No external dependencies or backend. Include accessible semantic markup and working JavaScript.',
                        f'Product: {name}\nBrief: {brief}\nImplementation phase: {phase}/3\nFeedback: {feedback}\nCurrent HTML to improve: {current["content"] if current else "None"}\nReturn {{"html":"<!doctype html>..."}}.')
                    html = result.get('html', '')
                    if '<html' not in html.lower() or '</html>' not in html.lower():
                        raise GenerationError('The generated application was not a complete HTML document.')
                else:
                    html = application_html(name, brief, phase, feedback)
            if source_format == 'single-file' and not appspec_enabled:
                files = {'index.html': html}
                if backend_mode == 'fastapi':
                    files.update({BACKEND_PATH: python_source, REQUIREMENTS_PATH: requirements})
            if not appspec_enabled:
                files, provenance = compile_with_appspec(project, files)
            if source_format == 'multi-file':
                await ensure_frontend_build(db_user, project_id, version, files)
            for path, content in files.items():
                save_artifact(db, project_id, 'build', path, content, version)
            for path, content in provenance.items():
                save_artifact(db, project_id, 'build', path, content, version)
            version_label = 'Refinement' if revise or stage == 'review' else f'Phase {phase}'
            db.execute('INSERT INTO versions(project_id,version,label,note,backend_mode,source_format) VALUES(?,?,?,?,?,?)',
                       (project_id, version, version_label, feedback or STAGE_LABELS[stage], backend_mode, source_format))
            next_stage = stage if revise else 'build' if phase < 3 else 'review'
            index = project['stage_index'] if revise else 3 if phase < 3 else 4
            db.execute('UPDATE projects SET phase_index=? WHERE id=?', (phase, project_id))
            message = ('Your feedback has been applied in a new version.' if revise else
                       f'Phase {phase} is implemented and the preview has been updated.' if stage == 'build' else
                       'Your feedback has been applied in a new version.')
        elif stage == 'deploy':
            next_stage, index, message = 'deploy', 5, 'Your application is ready to publish.'
        else:
            raise GenerationError('This stage cannot be advanced.')
        db.execute('UPDATE projects SET stage=?,stage_index=?,current_version=?,status=?,updated_at=? WHERE id=?',
                   (next_stage, index, version, 'ready', now(), project_id))
        completion = f'Feedback applied to version {version}' if revise and stage in {'build', 'review'} else f'{STAGE_LABELS[stage]} completed'
        add_event(db, project_id, completion, 'success')
        add_message(db, project_id, 'agent', message, 'stage', {'stage': next_stage, 'version': version})


async def revise_document(
    user_id: int, project_id: str, provider: dict | None, feedback: str,
) -> None:
    if not feature_enabled(FeatureFlag.DURABLE_JOBS_V1):
        await _revise_document_legacy(user_id, project_id, provider, feedback)
        return
    with workspace_db(user_id) as db:
        project = get_project(db, project_id)
        if not project:
            return
        stage = project['stage']
        input_data = {
            'project_id': project_id,
            'stage': stage,
            'version': project['current_version'],
            'source_format': project['source_format'],
            'feedback': feedback,
        }
    await run_generation_job(
        user_id, project_id, stage, 'revise-document', input_data,
        lambda: _revise_document_legacy(user_id, project_id, provider, feedback),
    )


async def _revise_document_legacy(
    user_id: int, project_id: str, provider: dict | None, feedback: str,
) -> None:
    if project_id in _running:
        raise GenerationError('This project is already being updated.')
    _running.add(project_id)
    try:
        with workspace_db(user_id) as db:
            project = get_project(db, project_id)
            if not project:
                return
            db.execute("UPDATE projects SET status='working',updated_at=? WHERE id=?", (now(), project_id))
            engine_label = f'{provider["name"]} · {provider["model"]}' if provider else 'Forma Local'
            add_event(db, project_id, f'Document revision started with {engine_label}')
        try:
            await _revise_document(user_id, project_id, provider, feedback)
        except Exception as exc:
            with workspace_db(user_id) as db:
                db.execute("UPDATE projects SET status='error',updated_at=? WHERE id=?", (now(), project_id))
                add_event(db, project_id, str(exc), 'error')
                add_message(db, project_id, 'agent', f'I hit a problem: {exc}', 'error')
    finally:
        _running.discard(project_id)


async def _revise_document(
    user_id: int, project_id: str, provider: dict | None, feedback: str,
) -> None:
    with workspace_db(user_id) as db:
        project = get_project(db, project_id)
        stage = project['stage']
        artifact_stage = {'design': 'discovery', 'plan': 'design', 'build': 'plan'}.get(stage)
        artifact_path = {'discovery': 'product.md', 'design': 'design.md', 'plan': 'plan.md'}.get(artifact_stage)
        db.execute("UPDATE projects SET description=description || ?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (f"\n- {feedback[:1000]}", project_id))
        artifact = db.execute('SELECT content,version FROM artifacts WHERE project_id=? AND path=? ORDER BY version DESC LIMIT 1',
                              (project_id, artifact_path)).fetchone() if artifact_path else None
        if artifact:
            if provider:
                result = await complete(
                    provider,
                    'You are a senior product designer. Revise the supplied artifact in response to feedback while preserving its Markdown structure.',
                    f'Feedback: {feedback}\nCurrent document:\n{artifact["content"]}\nReturn {{"document":"complete revised markdown..."}}.',
                )
                content = result.get('document', artifact['content'])
            else:
                content = artifact['content'] + f'\n\n## Revision direction\n{feedback}\n'
            save_artifact(db, project_id, artifact_stage, artifact_path, content, artifact['version'])
            if artifact_stage == 'plan' and feature_enabled(FeatureFlag.APPSPEC_V1):
                review_brief = project['brief'] + (
                    f'\n\nAdditional product direction:\n{project["description"]}' if project['description'] else ''
                )
                await review_appspec(db, project, provider, review_brief, feedback)
            add_event(db, project_id, f'{artifact_path} revised from feedback', 'success')
            add_message(db, project_id, 'agent',
                        f'I’ve applied your feedback to `{artifact_path}` and carried the direction forward into the next stages.')
        else:
            add_message(db, project_id, 'agent', f'Noted. I’ll carry this direction into the next artifact: “{feedback[:240]}”')
        db.execute("UPDATE projects SET status='ready',updated_at=? WHERE id=?", (now(), project_id))


async def migrate_architecture(
    user_id: int, project_id: str, target: str, provider: dict | None, feedback: str = '',
    deferred: bool = False,
) -> None:
    if target not in {'static', 'fastapi'}:
        raise GenerationError('Choose either frontend-only or FastAPI architecture.')
    if not feature_enabled(FeatureFlag.DURABLE_JOBS_V1):
        await _migrate_architecture_legacy(user_id, project_id, target, provider, feedback, deferred)
        return
    with workspace_db(user_id) as db:
        project = get_project(db, project_id)
        if not project:
            return
        stage = project['stage']
        input_data = {
            'project_id': project_id,
            'stage': stage,
            'version': project['current_version'],
            'backend_mode': project['backend_mode'],
            'source_format': project['source_format'],
            'target': target,
            'feedback': feedback,
        }
    await run_generation_job(
        user_id, project_id, stage, 'migrate', input_data,
        lambda: _migrate_architecture_legacy(user_id, project_id, target, provider, feedback, deferred),
    )


async def _migrate_architecture_legacy(
    user_id: int, project_id: str, target: str, provider: dict | None, feedback: str = '',
    deferred: bool = False,
) -> None:
    if target not in {'static', 'fastapi'}:
        raise GenerationError('Choose either frontend-only or FastAPI architecture.')
    if project_id in _running:
        raise GenerationError('This project is already being updated.')
    with workspace_db(user_id) as db:
        project = get_project(db, project_id)
        if not project:
            return
        if project['backend_mode'] == target:
            raise GenerationError(f'This project already uses {target} architecture.')
        if project['status'] == 'working' and not deferred:
            raise GenerationError('Wait for the current generation to finish before migrating.')
    _running.add(project_id)
    try:
        with workspace_db(user_id) as db:
            db.execute("UPDATE projects SET status='working',updated_at=? WHERE id=?", (now(), project_id))
            add_event(db, project_id, f'Architecture migration to {target} started')
        try:
            await _migrate_architecture(user_id, project_id, target, provider, feedback)
        except Exception as exc:
            with workspace_db(user_id) as db:
                db.execute("UPDATE projects SET status='error',updated_at=? WHERE id=?", (now(), project_id))
                add_event(db, project_id, str(exc), 'error')
                add_message(db, project_id, 'agent', f'I hit a problem: {exc}', 'error')
    finally:
        _running.discard(project_id)


async def _migrate_architecture(
    user_id: int, project_id: str, target: str, provider: dict | None, feedback: str,
) -> None:
    with workspace_db(user_id) as db:
        project = get_project(db, project_id)
        name, brief = project['name'], project['brief']
        version = project['current_version']
        reason = ('Added a dedicated FastAPI service and shared application state.' if target == 'fastapi'
                  else 'Moved to a portable frontend-only architecture without a product server.')
        if feedback:
            reason = f'{reason} Direction: {feedback[:240]}'
        if not version:
            db.execute('UPDATE projects SET backend_mode=?,backend_reason=?,status=?,updated_at=? WHERE id=?',
                       (target, reason, 'ready', now(), project_id))
            if feature_enabled(FeatureFlag.APPSPEC_V1):
                spec_project = dict(project)
                spec_project['backend_mode'] = target
                await review_appspec(db, spec_project, provider, brief, feedback)
            add_event(db, project_id, f'Architecture changed to {target} before the first build', 'success')
            add_message(db, project_id, 'agent',
                        f'Architecture updated to {target}. The next build will use this foundation.', 'stage',
                        {'stage': project['stage'], 'version': 0})
            return

        if project['source_format'] == 'multi-file':
            await _migrate_source_package(user_id, project_id, target, provider, feedback, reason)
            return

        current = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                             (project_id, 'index.html', version)).fetchone()
        if not current:
            raise GenerationError('The current application source is unavailable for migration.')
        current_backend = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                                     (project_id, BACKEND_PATH, version)).fetchone()
        phase = max(1, project['phase_index'])
        next_version = version + 1
        direction = (f'Architecture migration to {target}. Preserve the current visual design and working interactions. '
                     f'User direction: {feedback or "None"}')
        spec_project = dict(project)
        spec_project['backend_mode'] = target
        appspec_enabled = feature_enabled(FeatureFlag.APPSPEC_V1)
        if appspec_enabled:
            compiled = await generate_appspec_package(
                spec_project, provider, phase, feedback, generation_appspec(db, project, version),
                brief=f'{brief}\n\n{direction}',
            )
            files, provenance = compiled.files, spec_artifacts(compiled)
        elif target == 'fastapi':
            direction += (' Replace browser-owned shared state with the new FastAPI service. Keep the existing '
                          'frontend recognizable while adding a complete API and Forma.api integration.')
            if provider:
                result = await complete(
                    provider,
                    'You are an expert full-stack engineer performing a careful architecture migration.',
                    application_prompt(name, brief, phase, direction, current['content'],
                                       current_backend['content'] if current_backend else ''),
                )
                html, python_source, requirements = validate_application(
                    result.get('html', ''), result.get('python', result.get('backend', '')),
                )
            else:
                html, python_source, requirements = validate_application(
                    local_backend_html(name, brief, phase), local_backend_source(name),
                )
        else:
            direction += (' Remove Forma.api and every server dependency. Preserve the product workflow with '
                          'browser-local state and a complete static HTML document.')
            if provider:
                result = await complete(
                    provider,
                    'You are an expert frontend engineer performing a careful migration to a static application.',
                    f'Product: {name}\nBrief: {brief}\n{direction}\nCurrent HTML:\n{current["content"]}\n'
                    f'Current backend whose behavior should be adapted into browser state:\n'
                    f'{current_backend["content"] if current_backend else "None"}\n'
                    'Return {"html":"<!doctype html>..."}. The result must not contain Forma.api or require a server.',
                )
                html = result.get('html', '')
                if '<html' not in html.lower() or '</html>' not in html.lower():
                    raise GenerationError('The migrated application was not a complete HTML document.')
                if re.search(r'(?:window\.)?Forma\.api\s*\(', html):
                    raise GenerationError('The frontend-only migration still contains backend calls. Please retry.')
            else:
                html = application_html(name, brief, phase, direction)
        if not appspec_enabled:
            files = {'index.html': html}
            if target == 'fastapi':
                files.update({BACKEND_PATH: python_source, REQUIREMENTS_PATH: requirements})
            files, provenance = compile_with_appspec(spec_project, files)
        for path, content in files.items():
            save_artifact(db, project_id, 'build', path, content, next_version)
        for path, content in provenance.items():
            save_artifact(db, project_id, 'build', path, content, next_version)
        label = 'FastAPI migration' if target == 'fastapi' else 'Frontend-only migration'
        db.execute('INSERT INTO versions(project_id,version,label,note,backend_mode,source_format) VALUES(?,?,?,?,?,?)',
                   (project_id, next_version, label, feedback or reason, target, project['source_format']))
        db.execute('''UPDATE projects SET backend_mode=?,backend_reason=?,current_version=?,status=?,updated_at=?
                      WHERE id=?''', (target, reason, next_version, 'ready', now(), project_id))
        add_event(db, project_id, f'Architecture migrated to {target} as version {next_version}', 'success')
        add_message(db, project_id, 'agent',
                    f'Version {next_version} now uses {target}. Your phase and published release are unchanged.',
                    'stage', {'stage': project['stage'], 'version': next_version})


async def _migrate_source_package(
    user_id: int, project_id: str, target: str, provider: dict | None, feedback: str, reason: str,
) -> None:
    with workspace_db(user_id) as db:
        project = get_project(db, project_id)
        version = project['current_version']
        next_version = version + 1
        direction = (f'Architecture migration to {target}. Preserve the current React design and interactions. '
                     f'User direction: {feedback or "None"}')
        spec_project = dict(project)
        spec_project['backend_mode'] = target
        if feature_enabled(FeatureFlag.APPSPEC_V1):
            compiled = await generate_appspec_package(
                spec_project, provider, max(1, project['phase_index']), feedback,
                generation_appspec(db, project, version), brief=f'{project["brief"]}\n\n{direction}',
            )
            files, provenance = compiled.files, spec_artifacts(compiled)
        else:
            current_files = generation_source_files(db, project_id, version)
            if provider:
                files = await complete_package(
                    provider, project['name'], project['brief'], max(1, project['phase_index']), direction, target, current_files,
                )
            else:
                files = local_source_package(project['name'], project['brief'], max(1, project['phase_index']), target)
            files, provenance = compile_with_appspec(spec_project, files)
        await ensure_frontend_build(user_id, project_id, next_version, files)
        for path, content in files.items():
            save_artifact(db, project_id, 'build', path, content, next_version)
        for path, content in provenance.items():
            save_artifact(db, project_id, 'build', path, content, next_version)
        label = 'FastAPI migration' if target == 'fastapi' else 'Frontend-only migration'
        db.execute('INSERT INTO versions(project_id,version,label,note,backend_mode,source_format) VALUES(?,?,?,?,?,?)',
                   (project_id, next_version, label, feedback or reason, target, project['source_format']))
        db.execute('''UPDATE projects SET backend_mode=?,backend_reason=?,current_version=?,status=?,updated_at=?
                      WHERE id=?''', (target, reason, next_version, 'ready', now(), project_id))
        add_event(db, project_id, f'Architecture migrated to {target} as version {next_version}', 'success')
        add_message(db, project_id, 'agent',
                    f'Version {next_version} now uses {target}. Your phase and published release are unchanged.',
                    'stage', {'stage': project['stage'], 'version': next_version})


def safe_selector(selection: dict | None) -> str:
    if not selection:
        return ''
    selector = str(selection.get('selector', ''))[:300]
    text = str(selection.get('text', ''))[:160]
    return f'\nSelected element: {selector}\nSelected text: {text}' if selector else ''


def validate_project_id(value: str):
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Invalid project id')
    return value
