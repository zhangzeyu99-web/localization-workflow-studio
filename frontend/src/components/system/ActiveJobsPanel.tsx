import { useState } from 'react'
import { relativeTimeFromNow } from '../../domain/format'
import { allQueueJobs, queueJobKindLabel, queueJobStatusText, queueLanes } from '../../domain/jobQueues'
import type { JobQueueEntry, JobQueues } from '../../types'

export function ActiveJobsPanel({
  queues,
  onClose,
  onCancel,
}: {
  queues: JobQueues
  onClose: () => void
  onCancel: (job: JobQueueEntry) => Promise<void>
}) {
  const [cancelingJobId, setCancelingJobId] = useState('')
  const lanes = queueLanes(queues)
  const count = allQueueJobs(queues).length

  async function cancel(job: JobQueueEntry) {
    setCancelingJobId(job.job_id)
    try {
      await onCancel(job)
    } finally {
      setCancelingJobId('')
    }
  }

  return (
    <>
      <div className="active-jobs-backdrop" onClick={onClose} />
      <div className="active-jobs-panel" data-testid="active-jobs-panel" role="dialog" aria-label="后台任务">
        <div className="active-jobs-panel-head">
          <strong>后台任务（{count}）</strong>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
        </div>
        <div className="job-queue-lanes">
          {lanes.map((lane) => {
            const jobs = [...(lane.running ? [lane.running] : []), ...lane.queued]
            return (
              <section key={lane.lane} className="job-queue-lane" data-testid={`job-queue-lane-${lane.lane}`}>
                <div className="job-queue-lane-head"><strong>{lane.label}</strong><span>{jobs.length ? `${jobs.length} 个任务` : '空闲'}</span></div>
                {jobs.length ? (
                  <div className="active-jobs-list">
                    {jobs.map((job) => (
                      <div key={job.job_id} className="active-jobs-item" data-testid={`queue-job-${job.job_id}`}>
                        <div className="active-jobs-item-top">
                          <span className="active-jobs-item-project">{job.project_name || '未知项目'}</span>
                          <span className="active-jobs-item-kind">{queueJobKindLabel(job.job_kind)}</span>
                        </div>
                        <div className="active-jobs-item-state">{queueJobStatusText(job).split(' · ')[0]}</div>
                        <div className="active-jobs-item-bottom">
                          <span className="active-jobs-item-time">操作人 {job.operator_name || '未署名用户'} · {relativeTimeFromNow(job.status === 'running' ? job.started_at : job.queued_at)}</span>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm active-jobs-cancel"
                            data-testid={`queue-cancel-${job.job_id}`}
                            disabled={cancelingJobId === job.job_id}
                            onClick={() => void cancel(job)}
                          >
                            {cancelingJobId === job.job_id ? '取消中...' : '取消'}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <div className="active-jobs-empty">当前通道没有任务。</div>}
              </section>
            )
          })}
        </div>
      </div>
    </>
  )
}
