import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { contractApprovalError, SpecReview } from './SpecReview'
import type { AppSpecEnvelope, Project } from '../types'

const envelope: AppSpecEnvelope = {
  schema_version: '1.0', compiler_version: '1.0', spec_hash: 'a'.repeat(64),
  spec: {
    schema_version: '1.0', compiler_version: '1.0',
    product: {
      name: 'Item Manager', brief: 'A shared workspace for item priorities.', users: ['Team members'],
      primary_workflow: 'Create and complete items.', acceptance_goals: ['A working shared workflow'],
    },
    architecture: { backend_mode: 'fastapi', source_format: 'multi-file', state_ownership: 'server' },
    entities: [{
      name: 'Item', relationships: [],
      fields: [
        { name: 'id', kind: 'integer', required: true, constraints: {} },
        { name: 'title', kind: 'string', required: true, constraints: { maxLength: 160 } },
        { name: 'completed', kind: 'boolean', required: true, constraints: {} },
      ],
    }],
    api: [
      { name: 'Runtime health', method: 'GET', path: '/api/health', entity: null, errors: [] },
      { name: 'List items', method: 'GET', path: '/api/items', entity: 'Item', errors: [] },
    ],
    frontend: { components: ['App', 'Workspace'], routes: ['/'], state_adapter: 'forma-api', accessibility: ['keyboard-navigation'] },
    dependencies: { python: ['httpx'], npm: ['react', 'vite'] },
    manifest: {
      files: [{ path: 'frontend/src/App.jsx', owner: 'frontend', max_bytes: 140000 }],
      generation_order: ['frontend/src/App.jsx'],
    },
    acceptance: [
      { name: 'Production build', kind: 'build', target: 'frontend/dist/index.html' },
      { name: 'Health check', kind: 'api', target: '/api/health' },
    ],
  },
}

const project: Project = {
  id: 'project-1', name: 'Item Manager', brief: 'A shared workspace.', description: '',
  stage: 'build', stage_index: 3, phase_index: 0, status: 'ready', auto_mode: false, current_version: 0,
  backend_mode: 'fastapi', backend_reason: 'Shared data', backend_enabled: true, source_format: 'multi-file',
  published_version: null, created_at: '', updated_at: '', messages: [], versions: [], events: [],
  artifacts: [{ id: 1, path: 'appspec.json', stage: 'plan', content: '', version: 0, created_at: '' }],
  appspec_enabled: true, appspec: envelope, appspec_valid: true, appspec_error: null,
}

describe('SpecReview', () => {
  it('renders the complete validated contract', () => {
    const html = renderToStaticMarkup(<SpecReview project={project} />)
    expect(html).toContain('Item Manager')
    expect(html).toContain('hash verified')
    expect(html).toContain('Create and complete items.')
    expect(html).toContain('maxLength: 160')
    expect(html).toContain('/api/items')
    expect(html).toContain('httpx')
    expect(html).toContain('react')
    expect(html).toContain('Production build')
    expect(html).toContain('frontend/src/App.jsx')
    expect(html).toContain('Review draft')
  })

  it('renders a validation failure without the contract content', () => {
    const invalid = { ...project, appspec: null, appspec_valid: false, appspec_error: 'Broken contract' }
    const html = renderToStaticMarkup(<SpecReview project={invalid} />)
    expect(html).toContain('AppSpec needs correction.')
    expect(html).toContain('Broken contract')
    expect(html).toContain('cannot proceed to compilation')
    expect(html).not.toContain('/api/items')
  })

  it('explains when the draft is not available yet', () => {
    const empty = { ...project, appspec: null, appspec_valid: null, appspec_error: null }
    const html = renderToStaticMarkup(<SpecReview project={empty} />)
    expect(html).toContain('contract draft appears after planning')
  })
})

describe('contractApprovalError', () => {
  it('blocks only an invalid contract with AppSpec enabled', () => {
    expect(contractApprovalError({ ...project, appspec_valid: false, appspec_error: 'Broken contract' })).toBe('Broken contract')
    expect(contractApprovalError(project)).toBe('')
    expect(contractApprovalError({ ...project, appspec_enabled: false, appspec_valid: false })).toBe('')
  })
})
