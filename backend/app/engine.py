import json
import re
from datetime import datetime, timezone
from .database import workspace_db
from .local_engine import product_document, design_document, plan_document, application_html
from .llm import complete, GenerationError

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


def provider_for_user(control, user_id):
    pref = control.execute('SELECT provider_id FROM preferences WHERE user_id=?', (user_id,)).fetchone()
    if not pref or not pref['provider_id']:
        return None
    row = control.execute('SELECT * FROM providers WHERE id=? AND enabled=1', (pref['provider_id'],)).fetchone()
    return dict(row) if row else None


async def generate_stage(user_id: int, project_id: str, provider: dict | None, feedback: str = ''):
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
                await _advance(db_user=user_id, project_id=project_id, provider=provider, feedback=feedback)
        except Exception as exc:
            with workspace_db(user_id) as db:
                db.execute("UPDATE projects SET status='error',updated_at=? WHERE id=?", (now(), project_id))
                add_event(db, project_id, str(exc), 'error')
                add_message(db, project_id, 'agent', f'I hit a problem: {exc}', 'error')
    finally:
        _running.discard(project_id)


async def _advance(db_user: int, project_id: str, provider: dict | None, feedback: str = ''):
    with workspace_db(db_user) as db:
        project = get_project(db, project_id)
        stage, name = project['stage'], project['name']
        brief = project['brief'] + (f"\n\nAdditional product direction:\n{project['description']}" if project['description'] else '')
        version = project['current_version']
        if stage == 'discovery':
            content = product_document(name, brief)
            if provider:
                result = await complete(provider, 'You are a senior product strategist. Create a concise, concrete product description.',
                    f'Product name: {name}\nUser brief: {brief}\nReturn {{"document":"markdown..."}} with vision, users, core workflow, scope and success criteria.')
                content = result.get('document', content)
            save_artifact(db, project_id, 'discovery', 'product.md', content, 0)
            next_stage, index = 'design', 1
            message = 'The product description is ready. Review the scope, then approve it to move into experience design.'
        elif stage == 'design':
            content = design_document(name)
            if provider:
                result = await complete(provider, 'You are a staff product designer and architect.',
                    f'Product: {name}\nBrief: {brief}\nReturn {{"document":"markdown..."}} covering visual direction, UX, information architecture, frontend and backend.')
                content = result.get('document', content)
            save_artifact(db, project_id, 'design', 'design.md', content, 0)
            next_stage, index = 'plan', 2
            message = 'The experience and technical design are ready for your feedback.'
        elif stage == 'plan':
            content = plan_document(name)
            if provider:
                result = await complete(provider, 'You are a pragmatic technical lead.',
                    f'Product: {name}\nBrief: {brief}\nReturn {{"document":"markdown..."}} with exactly three implementation phases. Each phase must end in a shareable working page.')
                content = result.get('document', content)
            save_artifact(db, project_id, 'plan', 'plan.md', content, 0)
            next_stage, index = 'build', 3
            message = 'The implementation is split into three shareable phases. Approve the plan to start building.'
        elif stage in {'build', 'review'}:
            phase = min(3, project['phase_index'] + 1)
            version += 1
            if provider:
                current = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? ORDER BY version DESC LIMIT 1',
                                     (project_id, 'index.html')).fetchone()
                result = await complete(provider, 'You are an expert frontend engineer. Return a complete, polished, responsive single-file HTML application. No external dependencies. Include accessible semantic markup and working JavaScript.',
                    f'Product: {name}\nBrief: {brief}\nImplementation phase: {phase}/3\nFeedback: {feedback}\nCurrent HTML to improve: {current["content"] if current else "None"}\nReturn {{"html":"<!doctype html>..."}}.')
                html = result.get('html', '')
                if '<html' not in html.lower() or '</html>' not in html.lower():
                    raise GenerationError('The generated application was not a complete HTML document.')
            else:
                html = application_html(name, brief, phase, feedback)
            save_artifact(db, project_id, 'build', 'index.html', html, version)
            db.execute('INSERT INTO versions(project_id,version,label,note) VALUES(?,?,?,?)',
                       (project_id, version, f'Phase {phase}' if stage == 'build' else 'Refinement', feedback or STAGE_LABELS[stage]))
            next_stage = 'build' if phase < 3 else 'review'
            index = 3 if phase < 3 else 4
            db.execute('UPDATE projects SET phase_index=? WHERE id=?', (phase, project_id))
            message = f'Phase {phase} is implemented and the preview has been updated.' if stage == 'build' else 'Your feedback has been applied in a new version.'
        elif stage == 'deploy':
            next_stage, index, message = 'deploy', 5, 'Your application is ready to publish.'
        else:
            raise GenerationError('This stage cannot be advanced.')
        db.execute('UPDATE projects SET stage=?,stage_index=?,current_version=?,status=?,updated_at=? WHERE id=?',
                   (next_stage, index, version, 'ready', now(), project_id))
        add_event(db, project_id, f'{STAGE_LABELS[stage]} completed', 'success')
        add_message(db, project_id, 'agent', message, 'stage', {'stage': next_stage, 'version': version})


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
