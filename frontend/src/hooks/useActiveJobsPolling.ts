import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../apiClient'
import { usePolling } from './usePolling'
import type { JobQueues } from '../types'

const JOB_QUEUES_POLL_INTERVAL_MS = 2500
const EMPTY_QUEUES: JobQueues = { lanes: [] }

export type QueueConnection = { loading: boolean; failed: boolean; lastUpdated: number | null }

export function useActiveJobsPolling(): { queues: JobQueues; connection: QueueConnection; refresh: () => Promise<void> } {
  const [queues, setQueues] = useState<JobQueues>(EMPTY_QUEUES)
  const [connection, setConnection] = useState<QueueConnection>({ loading: true, failed: false, lastUpdated: null })
  const requestRef = useRef<{ controller: AbortController; promise: Promise<void> } | null>(null)
  const mounted = useRef(false)

  const fetchQueues = useCallback((force = false): Promise<void> => {
    if (!mounted.current) return Promise.resolve()
    if (requestRef.current && !force) return requestRef.current.promise
    // A post-mutation refresh must not reuse a GET started before that mutation.
    requestRef.current?.controller.abort()
    const controller = new AbortController()
    const current = { controller, promise: Promise.resolve() }
    requestRef.current = current
    setConnection(previous => ({ ...previous, loading: true }))
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    current.promise = (async () => {
      try {
        const result = await api<JobQueues>('/api/system/job-queues', { signal: controller.signal })
        if (!result || !Array.isArray(result.lanes)) throw new Error('Invalid queue response')
        if (!mounted.current || requestRef.current !== current) return
        setQueues(result)
        setConnection({ loading: false, failed: false, lastUpdated: Date.now() })
      } catch {
        if (!mounted.current || requestRef.current !== current) return
        // Retain the last snapshot, but never present a failed read as empty or current.
        setConnection(previous => ({ ...previous, loading: false, failed: true }))
      } finally {
        window.clearTimeout(timeout)
        if (requestRef.current === current) requestRef.current = null
      }
    })()
    return current.promise
  }, [])

  useEffect(() => {
    mounted.current = true
    void fetchQueues()
    const onFocus = () => { void fetchQueues() }
    window.addEventListener('focus', onFocus)
    return () => {
      mounted.current = false
      requestRef.current?.controller.abort()
      requestRef.current = null
      window.removeEventListener('focus', onFocus)
    }
  }, [fetchQueues])

  usePolling(
    () => fetchQueues(),
    { intervalMs: JOB_QUEUES_POLL_INTERVAL_MS, enabled: true, skipWhenHidden: true },
    [fetchQueues]
  )

  const refresh = useCallback(() => fetchQueues(true), [fetchQueues])
  return { queues, connection, refresh }
}
