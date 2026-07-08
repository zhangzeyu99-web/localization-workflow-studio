import type { Dispatch, SetStateAction } from 'react'
import { errorText, humanBackendEvent, humanTaskStatus } from '../appText'
import { newestArtifact } from '../domain/artifacts'
import { projectRunStatusText, projectTranslationPassedStatusText } from '../domain/projectActivity'
import { getTranslationProgress } from '../domain/translationFlow'
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
  setLatestRun: (run: Run | null) => void,
  setStep: Dispatch<SetStateAction<number>>,
  setQualityIssues: (issues: QualityIssue[]) => void,
  setQaArtifact: (artifact: Artifact | null) => void,
  setStatus: (message: string) => void,
  setStatusForProject: (projectId: string, message: string) => void,
  setBusyForProject: (projectId: string, value: boolean) => void,
  loadQualityIssues: (runId: string, projectId?: string) => Promise<QualityIssue[]>,
  refreshCurrent: (projectId?: string) => Promise<Project | null>,
  refreshDeliverables: (projectId?: string) => Promise<void>
) {
  const enabled = Boolean(latestRun && ['queued', 'running'].includes(latestRun.status))

  usePolling(async (isStale) => {
    if (!latestRun) return
    const runProjectId = latestRun.project_id
    try {
      const updated = await api<Run>(`/api/runs/${latestRun.id}`)
      if (isStale()) return
      if (!isCurrentProject(runProjectId)) return
      setLatestRun(updated)
      const latestEvent = updated.events?.[updated.events.length - 1]
      const modelFixStatus = String(updated.metadata?.model_fix_status || '')
      const modelFixResultRunId = String(updated.metadata?.model_fix_result_run_id || '')
      if (modelFixStatus) {
        if (modelFixStatus === 'running' || updated.status === 'running') {
          setStatus('模型修复后台运行中：正在调用 AI 修复问题，完成后会自动重跑 QA。')
        } else if (modelFixResultRunId) {
          const resultRun = await api<Run>(`/api/runs/${modelFixResultRunId}`)
          if (!isCurrentProject(runProjectId)) return
          setLatestRun(resultRun)
          setStep((prev) => (prev < 8 ? 8 : prev))
          if (resultRun.status === 'passed') {
            setQualityIssues([])
            setStatus('模型修复并重跑 QA 已通过，可进入交付。')
          } else {
            const issues = await loadQualityIssues(resultRun.id, runProjectId)
            const hardCount = issues.filter((issue) => issue.severity === 'hard').length
            setStatus(`模型修复已完成，但 QA 仍有${issueCountPhrase(hardCount || issues.length)}问题。请继续修复；急需交付时可带问题摘要交付。`)
          }
        } else if (modelFixStatus === 'failed') {
          setStatus(`模型修复失败：${String(updated.metadata?.model_fix_error || updated.metadata?.error || '请检查 API 配置和 QA 输入。')}`)
        }
      } else if (updated.kind === 'translation' && updated.status === 'passed') {
        setStatus(projectTranslationPassedStatusText(updated, selectedLanguage))
        const resultArtifact = newestArtifact(updated.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        setStep((prev) => (prev < 8 ? 8 : prev))
      } else if (updated.kind === 'translation' && updated.status === 'failed') {
        const progress = getTranslationProgress(updated)
        if (progress && progress.total_rows > 0 && progress.completed_rows >= progress.total_rows) {
          setStatus(`翻译已完成，但 QA 未通过：${projectRunStatusText(updated)}。请进入「QA 校对」步骤查看问题并修复；急需交付时可带问题摘要交付。`)
          const resultArtifact = newestArtifact(updated.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
          if (resultArtifact) setQaArtifact(resultArtifact)
          setStep((prev) => (prev < 8 ? 8 : prev))
        } else {
          setStatus(`翻译中断：${projectRunStatusText(updated)}。可在「AI 翻译」步骤点击继续 AI 翻译。`)
        }
      } else if (latestEvent?.message) {
        setStatus(`后台任务${humanTaskStatus(updated.status)}：${humanBackendEvent(latestEvent.message)}`)
      }
      if (!['queued', 'running'].includes(updated.status)) {
        setBusyForProject(runProjectId, false)
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
      }
    } catch (error) {
      if (!isStale()) setStatusForProject(runProjectId, `后台任务进度刷新失败：${errorText(error)}`)
    }
  }, { intervalMs: 2000, enabled }, [latestRun?.id, latestRun?.status, tab])
}
