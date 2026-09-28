import { relativeTimeFromNow } from '../../domain/format'
import { allQueueJobs, queueJobKindLabel, queueJobStatusText, queueLanes } from '../../domain/jobQueues'
import type { JobQueueEntry, JobQueues } from '../../types'
import type { QueueConnection } from '../../hooks/useActiveJobsPolling'

export function ActiveJobsPanel({
  queues,
  connection,
  requestedJobIds,
  cancelingJobIds,
  cancelErrors,
  onRefresh,
  onClose,
  onCancel,
}: {
  queues: JobQueues
  connection: QueueConnection
  requestedJobIds: ReadonlySet<string>
  cancelingJobIds: ReadonlySet<string>
  cancelErrors: Readonly<Record<string, string>>
  onRefresh: () => Promise<void>
  onClose: () => void
  onCancel: (job: JobQueueEntry) => Promise<boolean | void>
}) {
  const lanes = queueLanes(queues)
  const count = allQueueJobs(queues).length

  function jobState(job: JobQueueEntry) {
    const cancelRequested = job.cancel_requested || requestedJobIds.has(job.job_id)
    if (connection.failed) {
      if (job.archive_committed) return '归档已提交；完成状态待确认'
      if (cancelRequested) return '取消请求已接受；停止状态待确认'
      return `上次读取：${queueJobStatusText(job).split(' · ')[0]}`
    }
    return cancelRequested && !job.archive_committed ? '正在停止，等待当前步骤结束' : queueJobStatusText(job).split(' · ')[0]
  }

  return (
    <>
      <div className="active-jobs-backdrop" onClick={onClose} />
      <div className="active-jobs-panel" data-testid="active-jobs-panel" role="dialog" aria-label="后台任务">
        <div className="active-jobs-panel-head">
          <strong>后台任务{connection.lastUpdated !== null ? `（${connection.failed ? '上次 ' : ''}${count}）` : ''}</strong>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
        </div>
        {connection.failed ? (
          <div className="queue-freshness" data-testid="queue-freshness" role="status">
            <div><strong>{connection.lastUpdated === null ? '暂时无法读取任务' : '状态未确认'}</strong>
              <p>{connection.lastUpdated === null ? '连接恢复后自动刷新。' : '以下为上次结果。'}</p>
            </div>
            <button type="button" className="btn btn-secondary btn-sm" disabled={connection.loading} onClick={() => void onRefresh()}>{connection.loading ? '连接中…' : '重新连接'}</button>
          </div>
        ) : connection.lastUpdated === null ? <p role="status">正在读取后台任务…</p> : null}
        {connection.lastUpdated !== null ? <div className="job-queue-lanes">
          {lanes.map((lane) => {
            const jobs = [...(lane.running ? [lane.running] : []), ...lane.queued]
            return (
              <section key={lane.lane} className="job-queue-lane" data-testid={`job-queue-lane-${lane.lane}`}>
                <div className="job-queue-lane-head"><strong>{lane.label}</strong><span>{jobs.length ? `${jobs.length} 个任务` : connection.failed ? '状态待更新' : '空闲'}</span></div>
                {jobs.length ? (
                  <div className="active-jobs-list">
                    {jobs.map((job) => (
                      <div key={job.job_id} className="active-jobs-item" data-testid={`queue-job-${job.job_id}`}>
                        <div className="active-jobs-item-top">
                          <span className="active-jobs-item-project">{job.project_name || '未知项目'}</span>
                          <span className="active-jobs-item-kind">{queueJobKindLabel(job.job_kind)}</span>
                        </div>
                        <div className={`active-jobs-item-state${connection.failed ? ' is-stale' : ''}`}>{jobState(job)}</div>
                        <div className="active-jobs-item-bottom">
                          <span className="active-jobs-item-time">{job.operator_name || '未署名用户'} · {relativeTimeFromNow(job.status === 'running' ? job.started_at : job.queued_at)}</span>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm active-jobs-cancel"
                            data-testid={`queue-cancel-${job.job_id}`}
                            disabled={cancelingJobIds.has(job.job_id) || requestedJobIds.has(job.job_id) || job.cancel_requested || job.can_cancel === false || job.archive_committed}
                            title={job.archive_committed ? '归档已经提交，不能再取消；请等待任务完成。' : undefined}
                            onClick={() => void onCancel(job)}
                          >
                            {job.archive_committed ? '已提交' : job.cancel_requested || requestedJobIds.has(job.job_id) ? '等待停止' : cancelingJobIds.has(job.job_id) ? '取消中...' : cancelErrors[job.job_id] ? '重试取消' : '取消'}
                          </button>
                        </div>
                        {cancelErrors[job.job_id] ? <p className="queue-cancel-error" role="alert">{cancelErrors[job.job_id]}</p> : null}
                      </div>
                    ))}
                  </div>
                ) : <div className="active-jobs-empty">{connection.failed ? '上次读取时没有任务。' : '当前通道没有任务。'}</div>}
              </section>
            )
          })}
        </div> : null}
      </div>
    </>
  )
}
