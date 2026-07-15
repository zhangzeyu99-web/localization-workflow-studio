import type { JobQueueEntry, JobQueueLane, JobQueueLaneName, JobQueues } from '../types'

const LANE_ORDER: { lane: JobQueueLaneName; label: string }[] = [
  { lane: 'language_table', label: '语言表' },
  { lane: 'quick_announcement', label: '快速/公告' },
]

export function queueLanes(queues: JobQueues | null | undefined): JobQueueLane[] {
  const byLane = new Map((queues?.lanes || []).map((lane) => [lane.lane, lane]))
  return LANE_ORDER.map((definition) => {
    const lane = byLane.get(definition.lane)
    return {
      lane: definition.lane,
      label: lane?.label || definition.label,
      running: lane?.running || null,
      queued: Array.isArray(lane?.queued) ? lane.queued : [],
    }
  })
}

export function allQueueJobs(queues: JobQueues | null | undefined): JobQueueEntry[] {
  return queueLanes(queues).flatMap((lane) => [
    ...(lane.running ? [lane.running] : []),
    ...lane.queued,
  ])
}

export function projectQueueJobCount(queues: JobQueues | null | undefined, projectId: string): number {
  return allQueueJobs(queues).filter((job) => job.project_id === projectId).length
}

export function queueJobForTarget(queues: JobQueues | null | undefined, targetId?: string | null): JobQueueEntry | null {
  if (!targetId) return null
  return allQueueJobs(queues).find((job) => job.target_id === targetId) || null
}

export function queueJobKindLabel(jobKind?: string): string {
  const labels: Record<string, string> = {
    translation: '翻译',
    qa: 'QA 校对',
    model_fix: 'QA 修复',
    announcement: '公告翻译',
    multilingual_translate: '多语言翻译',
    multilingual_qa: '多语言 QA',
  }
  return labels[String(jobKind || '')] || 'AI 任务'
}

export function queueJobStatusText(job: JobQueueEntry | null | undefined): string {
  if (!job) return ''
  const operator = job.operator_name || '未署名用户'
  if (job.status === 'running') return `运行中 · 操作人 ${operator}`
  const position = Math.max(1, Number(job.position) || 1)
  const ahead = Math.max(0, Number(job.ahead) || 0)
  return `排队第 ${position} 位、前方 ${ahead} 个 · 操作人 ${operator}`
}
