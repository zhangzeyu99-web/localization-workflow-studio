import { relativeTimeFromNow } from '../../domain/format'
import { activeJobKindLabel } from '../../uiText'
import type { ActiveJob } from '../../types'

export function ActiveJobsPanel({ jobs, onClose }: { jobs: ActiveJob[]; onClose: () => void }) {
  return (
    <>
      <div className="active-jobs-backdrop" onClick={onClose} />
      <div className="active-jobs-panel" data-testid="active-jobs-panel" role="dialog" aria-label="活跃任务">
        <div className="active-jobs-panel-head">
          <strong>活跃任务（{jobs.length}）</strong>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
        </div>
        {jobs.length ? (
          <div className="active-jobs-list">
            {jobs.map((job) => (
              <div key={job.job_id || job.lease_name} className="active-jobs-item" data-testid="active-jobs-item">
                <div className="active-jobs-item-top">
                  <span className="active-jobs-item-project">{job.project_name || '未知项目'}</span>
                  <span className="active-jobs-item-kind">{activeJobKindLabel(job.job_kind)}</span>
                </div>
                <div className="active-jobs-item-time">{relativeTimeFromNow(job.started_at)}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="active-jobs-empty">当前没有正在执行的任务。</div>
        )}
      </div>
    </>
  )
}
