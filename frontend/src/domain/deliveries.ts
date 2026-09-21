import type { CurrentDeliveryTask, DeliverableTask, DeliveryHistory, DeliveryTaskKind, DeliveryVersion, Project, Run } from '../types'

export const deliveryTaskKindLabel: Record<DeliveryTaskKind, string> = {
  translation: '正式翻译', quick: '快速任务', merged: '多语言合并', announcement: '公告任务',
}

export function deliveryGroupKey(task: Pick<CurrentDeliveryTask, 'task_id' | 'task_kind' | 'language'>): string {
  return JSON.stringify([task.task_kind, task.task_id, task.language])
}

export function deliveryHasQaIssues(task: Pick<CurrentDeliveryTask, 'status' | 'qa_status' | 'qa_hard_errors'>): boolean {
  return task.status === 'failed' || task.qa_status === 'failed' || Number(task.qa_hard_errors || 0) > 0
}

export function deliveryQaLabel(status: string, hard: number | null): string {
  if (status === 'mixed') return '部分交付'
  if (status === 'failed' || Number(hard || 0) > 0) return 'QA 未通过'
  if (status === 'passed' && hard === 0) return 'QA 已通过'
  return 'QA 尚无完整结论'
}

export function deliveryHistorySections(history: DeliveryHistory) {
  const current = history.current_tasks.filter((task) => Boolean(task.task_id))
  const versions = [...history.versions].sort((a, b) => b.generated_at.localeCompare(a.generated_at))
  const currentVersionIds = new Set(current.map((task) => task.current_version_id).filter(Boolean))
  const past = versions.filter((version) => !version.task_id || !currentVersionIds.has(version.version_id))
  const previousAvailable = new Set<string>()
  for (const task of current.filter(deliveryHasQaIssues)) {
    const previous = past.find((version) => version.task_id
      && deliveryGroupKey({ ...version, task_id: version.task_id }) === deliveryGroupKey(task)
      && version.history_complete && version.available !== false && version.qa_snapshot.status === 'passed'
      && version.qa_snapshot.hard_errors === 0 && version.files.some((file) => file.download_url))
    if (previous) previousAvailable.add(previous.version_id)
  }
  return { current, past, previousAvailable }
}

export function currentDeliveryVersion(task: CurrentDeliveryTask, versions: DeliveryVersion[]): DeliveryVersion | undefined {
  return versions.find((version) => version.version_id === task.current_version_id
    && version.task_id === task.task_id && version.task_kind === task.task_kind && version.language === task.language)
}

export function currentDeliveryMissingQaSummary(task: CurrentDeliveryTask, summary: DeliverableTask | undefined): boolean {
  return ['translation', 'quick'].includes(task.task_kind) && task.can_generate && deliveryHasQaIssues(task)
    && !['canceled', 'abandoned', 'closed'].includes(task.task_state || task.status)
    && summary?.run_id === task.run_id && summary.translation_task_id === task.task_id && summary.language === task.language
    && Boolean(summary.files.final?.filename.toLowerCase().endsWith('.xlsx') && summary.files.final.download_url)
    && !summary.files.qa_summary?.download_url
}

export function deliveryProcessingRun(project: Project, task: CurrentDeliveryTask): Run | undefined {
  const runs = (project.runs || []).filter((run) => run.project_id === project.id)
  return runs.find((run) => run.id === task.run_id)
}
