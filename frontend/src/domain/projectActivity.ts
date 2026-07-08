import { activeAnnouncementTasks } from '../components/announcement/AnnouncementProjectPanel'
import { languageSpec, normalizeLanguageCode } from '../languages'
import { humanTaskStatus } from '../appText'
import { getTranslationProgress } from './translationFlow'
import type { Project, Run } from '../types'

export function visibleAnnouncementTaskCount(project: Project): number {
  return project.announcement_tasks ? activeAnnouncementTasks(project.announcement_tasks).length : (project.stats.announcement_tasks || 0)
}

function isProjectActivityRun(run: Run): boolean {
  return ['translation', 'qa'].includes(run.kind) && ['queued', 'running', 'needs_input', 'failed'].includes(run.status)
}

export function projectActivityRuns(project: Project | null | undefined): Run[] {
  if (!project) return []
  return (project.runs || [])
    .filter(isProjectActivityRun)
    .slice(0, 4)
}

export function latestProjectActivityRun(project: Project | null | undefined): Run | null {
  const latest = (project?.runs || []).find(isProjectActivityRun) || null
  if (!latest) return null
  return latest
}

export function projectActiveTaskCount(project: Project | null | undefined): number {
  if (!project) return 0
  const activeRuns = (project.runs || []).filter((run) => ['translation', 'qa'].includes(run.kind) && ['queued', 'running'].includes(run.status)).length
  const activeAnnouncements = activeAnnouncementTasks(project.announcement_tasks || [])
    .filter((task) => ['queued', 'running'].includes(task.status)).length
  return activeRuns + activeAnnouncements
}

export function projectRunTitle(run: Run): string {
  const lang = languageSpec(normalizeLanguageCode(run.language) || 'en').short
  if (run.kind === 'qa') return `${lang} QA \u6821\u5bf9`
  if (run.kind === 'translation') return `${lang} AI \u7ffb\u8bd1`
  return `${lang} ${run.kind}`
}

export function projectRunStatusText(run: Run): string {
  const progress = getTranslationProgress(run)
  const quality = (run.metadata?.quality_summary || run.metadata?.quality || {}) as { hard_errors?: number; issues?: number; passed?: boolean }
  if (progress?.total_rows) {
    const percent = typeof progress.percent === 'number' ? `${Math.round(progress.percent)}%` : `${progress.completed_rows || 0}/${progress.total_rows} \u884c`
    if (['queued', 'running'].includes(run.status)) return `\u8fdb\u884c\u4e2d \u00b7 ${percent}`
    if (run.status === 'failed' && progress.completed_rows >= progress.total_rows) {
      const hard = Number(quality.hard_errors || quality.issues || 0)
      return hard ? `\u7ffb\u8bd1\u5df2\u5b8c\u6210\uff0cQA \u672a\u901a\u8fc7 \u00b7 ${hard} \u4e2a\u95ee\u9898` : '\u7ffb\u8bd1\u5df2\u5b8c\u6210\uff0c\u7b49\u5f85\u5904\u7406 QA \u7ed3\u679c'
    }
    if (run.status === 'failed') return `\u4e2d\u65ad \u00b7 ${progress.completed_rows || 0}/${progress.total_rows} \u884c`
  }
  if (run.status === 'queued') return '\u6392\u961f\u4e2d'
  if (run.status === 'running') return '\u8fdb\u884c\u4e2d'
  if (run.status === 'needs_input') return '\u7b49\u5f85\u8865\u5145\u8f93\u5165'
  if (run.status === 'failed') return '\u5931\u8d25\u5f85\u5904\u7406'
  return humanTaskStatus(run.status)
}

export function projectTranslationPassedStatusText(run: Run, fallbackLanguage: string): string {
  const lang = languageSpec(normalizeLanguageCode(run.language) || normalizeLanguageCode(fallbackLanguage) || 'en').short
  return `${lang} \u7ffb\u8bd1\u548c QA \u5df2\u901a\u8fc7\uff0c\u6700\u7ec8\u4ea7\u7269\u5df2\u5f52\u6863\u3002`
}
