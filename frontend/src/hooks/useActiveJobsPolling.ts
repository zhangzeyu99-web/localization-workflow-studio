import { useEffect, useState } from 'react'
import { api } from '../apiClient'
import { usePolling } from './usePolling'
import type { ActiveJob } from '../types'

const ACTIVE_JOBS_POLL_INTERVAL_MS = 9000

// Polls GET /api/system/active-jobs (backend/app/jobs.py's per-project lease
// registry) for the header's workbench-wide active-tasks indicator. This is
// intentionally a separate, independent poll loop from the per-project
// useRunStatusPolling/useProjectSnapshotPolling hooks: the two can disagree
// by up to one poll cycle (~2s in practice) right after a run starts or
// finishes. That is an acceptable display-only lag for a "what else is
// running right now" glance, not a correctness issue for any single run.
export function useActiveJobsPolling(): ActiveJob[] {
  const [jobs, setJobs] = useState<ActiveJob[]>([])

  const fetchJobs = (signal?: AbortSignal) => {
    api<ActiveJob[]>('/api/system/active-jobs', { signal })
      .then((result) => setJobs(Array.isArray(result) ? result : []))
      .catch(() => undefined)
  }

  useEffect(() => {
    fetchJobs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  usePolling(
    (isStale, signal) => { if (!isStale()) fetchJobs(signal) },
    { intervalMs: ACTIVE_JOBS_POLL_INTERVAL_MS, enabled: true, skipWhenHidden: true },
    []
  )

  return jobs
}
