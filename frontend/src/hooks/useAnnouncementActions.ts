import type { Dispatch, SetStateAction } from 'react'
import { api } from '../apiClient'
import { announcementActionLabel, announcementActionSummary, errorText } from '../appText'
import { artifactPickerLabel, uniqueArtifactsByContent } from '../domain/artifacts'
import type { ConfirmDialogOptions } from '../components/modals/ConfirmModal'
import type { LanguageCode } from '../languages'
import type {
  AnnouncementLookupOptions,
  AnnouncementLookupResult,
  AnnouncementTask,
  AnnouncementTaskResult,
  AppView,
  Artifact,
  Project,
  Run
} from '../types'

export interface UseAnnouncementActionsParams {
  current: Project | undefined
  currentLang: { short: string }
  currentIdRef: { current: string }
  selectedLanguage: LanguageCode
  busy: boolean
  announcementFocusTaskId: string
  announcementCancelHoldTimer: { current: number | null }
  longPressTriggeredAnnouncementTaskId: { current: string }
  isCurrentProject: (projectId?: string | null) => boolean
  setAnnouncementCancelHoldTaskId: (id: string) => void
  setAnnouncementCancelTarget: (task: AnnouncementTask | null) => void
  setAnnouncementFocusTaskId: (id: string) => void
  setAnnouncementLookupResult: (result: AnnouncementLookupResult | null) => void
  setView: (view: AppView) => void
  setBusy: (value: boolean) => void
  setStatus: (message: string) => void
  setStatusForProject: (projectId: string, message: string) => void
  setBusyForProject: (projectId: string, value: boolean) => void
  setLatestRun: (run: Run | null) => void
  setAssetArtifacts: Dispatch<SetStateAction<Artifact[]>>
  refreshCurrent: (projectId?: string) => Promise<Project | null>
  upload: (file: File, kind: string, purpose?: string) => Promise<Artifact | null>
  alertDialog: (message: string, options?: Omit<ConfirmDialogOptions, 'cancelLabel'>) => Promise<boolean>
}

// Announcement task handlers moved verbatim out of main.tsx's App component.
export function useAnnouncementActions(params: UseAnnouncementActionsParams) {
  const {
    current,
    currentLang,
    currentIdRef,
    selectedLanguage,
    busy,
    announcementFocusTaskId,
    announcementCancelHoldTimer,
    longPressTriggeredAnnouncementTaskId,
    isCurrentProject,
    setAnnouncementCancelHoldTaskId,
    setAnnouncementCancelTarget,
    setAnnouncementFocusTaskId,
    setAnnouncementLookupResult,
    setView,
    setBusy,
    setStatus,
    setStatusForProject,
    setBusyForProject,
    setLatestRun,
    setAssetArtifacts,
    refreshCurrent,
    upload,
    alertDialog
  } = params

  function cancelAnnouncementCancelHold() {
    if (announcementCancelHoldTimer.current !== null) {
      window.clearTimeout(announcementCancelHoldTimer.current)
      announcementCancelHoldTimer.current = null
    }
    setAnnouncementCancelHoldTaskId('')
  }

  function beginAnnouncementCancelHold(task: AnnouncementTask) {
    if (busy) return
    cancelAnnouncementCancelHold()
    setAnnouncementCancelHoldTaskId(task.id)
    announcementCancelHoldTimer.current = window.setTimeout(() => {
      longPressTriggeredAnnouncementTaskId.current = task.id
      announcementCancelHoldTimer.current = null
      setAnnouncementCancelHoldTaskId('')
      setAnnouncementCancelTarget(task)
    }, 850)
  }

  function openAnnouncementTask(task?: AnnouncementTask) {
    if (task && longPressTriggeredAnnouncementTaskId.current === task.id) {
      longPressTriggeredAnnouncementTaskId.current = ''
      return
    }
    setAnnouncementFocusTaskId(task?.id || '')
    setView('announcement')
  }

  async function cancelAnnouncementTask(task: AnnouncementTask) {
    const projectId = task.project_id || currentIdRef.current
    setBusyForProject(projectId, true)
    setStatus(`正在取消公告任务“${task.title || task.id}”...`)
    try {
      await api(`/api/announcement-tasks/${task.id}/cancel`, { method: 'POST' })
      await refreshCurrent()
      if (announcementFocusTaskId === task.id) setAnnouncementFocusTaskId('')
      longPressTriggeredAnnouncementTaskId.current = ''
      setAnnouncementCancelTarget(null)
      setStatus(`公告任务“${task.title || task.id}”已取消`)
    } catch (error) {
      setStatus(`取消公告任务失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function uploadAnnouncementResponse(file: File) {
    const artifact = await upload(file, 'asset')
    if (artifact) {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `外部 AI 结果已存在，已复用：${artifactPickerLabel(artifact)}` : `外部 AI 结果已上传：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }

  async function uploadAnnouncementConstraint(file: File) {
    const artifact = await upload(file, 'language_table')
    if (artifact) {
      setStatus(artifact.duplicate ? `约束文件已存在，已复用：${artifactPickerLabel(artifact)}` : `公告约束文件已归档：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }

  async function uploadAnnouncementTermsFile(file: File) {
    const artifact = await upload(file, 'announcement_terms_workbook')
    if (artifact) {
      setStatus(artifact.duplicate ? `公告术语表已存在，已复用：${artifactPickerLabel(artifact)}` : `公告术语表已上传：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }

  async function createAnnouncementTask(payload: Record<string, unknown>) {
    if (!current) return null
    const projectId = current.id
    setBusy(true)
    setStatusForProject(projectId, '正在创建公告任务...')
    try {
      const task = await api<AnnouncementTask>(`/api/projects/${projectId}/announcement-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!isCurrentProject(projectId)) return null
      await refreshCurrent()
      setStatusForProject(projectId, `公告任务已创建：${task.title || task.id}`)
      return task
    } catch (error) {
      setStatusForProject(projectId, `公告任务创建失败：${errorText(error)}`)
      return null
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function runAnnouncementTaskAction(taskId: string, endpoint: string, payload: Record<string, unknown> = {}) {
    if (!current) return null
    const projectId = current.id
    setBusy(true)
    setStatusForProject(projectId, `正在执行公告任务：${announcementActionLabel(endpoint)}...`)
    try {
      const result = await api<AnnouncementTaskResult>(`/api/announcement-tasks/${taskId}/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!isCurrentProject(projectId)) return null
      if (result.run) setLatestRun({ ...result.run, artifacts: result.artifacts || [] })
      await refreshCurrent()
      const summary = announcementActionSummary(endpoint, result.summary)
      const taskStatus = String(result.task?.status || '')
      if (endpoint.startsWith('translate/') && ['queued', 'running'].includes(taskStatus)) {
        setStatusForProject(projectId, summary || `公告后台翻译已启动：${announcementActionLabel(endpoint)}`)
      } else {
        setStatusForProject(projectId, summary || `公告步骤已完成：${announcementActionLabel(endpoint)}`)
      }
      return result
    } catch (error) {
      const message = errorText(error)
      setStatusForProject(projectId, `公告任务失败：${message}`)
      if (/约束文件|语言表|表头|可反查词条/.test(message)) {
        void alertDialog(`公告约束文件没有被正确读取：${message}`, { title: '约束文件读取失败', tone: 'warn' })
      }
      return null
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function runAnnouncementLookup(text: string, materialArtifactIds: string[], options: AnnouncementLookupOptions) {
    if (!current) return
    if (!text.trim() && !materialArtifactIds.length) {
      setStatus('请先上传/选择公告素材，或直接输入公告长文本。')
      return
    }
    setBusy(true)
    setStatus(`正在生成 ${currentLang.short} 公告检索包...`)
    try {
      const result = await api<AnnouncementLookupResult>(`/api/projects/${current.id}/announcement-lookup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          material_artifact_ids: materialArtifactIds,
          language: selectedLanguage,
          include_glossary: options.includeGlossary,
          include_translation_archive: options.includeTranslationArchive
        })
      })
      setAnnouncementLookupResult(result)
      setLatestRun({ ...result.run, artifacts: result.artifacts })
      await refreshCurrent()
      setStatus(`公告检索包完成：命中术语 ${result.summary.matched_terms} 条，译文参考 ${result.summary.matched_translations} 条。`)
    } catch (error) {
      setStatus(`公告检索包生成失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  return {
    cancelAnnouncementCancelHold,
    beginAnnouncementCancelHold,
    openAnnouncementTask,
    cancelAnnouncementTask,
    uploadAnnouncementResponse,
    uploadAnnouncementConstraint,
    uploadAnnouncementTermsFile,
    createAnnouncementTask,
    runAnnouncementTaskAction,
    runAnnouncementLookup
  }
}
