import type { JobQueueEntry, JobQueueLane, JobQueueLaneName, JobQueues, Project, Run } from '../types'

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

export function queueJobForTarget(
  queues: JobQueues | null | undefined,
  targetId: string | null | undefined,
  projectId: string,
): JobQueueEntry | null {
  if (!targetId || !projectId) return null
  return allQueueJobs(queues).find((job) => job.project_id === projectId && job.target_id === targetId) || null
}

function isFormalRun(run: Run, projectId: string): boolean {
  return run.project_id === projectId
    && ['translation', 'qa'].includes(run.kind)
    && run.metadata?.task_origin !== 'quick_task'
}

function runReferencesSource(project: Project, run: Run, sourceArtifactId: string | null | undefined): boolean {
  if (!sourceArtifactId) return true
  const metadata = run.metadata || {}
  const directIds = [metadata.input_artifact_id, metadata.parent_input_artifact_id, metadata.multilingual_source_artifact_id]
    .map((value) => String(value || ''))
  if (directIds.includes(sourceArtifactId)) return true
  const sourceRunIds = [metadata.source_run_id, metadata.manual_fix_source_run_id, metadata.model_fix_source_run_id]
    .map((value) => String(value || ''))
  return sourceRunIds.some((runId) => {
    const sourceRun = (project.runs || []).find((candidate) => candidate.id === runId)
    return Boolean(sourceRun && isFormalRun(sourceRun, project.id) && runReferencesSource(project, sourceRun, sourceArtifactId))
  })
}

export function formalWorkflowQueueJob(
  queues: JobQueues | null | undefined,
  project: Project,
  sourceArtifactId: string | null | undefined,
  currentRun?: Run | null,
): JobQueueEntry | null {
  const languageLane = queueLanes(queues).find((lane) => lane.lane === 'language_table')
  const jobs = [...(languageLane?.running ? [languageLane.running] : []), ...(languageLane?.queued || [])]
    .filter((job) => job.project_id === project.id)

  const multilingualJob = sourceArtifactId
    ? jobs.find((job) => job.target_id === sourceArtifactId && ['multilingual_translate', 'multilingual_qa'].includes(job.job_kind))
    : null
  if (multilingualJob) return multilingualJob

  const candidates = [currentRun, ...(project.runs || [])]
    .filter((run): run is Run => Boolean(run && isFormalRun(run, project.id)))
    .filter((run, index, items) => items.findIndex((candidate) => candidate.id === run.id) === index)
    .filter((run) => runReferencesSource(project, run, sourceArtifactId))
  for (const run of candidates) {
    const job = jobs.find((candidate) => candidate.target_id === run.id)
    if (job) return job
  }
  return null
}

export function quickWorkflowQueueJob(
  queues: JobQueues | null | undefined,
  project: Project,
  startedRun?: Run | null,
): JobQueueEntry | null {
  const quickLane = queueLanes(queues).find((lane) => lane.lane === 'quick_announcement')
  const jobs = [...(quickLane?.running ? [quickLane.running] : []), ...(quickLane?.queued || [])]
    .filter((job) => job.project_id === project.id && ['translation', 'qa'].includes(job.job_kind))
  const candidates = [startedRun, ...(project.runs || [])]
    .filter((run): run is Run => Boolean(
      run
      && run.project_id === project.id
      && run.metadata?.task_origin === 'quick_task'
    ))
    .filter((run, index, items) => items.findIndex((candidate) => candidate.id === run.id) === index)
  for (const run of candidates) {
    const job = jobs.find((candidate) => candidate.target_id === run.id)
    if (job) return job
  }
  return null
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
