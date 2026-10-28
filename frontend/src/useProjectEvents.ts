import { useEffect, useRef } from 'react'
import { getToken } from './api'

export type ProjectEvent = {
  schema_version: string; id: number; job_id: string; attempt_id: number | null
  type: string; timestamp: string; payload: Record<string, unknown>
}
type RefreshCallback = () => void | Promise<void>
type StatusCallback = (connected: boolean) => void
type StreamOptions = {
  onRefresh: RefreshCallback
  onStatus?: StatusCallback
  fetchFn?: typeof fetch
  backoffMs?: number
  maxBackoffMs?: number
}

const REFRESH_EVENTS = new Set(['project.refresh', 'verification.report', 'job.succeeded', 'job.cancelled', 'job.failed'])
const decoder = new TextDecoder()

function abortError() {
  return new DOMException('The event stream was aborted', 'AbortError')
}
function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const timer = globalThis.setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    function onAbort() {
      globalThis.clearTimeout(timer)
      reject(abortError())
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

export class ProjectEventStream {
  private active = false
  private controller: AbortController | null = null
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null
  private failures = 0
  private connected = false
  private cursor = 0

  constructor(private projectId: string, private options: StreamOptions) {}

  get currentCursor() { return this.cursor }
  get isConnected() { return this.connected }
  get isActive() { return this.active }

  private status(connected: boolean) {
    if (this.connected === connected) return
    this.connected = connected
    this.options.onStatus?.(connected)
  }

  async start() {
    if (this.active) return
    if (!getToken()) return
    this.active = true
    while (this.active) {
      try {
        await this.connect()
      } catch {
        if (!this.active) break
        this.status(false)
      }
      if (!this.active) break
      this.failures += 1
      const backoff = Math.min(
        this.options.maxBackoffMs ?? 10_000,
        (this.options.backoffMs ?? 1_000) * 2 ** Math.max(0, this.failures - 1),
      )
      if (!this.active) break
      await delay(backoff, this.controller!.signal)
    }
    this.status(false)
  }

  stop() {
    this.active = false
    this.controller?.abort()
    if (this.reader) void this.reader.cancel().catch(() => {})
    this.status(false)
  }

  private async connect() {
    const token = getToken()
    if (!token) { this.active = false; return }
    this.controller = new AbortController()
    const headers: Record<string, string> = {
      Accept: 'text/event-stream', Authorization: `Bearer ${token}`,
    }
    if (this.cursor > 0) headers['Last-Event-ID'] = String(this.cursor)
    const fetchFn = this.options.fetchFn ?? fetch
    const response = await fetchFn(`/api/projects/${this.projectId}/events?follow=true&heartbeat_seconds=15`, {
      headers, signal: this.controller.signal,
    })
    if (response.status === 401 || response.status === 404) { this.stop(); return }
    if (response.status === 409) {
      this.status(false)
      const detail = await response.json().catch(() => ({}))
      const highWatermark = Number(detail.detail?.high_watermark ?? 0)
      this.cursor = Math.max(0, Math.min(this.cursor, highWatermark))
      await this.options.onRefresh()
      return
    }
    if (!response.ok) throw new Error(`Event stream failed (${response.status})`)
    if (!response.body) throw new Error('Event stream body is unavailable')
    this.status(true)
    this.failures = 0
    const reader = this.reader = response.body.getReader()
    let buffer = ''
    while (this.active) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '')
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''
      for (const frame of frames) await this.handleFrame(frame)
    }
  }

  private async handleFrame(frame: string) {
    let id = 0
    const data: string[] = []
    for (const line of frame.split('\n')) {
      if (!line || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      if (colon < 0) continue
      const field = line.slice(0, colon), value = line.slice(colon + 1).trimStart()
      if (field === 'id') id = Number(value)
      if (field === 'data') data.push(value)
    }
    if (!id || id <= this.cursor || !data.length) return
    let event: ProjectEvent
    try { event = JSON.parse(data.join('\n')) as ProjectEvent } catch { return }
    if (event.schema_version !== '1.0' || event.id !== id) return
    this.cursor = id
    if (REFRESH_EVENTS.has(event.type)) await this.options.onRefresh()
  }
}

export function useProjectEvents(projectId: string, enabled: boolean, onRefresh: RefreshCallback, onStatus?: StatusCallback) {
  const refreshRef = useRef(onRefresh)
  const statusRef = useRef(onStatus)
  refreshRef.current = onRefresh
  statusRef.current = onStatus
  const streamRef = useRef<ProjectEventStream | null>(null)
  useEffect(() => {
    if (!enabled || !getToken()) return
    const stream = new ProjectEventStream(projectId, {
      onRefresh: () => refreshRef.current(),
      onStatus: connected => statusRef.current?.(connected),
    })
    streamRef.current = stream
    void stream.start()
    return () => { stream.stop(); streamRef.current = null }
  }, [projectId, enabled])
  return { cursor: streamRef.current?.currentCursor ?? 0, connected: streamRef.current?.isConnected ?? false }
}
