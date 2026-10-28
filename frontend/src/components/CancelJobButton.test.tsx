import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CancelJobButton } from './CancelJobButton'

describe('CancelJobButton', () => {
  it('shows ready and immediate cancelling states', () => {
    const ready = renderToStaticMarkup(<CancelJobButton cancelling={false} onCancel={() => {}} />)
    expect(ready).toContain('Cancel')
    expect(ready).not.toContain('disabled')

    const cancelling = renderToStaticMarkup(<CancelJobButton cancelling onCancel={() => {}} />)
    expect(cancelling).toContain('Cancelling…')
    expect(cancelling).toContain('disabled')
  })
})
