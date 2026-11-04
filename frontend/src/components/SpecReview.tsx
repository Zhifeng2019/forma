import { systemText, statusLabel } from '../systemMessages'
import { useTranslation } from '../i18n'
import { CheckCircle2, Code2, Database, FileText, ListChecks, Package, ShieldCheck, XCircle } from 'lucide-react'
import type { AppSpecEntityField, Project } from '../types'

function constraints(field: AppSpecEntityField) {
  const values = Object.entries(field.constraints || {})
  return values.length ? values.map(([key, value]) => `${key}: ${value}`).join(' · ') : '—'
}

export function SpecReview({ project }: { project: Project }) {
  const { t } = useTranslation()
  if (project.appspec_valid === false) {
    return <div className="spec-review"><div className="spec-invalid" role="alert"><XCircle size={24} /><div><span className="eyebrow">{t("CONTRACT VALIDATION FAILED")}</span><h2>{t("Stored contract could not be read.")}</h2><p>{project.appspec_error ? systemText(project.appspec_error) : t("The stored contract is invalid.")}</p><small>{t("This saved contract does not block new builds. You can continue from the existing application.")}</small></div></div></div>
  }
  const envelope = project.appspec
  if (!envelope) {
    return <div className="spec-review"><div className="empty-state"><span><FileText size={27} /></span><h3>{t("No stored contract for this version")}</h3><p>{t("Saved contracts remain available on the versions that created them.")}</p></div></div>
  }
  const spec = envelope.spec
  const artifact = project.artifacts.find(item => item.path === 'appspec.json')
  const architecture = spec.architecture
  return <div className="spec-review">
    <header className="spec-heading"><div><span className="eyebrow">{t("STORED APPLICATION SPECIFICATION")}</span><h2>{spec.product.name}</h2><p>{t("Saved contract for this version. It is shown for reference and does not control new builds.")}</p></div><span className="spec-valid"><CheckCircle2 size={14} />{t("Schema & hash verified")}</span></header>
    <div className="spec-meta"><span>v{artifact?.version ?? 0}{artifact?.version === 0 ? t(" · Historical draft") : ''}</span><span>{architecture.backend_mode === 'fastapi' ? 'FastAPI' : t("Frontend only")}</span><span>{statusLabel(architecture.source_format)}</span><span title={envelope.spec_hash}>{t("Hash")} {envelope.spec_hash.slice(0, 12)}</span></div>

    <section className="spec-card spec-product"><header><ShieldCheck size={16} /><h3>{t("Product contract")}</h3></header><p>{spec.product.brief}</p><dl><div><dt>{t("Primary workflow")}</dt><dd>{spec.product.primary_workflow}</dd></div><div><dt>{t("State ownership")}</dt><dd>{architecture.state_ownership === 'server' ? t("Server-owned persistent state") : t("Browser-local state")}</dd></div><div><dt>{t("Frontend adapter")}</dt><dd>{spec.frontend.state_adapter}</dd></div><div><dt>{t("Users")}</dt><dd>{spec.product.users.length ? spec.product.users.join(', ') : t("Not declared")}</dd></div></dl>{spec.product.acceptance_goals.length > 0 && <div className="spec-goals">{spec.product.acceptance_goals.map(goal => <span key={goal}>{goal}</span>)}</div>}</section>

    <section className="spec-card"><header><Database size={16} /><h3>{t("Entities")} <span>{spec.entities.length}</span></h3></header>{spec.entities.length ? spec.entities.map(entity => <div className="spec-entity" key={entity.name}><h4>{entity.name}</h4><div className="spec-table-wrap"><table><caption className="sr-only">{t("Fields for {{name}}", { name: entity.name })}</caption><thead><tr><th>{t("Field")}</th><th>{t("Kind")}</th><th>{t("Required")}</th><th>{t("Constraints")}</th></tr></thead><tbody>{entity.fields.map(field => <tr key={field.name}><td><code>{field.name}</code></td><td>{statusLabel(field.kind)}</td><td>{field.required ? t("Yes") : t("Optional")}</td><td>{constraints(field)}</td></tr>)}</tbody></table></div>{entity.relationships.length > 0 && <small>{t("Relationships:")} {entity.relationships.join(', ')}</small>}</div>) : <p className="spec-muted">{t("This legacy package has no declared domain entities.")}</p>}</section>

    <section className="spec-card"><header><Code2 size={16} /><h3>{t("API operations")} <span>{spec.api.length}</span></h3></header>{spec.api.length ? <div className="spec-table-wrap"><table><caption className="sr-only">{t("Declared API operations")}</caption><thead><tr><th>{t("Method")}</th><th>{t("Path")}</th><th>{t("Operation")}</th><th>{t("Entity")}</th></tr></thead><tbody>{spec.api.map(operation => <tr key={`${operation.method}-${operation.path}`}><td><span className={`spec-method ${operation.method.toLowerCase()}`}>{operation.method}</span></td><td><code>{operation.path}</code></td><td>{operation.name}</td><td>{operation.entity || '—'}</td></tr>)}</tbody></table></div> : <p className="spec-muted">{t("No backend operations. This application uses browser-local state.")}</p>}</section>

    <section className="spec-card"><header><Package size={16} /><h3>{t("Reviewed dependencies")}</h3></header><div className="spec-dependencies"><div><h4>Python</h4>{spec.dependencies.python.length ? <ul>{spec.dependencies.python.map(item => <li key={item}>{item}</li>)}</ul> : <p>{t("Base FastAPI stack only")}</p>}</div><div><h4>npm</h4>{spec.dependencies.npm.length ? <ul>{spec.dependencies.npm.map(item => <li key={item}>{item}</li>)}</ul> : <p>{t("No npm dependencies")}</p>}</div></div><small>{t("These dependencies were recorded when this version was built.")}</small></section>

    <section className="spec-card"><header><ListChecks size={16} /><h3>{t("Acceptance checks")} <span>{spec.acceptance.length}</span></h3></header><ul className="spec-checks">{spec.acceptance.map(check => <li key={`${check.kind}-${check.target}-${check.name}`}><span>{statusLabel(check.kind)}</span><div><strong>{check.name}</strong><code>{check.target}</code></div></li>)}</ul></section>

    <details className="spec-card spec-manifest"><summary>{t("Build manifest")} <span>{t("{{count}} allowed files", { count: spec.manifest.files.length })}</span></summary><div className="spec-table-wrap"><table><caption className="sr-only">{t("Allowed source paths and owners")}</caption><thead><tr><th>{t("Path")}</th><th>{t("Owner")}</th><th>{t("Size limit")}</th></tr></thead><tbody>{spec.manifest.files.map(file => <tr key={file.path}><td><code>{file.path}</code></td><td>{statusLabel(file.owner)}</td><td>{Math.round(file.max_bytes / 1000)} KB</td></tr>)}</tbody></table></div><small>{t("Generation order:")} {spec.manifest.generation_order.join(' → ')}</small></details>
  </div>
}
