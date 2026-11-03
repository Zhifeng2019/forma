"""Planning inputs for LLM generation and immutable, per-version provenance."""

import hashlib
import json

from .llm import GenerationError

DOCUMENT_PATHS = ('product.md', 'design.md', 'plan.md')
UPSTREAM_DOCUMENTS = {'design': ('product.md',), 'plan': ('product.md', 'design.md')}


def read_version_context(value: str | None) -> dict | None:
    if value is None:
        return None
    try:
        context = json.loads(value)
        if context['schema_version'] != 1 or not isinstance(context['documents'], dict):
            raise ValueError('Unsupported planning context')
        if (not isinstance(context['missing_documents'], list)
                or set(context['documents']) - set(DOCUMENT_PATHS)
                or set(context['missing_documents']) != set(DOCUMENT_PATHS) - set(context['documents'])
                or context['document_basis'] not in {'workflow', 'legacy-unrecorded'}):
            raise ValueError('Incomplete planning context')
        for document in context['documents'].values():
            if hashlib.sha256(document['content'].encode()).hexdigest() != document['sha256']:
                raise ValueError('Planning document checksum mismatch')
        return context
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise GenerationError('The saved generation context is invalid. Restore its recorded planning inputs before continuing.') from exc


def capture_planning_context(db, project, paths=DOCUMENT_PATHS, *, inherit=False) -> dict:
    if inherit and project['current_version']:
        row = db.execute('SELECT generation_context FROM versions WHERE project_id=? AND version=?',
                         (project['id'], project['current_version'])).fetchone()
        previous = read_version_context(row['generation_context']) if row else None
        if previous is not None:
            # Later drafts must not silently replace the inputs approved for this app.
            return {
                'documents': previous['documents'],
                'missing_documents': previous['missing_documents'],
                'document_basis': previous['document_basis'],
                'inherited_from_version': project['current_version'],
            }
    documents = {}
    for path in paths:
        artifact = db.execute('''SELECT id,version,content,created_at FROM artifacts
            WHERE project_id=? AND path=? ORDER BY version DESC LIMIT 1''', (project['id'], path)).fetchone()
        if artifact and artifact['content'].strip():
            documents[path] = {
                'artifact_id': artifact['id'], 'artifact_version': artifact['version'],
                'created_at': artifact['created_at'], 'content': artifact['content'],
                'sha256': hashlib.sha256(artifact['content'].encode()).hexdigest(),
            }
    return {
        'documents': documents,
        'missing_documents': [path for path in paths if path not in documents],
        # Existing releases did not record which documents were approved or used.
        'document_basis': 'legacy-unrecorded' if project['current_version'] else 'workflow',
        'inherited_from_version': None,
    }


def generation_context(db, project, phase: int, operation: str, feedback: str,
                       backend_mode: str, provider: dict | None) -> dict:
    return {
        'schema_version': 1, 'operation': operation, 'phase': phase,
        'source_version': project['current_version'], 'source_format': project['source_format'],
        'backend_mode': backend_mode, 'generation_mode': 'llm' if provider else 'local-demo',
        'brief': project['brief'], 'additional_direction': project['description'], 'feedback': feedback,
        **capture_planning_context(db, project, inherit=True),
    }


def planning_prompt(context: dict, *, phase: int | None = None, operation: str = 'build') -> str:
    lines = ['Planning context:']
    if context['document_basis'] == 'legacy-unrecorded':
        lines.append('These are the available documents for a legacy application; their earlier approval/use was not recorded.')
    else:
        lines.append('These documents are the reviewed inputs carried forward by the product workflow.')
    for path in DOCUMENT_PATHS:
        if path not in context['documents']:
            continue
        document = context['documents'][path]
        lines.append(f'--- {path} (sha256 {document["sha256"]}) ---\n{document["content"]}\n--- end {path} ---')
    if context['missing_documents']:
        lines.append('Documents unavailable: ' + ', '.join(context['missing_documents']) +
                     '. Use the supplied brief, user direction, and existing source for missing context; do not invent prior approvals.')
    lines.append('Preserve the product requirements, UX decisions, and working behavior in these documents and the current source. '
                 'Keep earlier refinements in the source. Explicit current feedback may amend these requirements. '
                 'The selected backend architecture takes precedence over architectural assumptions in older documents.')
    if phase is not None:
        if operation == 'migrate':
            lines.append(f'This is an architecture migration at phase {phase}/3. Preserve the implemented scope; '
                         'do not advance the plan or implement later phases as part of the migration.')
        else:
            lines.append(f'The implementation plan defines the scope of phase {phase}/3. '
                         'Implement its work for this phase and preserve completed earlier phases. '
                         'Defer work assigned to later phases unless explicitly requested in the current feedback. '
                         'Leave a working preview after this phase.')
            if operation == 'refine':
                lines.append(f'Refine the current phase {phase}; feedback does not approve or advance the next phase.')
    return '\n\n'.join(lines)


def planning_fingerprint(db, project, *, inherit=False) -> str:
    inputs = {
        'brief': project['brief'], 'additional_direction': project['description'],
    }
    row = db.execute('SELECT generation_context FROM versions WHERE project_id=? AND version=?',
                     (project['id'], project['current_version'])).fetchone() if inherit else None
    if row and row['generation_context'] is not None:
        # Hash even an invalid record here. Validation belongs inside the job so
        # its normal error handling can mark the project/attempt as failed.
        inputs['recorded_context'] = row['generation_context']
    else:
        inputs['planning_context'] = capture_planning_context(db, project)
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
