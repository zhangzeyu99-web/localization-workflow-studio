import { useCallback, useEffect, useState } from 'react'
import { api } from '../apiClient'
import { usePolling } from './usePolling'
import type { JobQueues } from '../types'

const JOB_QUEUES_POLL_INTERVAL_MS = 2500
const EMPTY_QUEUES: JobQueues = { lanes: [] }

export function useActiveJobsPolling(): { queues: JobQueues; refresh: () => Promise<void> } {
  const [queues, setQueues] = useState<JobQueues>(EMPTY_QUEUES)

  const fetchQueues = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api<JobQueues>('/api/system/job-queues', signal ? { signal } : undefined)
      setQueues(result && Array.isArray(result.lanes) ? result : EMPTY_QUEUES)
    } catch {
      // Keep the last valid snapshot during a transient restart or network drop.
    }
  }, [])

  useEffect(() => {
    void fetchQueues()
  }, [fetchQueues])

  usePolling(
    (isStale, signal) => { if (!isStale()) return fetchQueues(signal) },
    { intervalMs: JOB_QUEUES_POLL_INTERVAL_MS, enabled: true, skipWhenHidden: true },
    [fetchQueues]
  )

  const refresh = useCallback(() => fetchQueues(), [fetchQueues])
  return { queues, refresh }
}
