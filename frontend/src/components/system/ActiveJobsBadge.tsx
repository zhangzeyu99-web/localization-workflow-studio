import { allQueueJobs } from '../../domain/jobQueues'
import type { JobQueues } from '../../types'

export function ActiveJobsBadge({ queues, open, onToggle }: { queues: JobQueues; open: boolean; onToggle: () => void }) {
  const count = allQueueJobs(queues).length
  if (!count) return null
  return (
    <button
      type="button"
      className="btn btn-ghost active-jobs-badge"
      data-testid="active-jobs-badge"
      aria-expanded={open}
      onClick={onToggle}
    >
      <span className="active-jobs-dot" />
      后台任务
      <span className="active-jobs-count">{count}</span>
    </button>
  )
}
