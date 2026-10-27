import { CheckCircle2, Code2, Database, FileText, ListChecks, Package, ShieldCheck, XCircle } from 'lucide-react'
import type { AppSpecEntityField, Project } from '../types'

export function contractApprovalError(project: Project) {
  if (!project.appspec_enabled || project.appspec_valid !== false) return ''
  return project.appspec_error || 'The AppSpec contract is invalid. Revise it before building.'
}

function constraints(field: AppSpecEntityField) {
  const values = Object.entries(field.constraints || {})
  return values.length ? values.map(([key, value]) => `${key}: ${value}`).join(' · ') : '—'
}

export function SpecReview({ project }: { project: Project }) {
  if (project.appspec_valid === false) {
    return <div className="spec-review"><div className="spec-invalid" role="alert"><XCircle size={24} /><div><span className="eyebrow">CONTRACT VALIDATION FAILED</span><h2>AppSpec needs correction.</h2><p>{contractApprovalError(project)}</p><small>Review the error and ask Forma to revise the contract. Invalid AppSpecs cannot proceed to compilation.</small></div></div></div>
  }
  const envelope = project.appspec
  if (!envelope) {
    return <div className="spec-review"><div className="empty-state"><span><FileText size={27} /></span><h3>Your contract draft appears after planning</h3><p>Forma will define the product workflow, entity, API, dependencies, and acceptance checks here before the first build.</p></div></div>
  }
  const spec = envelope.spec
  const artifact = project.artifacts.find(item => item.path === 'appspec.json')
  const architecture = spec.architecture
  return <div className="spec-review">
    <header className="spec-heading"><div><span className="eyebrow">APPLICATION SPECIFICATION</span><h2>{spec.product.name}</h2><p>Review the typed contract that drives deterministic source generation.</p></div><span className="spec-valid"><CheckCircle2 size={14} />Schema &amp; hash verified</span></header>
    <div className="spec-meta"><span>v{artifact?.version ?? 0}{artifact?.version === 0 ? ' · Review draft' : ''}</span><span>{architecture.backend_mode === 'fastapi' ? 'FastAPI' : 'Frontend only'}</span><span>{architecture.source_format}</span><span title={envelope.spec_hash}>Hash {envelope.spec_hash.slice(0, 12)}</span></div>

    <section className="spec-card spec-product"><header><ShieldCheck size={16} /><h3>Product contract</h3></header><p>{spec.product.brief}</p><dl><div><dt>Primary workflow</dt><dd>{spec.product.primary_workflow}</dd></div><div><dt>State ownership</dt><dd>{architecture.state_ownership === 'server' ? 'Server-owned persistent state' : 'Browser-local state'}</dd></div><div><dt>Frontend adapter</dt><dd>{spec.frontend.state_adapter}</dd></div><div><dt>Users</dt><dd>{spec.product.users.length ? spec.product.users.join(', ') : 'Not declared'}</dd></div></dl>{spec.product.acceptance_goals.length > 0 && <div className="spec-goals">{spec.product.acceptance_goals.map(goal => <span key={goal}>{goal}</span>)}</div>}</section>

    <section className="spec-card"><header><Database size={16} /><h3>Entities <span>{spec.entities.length}</span></h3></header>{spec.entities.length ? spec.entities.map(entity => <div className="spec-entity" key={entity.name}><h4>{entity.name}</h4><div className="spec-table-wrap"><table><caption className="sr-only">Fields for {entity.name}</caption><thead><tr><th>Field</th><th>Kind</th><th>Required</th><th>Constraints</th></tr></thead><tbody>{entity.fields.map(field => <tr key={field.name}><td><code>{field.name}</code></td><td>{field.kind}</td><td>{field.required ? 'Yes' : 'Optional'}</td><td>{constraints(field)}</td></tr>)}</tbody></table></div>{entity.relationships.length > 0 && <small>Relationships: {entity.relationships.join(', ')}</small>}</div>) : <p className="spec-muted">This legacy package has no declared domain entities.</p>}</section>

    <section className="spec-card"><header><Code2 size={16} /><h3>API operations <span>{spec.api.length}</span></h3></header>{spec.api.length ? <div className="spec-table-wrap"><table><caption className="sr-only">Declared API operations</caption><thead><tr><th>Method</th><th>Path</th><th>Operation</th><th>Entity</th></tr></thead><tbody>{spec.api.map(operation => <tr key={`${operation.method}-${operation.path}`}><td><span className={`spec-method ${operation.method.toLowerCase()}`}>{operation.method}</span></td><td><code>{operation.path}</code></td><td>{operation.name}</td><td>{operation.entity || '—'}</td></tr>)}</tbody></table></div> : <p className="spec-muted">No backend operations. This application uses browser-local state.</p>}</section>

    <section className="spec-card"><header><Package size={16} /><h3>Reviewed dependencies</h3></header><div className="spec-dependencies"><div><h4>Python</h4>{spec.dependencies.python.length ? <ul>{spec.dependencies.python.map(item => <li key={item}>{item}</li>)}</ul> : <p>Base FastAPI stack only</p>}</div><div><h4>npm</h4>{spec.dependencies.npm.length ? <ul>{spec.dependencies.npm.map(item => <li key={item}>{item}</li>)}</ul> : <p>No npm dependencies</p>}</div></div><small>Versions are pinned by Forma at compilation, never selected by the model.</small></section>

    <section className="spec-card"><header><ListChecks size={16} /><h3>Acceptance checks <span>{spec.acceptance.length}</span></h3></header><ul className="spec-checks">{spec.acceptance.map(check => <li key={`${check.kind}-${check.target}-${check.name}`}><span>{check.kind}</span><div><strong>{check.name}</strong><code>{check.target}</code></div></li>)}</ul></section>

    <details className="spec-card spec-manifest"><summary>Build manifest <span>{spec.manifest.files.length} allowed files</span></summary><div className="spec-table-wrap"><table><caption className="sr-only">Allowed source paths and owners</caption><thead><tr><th>Path</th><th>Owner</th><th>Size limit</th></tr></thead><tbody>{spec.manifest.files.map(file => <tr key={file.path}><td><code>{file.path}</code></td><td>{file.owner}</td><td>{Math.round(file.max_bytes / 1000)} KB</td></tr>)}</tbody></table></div><small>Generation order: {spec.manifest.generation_order.join(' → ')}</small></details>
  </div>
}
