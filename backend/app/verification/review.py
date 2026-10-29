"""Optional advisory model review, isolated from deterministic release evidence."""

import json

from ..config import Settings, settings
from ..database import workspace_db
from ..features import FeatureFlag, feature_enabled
from ..jobs.models import JobCancelledError
from ..jobs.redaction import redact_metadata, redact_output
from ..llm import complete
from ..workers.contracts import WorkerRole
from ..workers.credentials import CredentialBroker

MODEL_REVIEW_PATH = 'acceptance/model-review.json'
REVIEW_SYSTEM = '''You are an advisory application reviewer. Return only JSON with this shape:
{"summary":"short assessment","suggestions":[{"title":"...","detail":"...","severity":"low|medium|high","target":"file or check ID"}]}
You are not a build, test, or security authority. Never claim that failures can be waived or releases approved.'''


def _document(report: dict, status: str, provider: dict | None = None) -> dict:
    return {
        'schema_version': '1.0', 'kind': 'optional_model_review', 'gating': False,
        'status': status, 'project_id': report['project_id'], 'version': report['version'],
        'job_id': report['job_id'], 'attempt_id': report['attempt_id'],
        'spec_hash': report['spec_hash'], 'source_hash': report['source_hash'],
        'provider': provider['name'] if provider else None, 'model': provider['model'] if provider else None,
        'summary': '', 'suggestions': [], 'error': None,
    }


def _persist(user_id: int, project_id: str, version: int, review: dict) -> dict:
    content = json.dumps(review, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    with workspace_db(user_id) as db:
        db.execute('INSERT OR REPLACE INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                   (project_id, 'review', MODEL_REVIEW_PATH, content, version))
    return review


def latest_model_review(user_id: int, project_id: str, version: int) -> dict | None:
    with workspace_db(user_id) as db:
        row = db.execute(
            'SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
            (project_id, MODEL_REVIEW_PATH, version),
        ).fetchone()
    return json.loads(row['content']) if row else None


def _suggestions(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        suggestion = redact_metadata({
            'title': str(item.get('title') or 'Review suggestion')[:200],
            'detail': str(item.get('detail') or '')[:2000],
            'severity': item.get('severity') if item.get('severity') in {'low', 'medium', 'high'} else 'low',
            'target': str(item.get('target') or '')[:240],
        })
        result.append(suggestion)
    return result


def _prompt(report: dict) -> str:
    checks = [{
        'id': check['id'], 'status': check['status'], 'required': check['required'],
        'error': check.get('error', '')[:600],
    } for check in report['checks']]
    return (
        f'Review the deterministic verification outcomes for {report["project_id"]} version {report["version"]}.\n'
        f'Spec hash: {report["spec_hash"]}\nSource hash: {report["source_hash"]}\n'
        f'Deterministic status: {report["status"]}; can_publish={report["can_publish"]}.\n'
        f'Checks: {json.dumps(checks, ensure_ascii=False)}\n'
        'Offer concise implementation suggestions only. Do not modify release decisions or waive failures.'
    )


async def generate_model_review(
    user_id: int, project_id: str, version: int, report: dict,
    provider: dict | None, config: Settings | None = None,
) -> dict:
    config = config or settings
    if not feature_enabled(FeatureFlag.SPECIALIST_WORKERS_V1, config):
        review = _document(report, 'disabled')
        review['summary'] = 'Advisory model review is not enabled on this studio.'
        return _persist(user_id, project_id, version, review)
    if not provider:
        review = _document(report, 'unavailable')
        review['summary'] = 'Choose a model provider to request advisory review.'
        return _persist(user_id, project_id, version, review)
    try:
        supervised = CredentialBroker(provider).for_role(WorkerRole.SUPERVISOR)
        result = await complete(supervised, REVIEW_SYSTEM, _prompt(report))
        review = _document(report, 'completed', provider)
        review['summary'] = redact_output(str(result.get('summary') or 'Advisory review completed.'))[:2000]
        review['suggestions'] = _suggestions(result.get('suggestions'))
    except JobCancelledError as exc:
        review = _document(report, 'cancelled', provider)
        review['error'] = redact_output(str(exc))[:1000]
    except Exception as exc:
        review = _document(report, 'failed', provider)
        review['error'] = redact_output(f'{type(exc).__name__}: {exc}')[:1000]
    return _persist(user_id, project_id, version, review)
