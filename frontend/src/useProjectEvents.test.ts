import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectEventStream, type ProjectEvent } from './useProjectEvents'

const encoder = new TextEncoder()
const store = new Map<string, string>()
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value) },
    removeItem: (key: string) => { store.delete(key) },
  },
})

function event(id: number, type = 'project.refresh'): ProjectEvent {
  return {
    schema_version: '1.0', id, job_id: 'job-1', attempt_id: 1,
    type, timestamp: '2026-01-01T00:00:00+00:00', payload: {},
  }
}

function responseWith(
  events: ProjectEvent[],
  options: { onClose?: () => void; status?: number } = {},
) {
  return new Response(new ReadableStream({
    async start(controller) {
      try {
        for (const event of events) {
          controller.enqueue(encoder.encode(
            `id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
          ))
        }
        options.onClose?.()
        controller.close()
      } catch (error) {
        if (!options.onClose) controller.error(error)
      }
    },
  }), { status: options.status ?? 200 })
}

describe('ProjectEventStream', () => {
  beforeEach(() => {
    store.clear()
    store.set('forma_token', 'test-token')
  })

  it('resumes from the last cursor after an external abort', async () => {
    const onRefresh = vi.fn(async () => {
      if (onRefresh.mock.calls.length === 2) stream.stop()
    })
    let callCount = 0
    let lastHeaders: Record<string, string> | undefined
    const fetchFn = vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
      callCount += 1
      lastHeaders = options?.headers as Record<string, string>
      if (callCount === 1) return responseWith([event(1)])
      if (callCount === 2) throw new DOMException('Connection aborted', 'AbortError')
      return responseWith([event(2)])
    })
    const stream = new ProjectEventStream('project-1', {
      onRefresh, fetchFn: fetchFn as typeof fetch, backoffMs: 1, maxBackoffMs: 2,
    })
    await stream.start()

    expect(onRefresh).toHaveBeenCalledTimes(2)
    expect(fetchFn).toHaveBeenCalledTimes(3)
    expect(lastHeaders?.['Last-Event-ID']).toBe('1')
    expect(stream.currentCursor).toBe(2)
    expect(stream.isActive).toBe(false)
    expect(stream.isConnected).toBe(false)
  })

  it('aborts an active subscription and its reader', async () => {
    const onStatus = vi.fn()
    const stream = new ProjectEventStream('project-1', {
      onRefresh: vi.fn(), onStatus,
      fetchFn: async () => new Response(new ReadableStream({ start() {} }), { status: 200 }),
    })
    const starting = stream.start()
    await Promise.resolve()
    stream.stop()
    await starting
    expect(stream.isActive).toBe(false)
    expect(stream.isConnected).toBe(false)
    expect(onStatus).toHaveBeenCalledWith(false)
  })

  it('reconciles an expired cursor before resuming', async () => {
    const onRefresh = vi.fn(async () => {
      if (onRefresh.mock.calls.length === 3) stream.stop()
    })
    let callCount = 0
    let lastHeaders: Record<string, string> | undefined
    const fetchFn = vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
      callCount += 1
      lastHeaders = options?.headers as Record<string, string>
      if (callCount === 1) return responseWith([event(1)])
      if (callCount === 2) {
        return new Response(JSON.stringify({ detail: { error: 'cursor_expired', high_watermark: 1 } }), {
          status: 409, headers: { 'Content-Type': 'application/json' },
        })
      }
      return responseWith([event(2)])
    })
    const stream = new ProjectEventStream('project-1', {
      onRefresh, fetchFn: fetchFn as typeof fetch, backoffMs: 1, maxBackoffMs: 2,
    })
    await stream.start()
    expect(onRefresh).toHaveBeenCalledTimes(3)
    expect(stream.currentCursor).toBe(2)
    expect(lastHeaders?.['Last-Event-ID']).toBe('1')
  })
})
