import type { ActiveJob } from '../../types'

export function ActiveJobsBadge({ jobs, open, onToggle }: { jobs: ActiveJob[]; open: boolean; onToggle: () => void }) {
  if (!jobs.length) return null
  return (
    <button
      type="button"
      className="btn btn-ghost active-jobs-badge"
      data-testid="active-jobs-badge"
      aria-expanded={open}
      onClick={onToggle}
    >
      <span className="active-jobs-dot" />
      活跃任务
      <span className="active-jobs-count">{jobs.length}</span>
    </button>
  )
}
