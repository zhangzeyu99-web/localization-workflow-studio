import { allQueueJobs } from '../../domain/jobQueues'
import type { JobQueues } from '../../types'
import type { QueueConnection } from '../../hooks/useActiveJobsPolling'

export function ActiveJobsBadge({ queues, connection, open, onToggle }: { queues: JobQueues; connection: QueueConnection; open: boolean; onToggle: () => void }) {
  const count = allQueueJobs(queues).length
  if (!count && !connection.failed && connection.lastUpdated !== null && !open) return null
  return (
    <button
      type="button"
      className={`btn btn-ghost active-jobs-badge${connection.failed ? ' is-stale' : ''}`}
      data-testid="active-jobs-badge"
      aria-label={connection.failed ? '后台任务：状态待更新' : undefined}
      aria-expanded={open}
      onClick={onToggle}
    >
      {connection.failed ? '任务状态待更新' : connection.lastUpdated === null ? '正在读取任务' : `后台任务（${count}）`}
    </button>
  )
}
