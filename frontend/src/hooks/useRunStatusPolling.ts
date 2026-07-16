import { useEffect, useRef } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { errorText, humanBackendEvent, humanTaskStatus } from '../appText'
import { newestArtifact } from '../domain/artifacts'
import { projectRunStatusText, projectTranslationPassedStatusText } from '../domain/projectActivity'
import { getTranslationProgress, shouldAutoAdvanceTranslationRun } from '../domain/translationFlow'
import type { LanguageCode } from '../languages'
import type { Artifact, Project, ProjectTab, QualityIssue, Run } from '../types'
import { issueCountPhrase } from '../uiText'
import { usePolling } from './usePolling'
import { api } from '../apiClient'

// Every 2s while the latest run is queued/running, polls run details and
// applies status text, step advancement and QA-related state transitions
// (including the model-fix background flow). Moved verbatim from main.tsx's
// App component; `isStale()` replaces the previous local `cancelled` flag.
export function useRunStatusPolling(
  latestRun: Run | null,
  tab: ProjectTab,
  selectedLanguage: LanguageCode,
  isCurrentProject: (projectId?: string | null) => boolean,
  isCurrentRunScope: (run: Run) => boolean,
  setLatestRun: (run: Run | null) => void,
  setStep: Dispatch<SetStateAction<number>>,
  setQualityIssues: (issues: QualityIssue[]) => void,
  setQaArtifact: (artifact: Artifact | null) => void,
  setStatus: (message: string) => void,
  setStatusForProject: (projectId: string, message: string) => void,
  setBusyForProject: (projectId: string, value: boolean) => void,
  loadQualityIssues: (runId: string, projectId?: string, accept?: () => boolean) => Promise<QualityIssue[]>,
  refreshCurrent: (projectId?: string) => Promise<Project | null>,
  refreshDeliverables: (projectId?: string) => Promise<void>,
  refreshProjects?: () => Promise<void>
) {
  const enabled = Boolean(latestRun && ['queued', 'running'].includes(latestRun.status))
  const consecutiveFailuresRef = useRef(0)

  useEffect(() => {
    consecutiveFailuresRef.current = 0
  }, [latestRun?.id])

  usePolling(async (isStale, signal) => {
    if (!latestRun) return
    const runProjectId = latestRun.project_id
    try {
      const updated = await api<Run>(`/api/runs/${latestRun.id}`, { signal })
      if (isStale()) return
      consecutiveFailuresRef.current = 0
      if (!isCurrentProject(runProjectId) || !isCurrentRunScope(updated)) return
      const latestEvent = updated.events?.[updated.events.length - 1]
      const modelFixStatus = String(updated.metadata?.model_fix_status || '')
      const modelFixResultRunId = String(updated.metadata?.model_fix_result_run_id || '')
      // Do not publish the model-fix source run's intermediate terminal state
      // before resolving its result run. Changing running -> failed/passed
      // tears down this poll effect and would mark the in-flight result read
      // stale even though it belongs to the same task.
      if (!modelFixResultRunId) setLatestRun(updated)
      if (modelFixStatus) {
        if (modelFixStatus === 'running' || updated.status === 'running') {
          setStatus('模型修复后台运行中：正在调用 AI 修复问题，完成后会自动重跑 QA。')
        } else if (modelFixResultRunId) {
          const resultRun = await api<Run>(`/api/runs/${modelFixResultRunId}`, { signal })
          if (isStale()) return
          if (!isCurrentProject(runProjectId) || !isCurrentRunScope(resultRun)) return
          setLatestRun(resultRun)
          setStep((prev) => (prev < 8 ? 8 : prev))
          if (resultRun.status === 'passed') {
            setQualityIssues([])
            setStatus('模型修复并重跑 QA 已通过，可进入交付。')
          } else {
            const issues = await loadQualityIssues(resultRun.id, runProjectId, () => isCurrentRunScope(resultRun))
            if (isStale() || !isCurrentRunScope(resultRun)) return
            const hardCount = issues.filter((issue) => issue.severity === 'hard').length
            setStatus(`模型修复已完成，但 QA 仍有${issueCountPhrase(hardCount || issues.length)}问题。请继续修复；时间受限时可生成带问题摘要的交付。`)
          }
        } else if (modelFixStatus === 'failed') {
          setStatus(`模型修复失败：${String(updated.metadata?.model_fix_error || updated.metadata?.error || '请检查 API 配置和 QA 输入。')}`)
        }
      } else if (updated.kind === 'translation' && updated.status === 'passed') {
        if (shouldAutoAdvanceTranslationRun(updated)) {
          setStatus(projectTranslationPassedStatusText(updated, selectedLanguage))
          const resultArtifact = newestArtifact(updated.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
          if (resultArtifact) setQaArtifact(resultArtifact)
          setStep((prev) => (prev < 8 ? 8 : prev))
        } else {
          setStatus(`${updated.language.toUpperCase()} 翻译和 QA 已完成；多语言队列会继续处理剩余语言。`)
        }
      } else if (updated.kind === 'translation' && updated.status === 'failed') {
        const progress = getTranslationProgress(updated)
        if (progress && progress.total_rows > 0 && progress.completed_rows >= progress.total_rows) {
          if (shouldAutoAdvanceTranslationRun(updated)) {
            setStatus(`翻译已完成，但 QA 未通过：${projectRunStatusText(updated)}。请进入「QA 校对」步骤查看问题并修复；时间受限时可生成带问题摘要的交付。`)
            const resultArtifact = newestArtifact(updated.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
            if (resultArtifact) setQaArtifact(resultArtifact)
            setStep((prev) => (prev < 8 ? 8 : prev))
          } else {
            setStatus(`${updated.language.toUpperCase()} 已完成翻译但 QA 未通过；多语言队列会继续处理剩余语言，完成后可在总览统一修复。`)
          }
        } else {
          setStatus(`翻译中断：${projectRunStatusText(updated)}。可在「AI 翻译」步骤点击继续 AI 翻译。`)
        }
      } else if (updated.kind === 'qa' && updated.status === 'passed') {
        const resultArtifact = newestArtifact(updated.artifacts || [], ['qa_final_workbook'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        setQualityIssues([])
        setStatus('QA 通过，可进入交付。')
      } else if (updated.kind === 'qa' && updated.status === 'failed') {
        const issues = await loadQualityIssues(updated.id, runProjectId, () => isCurrentRunScope(updated))
        if (isStale() || !isCurrentRunScope(updated)) return
        const hardCount = issues.filter((issue) => issue.severity === 'hard').length
        setStatus(`QA 未通过：发现${issueCountPhrase(hardCount || issues.length)}问题。建议先修复并重跑；时间受限时可生成带问题摘要的交付。`)
      } else if (updated.kind === 'qa' && updated.status === 'canceled') {
        setStatus('QA 已取消，未写入任何结果；可重新运行 QA。')
      } else if (latestEvent?.message) {
        setStatus(`后台任务${humanTaskStatus(updated.status)}：${humanBackendEvent(latestEvent.message)}`)
      }
      if (!['queued', 'running'].includes(updated.status)) {
        setBusyForProject(runProjectId, false)
        await refreshCurrent()
        if (isStale() || !isCurrentRunScope(updated)) return
        if (tab === 'delivery') await refreshDeliverables()
        // Refresh the project list immediately so sidebar badges reflect the
        // terminal state now instead of after the next 10s list poll.
        if (refreshProjects) refreshProjects().catch(() => undefined)
      }
    } catch (error) {
      if (isStale()) return
      if (!isCurrentRunScope(latestRun)) return
      consecutiveFailuresRef.current += 1
      if (consecutiveFailuresRef.current >= 5) {
        // Escape hatch: if progress polling keeps failing (backend restart,
        // network drop), release the global busy lock instead of freezing the
        // whole UI forever. The backend task itself keeps running.
        setBusyForProject(runProjectId, false)
        setStatusForProject(runProjectId, `后台任务进度刷新连续失败（${errorText(error)}）。任务可能仍在后台运行，界面已解锁；请稍后在「活跃任务」里查看，或刷新页面。`)
      } else {
        setStatusForProject(runProjectId, `后台任务进度刷新失败：${errorText(error)}`)
      }
    }
  }, { intervalMs: 2000, enabled, skipWhenHidden: true }, [latestRun?.id, latestRun?.status, tab, isCurrentRunScope])
}
