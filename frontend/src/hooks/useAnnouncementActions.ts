import type { Dispatch, SetStateAction } from 'react'
import { api } from '../apiClient'
import { announcementActionLabel, announcementActionSummary, errorText } from '../appText'
import { artifactPickerLabel, uniqueArtifactsByContent } from '../domain/artifacts'
import { unfinishedAnnouncementConflictTaskId } from '../domain/announcementTaskLifecycle'
import type { AnnouncementSessionScope } from '../domain/announcementTaskLifecycle'
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
  setAnnouncementLookupResult: (result: AnnouncementLookupResult | null) => void
  setView: (view: AppView) => void
  setBusy: (value: boolean) => void
  setStatus: (message: string) => void
  setStatusForProject: (projectId: string, message: string) => void
  setBusyForProject: (projectId: string, value: boolean) => void
  setLatestRun: (run: Run | null) => void
  setAssetArtifacts: Dispatch<SetStateAction<Artifact[]>>
  refreshCurrent: (projectId?: string) => Promise<Project | null>
  upload: (file: File, kind: string, purpose?: string, accept?: () => boolean) => Promise<Artifact | null>
  alertDialog: (message: string, options?: Omit<ConfirmDialogOptions, 'cancelLabel'>) => Promise<boolean>
  beginAnnouncementSession: (taskId: string) => void
  captureAnnouncementSession: (taskId?: string) => AnnouncementSessionScope
  isCurrentAnnouncementSession: (scope: AnnouncementSessionScope) => boolean
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
    alertDialog,
    beginAnnouncementSession,
    captureAnnouncementSession,
    isCurrentAnnouncementSession
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

  function openAnnouncementTask(task?: AnnouncementTask, message = '公告任务已就绪。') {
    if (task && longPressTriggeredAnnouncementTaskId.current === task.id) {
      longPressTriggeredAnnouncementTaskId.current = ''
      return
    }
    beginAnnouncementSession(task?.id || '')
    setBusy(false)
    setStatus(message)
    setView('announcement')
  }

  async function cancelAnnouncementTask(task: AnnouncementTask) {
    const projectId = task.project_id || currentIdRef.current
    beginAnnouncementSession(task.id)
    const session = captureAnnouncementSession(task.id)
    setBusyForProject(projectId, true)
    setStatus(`正在取消公告任务“${task.title || task.id}”...`)
    try {
      await api(`/api/announcement-tasks/${task.id}/cancel`, { method: 'POST' })
      if (!isCurrentAnnouncementSession(session)) return
      await refreshCurrent(projectId)
      if (!isCurrentAnnouncementSession(session)) return
      longPressTriggeredAnnouncementTaskId.current = ''
      setAnnouncementCancelTarget(null)
      setStatus(`公告任务“${task.title || task.id}”已取消`)
      setBusyForProject(projectId, false)
      beginAnnouncementSession('')
    } catch (error) {
      if (isCurrentAnnouncementSession(session)) setStatus(`取消公告任务失败：${errorText(error)}`)
    } finally {
      if (isCurrentAnnouncementSession(session)) setBusyForProject(projectId, false)
    }
  }

  async function uploadAnnouncementFile(
    file: File,
    kind: string,
    onAccepted: (artifact: Artifact) => void,
  ): Promise<Artifact | null> {
    const session = captureAnnouncementSession()
    const accept = () => isCurrentAnnouncementSession(session)
    const artifact = await upload(file, kind, '', accept)
    if (!accept()) return null
    if (artifact) onAccepted(artifact)
    return artifact
  }

  async function uploadAnnouncementAsset(file: File) {
    return uploadAnnouncementFile(file, 'asset', (artifact) => {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `参考素材已存在，已复用：${artifactPickerLabel(artifact)}` : `参考素材已归档：${artifactPickerLabel(artifact)}`)
    })
  }

  async function uploadAnnouncementResponse(file: File) {
    return uploadAnnouncementFile(file, 'asset', (artifact) => {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `外部 AI 结果已存在，已复用：${artifactPickerLabel(artifact)}` : `外部 AI 结果已上传：${artifactPickerLabel(artifact)}`)
    })
  }

  async function uploadAnnouncementConstraint(file: File) {
    return uploadAnnouncementFile(file, 'language_table', (artifact) => {
      setStatus(artifact.duplicate ? `约束文件已存在，已复用：${artifactPickerLabel(artifact)}` : `公告约束文件已归档：${artifactPickerLabel(artifact)}`)
    })
  }

  async function uploadAnnouncementTermsFile(file: File) {
    return uploadAnnouncementFile(file, 'announcement_terms_workbook', (artifact) => {
      setStatus(artifact.duplicate ? `公告术语表已存在，已复用：${artifactPickerLabel(artifact)}` : `公告术语表已上传：${artifactPickerLabel(artifact)}`)
    })
  }

  async function createAnnouncementTask(payload: Record<string, unknown>) {
    if (!current) return null
    const projectId = current.id
    const session = captureAnnouncementSession()
    setBusy(true)
    setStatusForProject(projectId, '正在创建公告任务...')
    try {
      const task = await api<AnnouncementTask>(`/api/projects/${projectId}/announcement-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      await refreshCurrent()
      if (!isCurrentAnnouncementSession(session)) return null
      openAnnouncementTask(task, `公告任务已创建：${task.title || task.id}`)
      return task
    } catch (error) {
      const conflictTaskId = unfinishedAnnouncementConflictTaskId(error)
      if (conflictTaskId) {
        const loaded = await refreshCurrent(projectId).catch(() => null)
        if (!isCurrentAnnouncementSession(session)) return null
        const existingTask = (loaded?.announcement_tasks || []).find((task) => task.id === conflictTaskId) || null
        if (existingTask) {
          openAnnouncementTask(existingTask, `已打开现有公告任务：${existingTask.title || existingTask.id}`)
          return existingTask
        }
      }
      if (isCurrentAnnouncementSession(session)) setStatusForProject(projectId, `公告任务创建失败：${errorText(error)}`)
      return null
    } finally {
      if (isCurrentAnnouncementSession(session)) setBusyForProject(projectId, false)
    }
  }

  async function runAnnouncementTaskAction(taskId: string, endpoint: string, payload: Record<string, unknown> = {}) {
    if (!current) return null
    const projectId = current.id
    const session = captureAnnouncementSession(taskId)
    setBusy(true)
    setStatusForProject(projectId, `正在执行公告任务：${announcementActionLabel(endpoint)}...`)
    try {
      const result = await api<AnnouncementTaskResult>(`/api/announcement-tasks/${taskId}/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (isCurrentAnnouncementSession(session) && result.run) setLatestRun({ ...result.run, artifacts: result.artifacts || [] })
      await refreshCurrent()
      if (!isCurrentAnnouncementSession(session)) return null
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
      if (isCurrentAnnouncementSession(session)) setStatusForProject(projectId, `公告任务失败：${message}`)
      if (isCurrentAnnouncementSession(session) && /约束文件|语言表|表头|可反查词条/.test(message)) {
        void alertDialog(`公告约束文件没有被正确读取：${message}`, { title: '约束文件读取失败', tone: 'warn' })
      }
      return null
    } finally {
      if (isCurrentAnnouncementSession(session)) setBusyForProject(projectId, false)
    }
  }

  async function runAnnouncementLookup(text: string, materialArtifactIds: string[], options: AnnouncementLookupOptions) {
    if (!current) return
    const projectId = current.id
    const session = captureAnnouncementSession()
    if (!text.trim() && !materialArtifactIds.length) {
      setStatus('请先上传/选择公告素材，或直接输入公告长文本。')
      return
    }
    setBusy(true)
    setStatus(`正在生成 ${currentLang.short} 公告检索包...`)
    try {
      const result = await api<AnnouncementLookupResult>(`/api/projects/${projectId}/announcement-lookup`, {
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
      if (!isCurrentAnnouncementSession(session)) return
      await refreshCurrent(projectId)
      if (!isCurrentAnnouncementSession(session)) return
      setAnnouncementLookupResult(result)
      setLatestRun({ ...result.run, artifacts: result.artifacts })
      setStatus(`公告检索包完成：命中术语 ${result.summary.matched_terms} 条，译文参考 ${result.summary.matched_translations} 条。`)
    } catch (error) {
      if (isCurrentAnnouncementSession(session)) setStatus(`公告检索包生成失败：${errorText(error)}`)
    } finally {
      if (isCurrentAnnouncementSession(session)) setBusy(false)
    }
  }

  return {
    cancelAnnouncementCancelHold,
    beginAnnouncementCancelHold,
    openAnnouncementTask,
    cancelAnnouncementTask,
    uploadAnnouncementAsset,
    uploadAnnouncementResponse,
    uploadAnnouncementConstraint,
    uploadAnnouncementTermsFile,
    createAnnouncementTask,
    runAnnouncementTaskAction,
    runAnnouncementLookup
  }
}
