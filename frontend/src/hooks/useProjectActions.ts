import { useCallback } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { api } from '../apiClient'
import { errorText } from '../appText'
import { artifactPickerLabel, uniqueArtifactsByContent } from '../domain/artifacts'
import { uploadProjectFile } from '../domain/projectApi'
import { mergeProjectListSummaries } from '../domain/projectState'
import type { LanguageCode, LanguageOption } from '../languages'
import type { ConfirmDialogOptions } from '../components/modals/ConfirmModal'
import type { AppRuntimeVersion, AppSettings, AppView, Artifact, Project, ProjectAnalysisResponse, ProjectHarness, ProjectTab, QualityIssue } from '../types'

export interface UseProjectActionsParams {
  current: Project | undefined
  currentId: string
  currentIdRef: { current: string }
  intro: string
  assetArtifacts: Artifact[]
  selectedLanguage: LanguageCode
  currentLang: LanguageOption
  busy: boolean
  deleteHoldTimer: { current: number | null }
  longPressTriggeredProjectId: { current: string }
  isCurrentProject: (projectId?: string | null) => boolean
  setProjects: Dispatch<SetStateAction<Project[]>>
  setCurrentId: (id: string) => void
  setView: (view: AppView) => void
  setTab: (tab: ProjectTab) => void
  setBusy: (value: boolean) => void
  setStatus: (message: string) => void
  setStatusForProject: (projectId: string, message: string) => void
  setQualityIssues: (issues: QualityIssue[]) => void
  setRuntimeVersion: (version: AppRuntimeVersion) => void
  setSettings: (settings: AppSettings) => void
  setNewProjectOpen: (value: boolean) => void
  setDeleteHoldProjectId: (id: string) => void
  setDeleteProjectTarget: (project: Project | null) => void
  setSourceArtifact: (artifact: Artifact | null) => void
  setAssetArtifacts: Dispatch<SetStateAction<Artifact[]>>
  resetProjectTransientState: (message?: string) => void
  confirm: (message: string, options?: ConfirmDialogOptions) => Promise<boolean>
  runGlossaryExtract: (inputArtifact?: Artifact | null) => Promise<void>
}

// Project lifecycle, list refresh and low-level upload/analysis handlers
// moved verbatim out of main.tsx's App component. `runGlossaryExtract` is
// passed in (forwarded via a ref in main.tsx) because `runAnalysis` here can
// trigger a glossary scan, while the actual glossary logic lives in
// useGlossaryActions, which itself depends on useTranslationActions.
//
// Every returned handler is wrapped in `useCallback` so components that
// receive them as props (e.g. the memoized sidebar `ProjectListItem`) can
// skip re-rendering when the underlying dependencies haven't changed, even
// though this hook itself re-runs on every `App` render. Declaration order
// below matters: functions that call another function from this same hook
// are declared after the function they depend on (useCallback uses `const`,
// which isn't hoisted like the original `function` declarations were).
export function useProjectActions(params: UseProjectActionsParams) {
  const {
    current,
    currentId,
    currentIdRef,
    intro,
    assetArtifacts,
    selectedLanguage,
    currentLang,
    busy,
    deleteHoldTimer,
    longPressTriggeredProjectId,
    isCurrentProject,
    setProjects,
    setCurrentId,
    setView,
    setTab,
    setBusy,
    setStatus,
    setStatusForProject,
    setQualityIssues,
    setRuntimeVersion,
    setSettings,
    setNewProjectOpen,
    setDeleteHoldProjectId,
    setDeleteProjectTarget,
    setSourceArtifact,
    setAssetArtifacts,
    resetProjectTransientState,
    confirm,
    runGlossaryExtract
  } = params

  const cancelProjectDeleteHold = useCallback(() => {
    if (deleteHoldTimer.current !== null) {
      window.clearTimeout(deleteHoldTimer.current)
      deleteHoldTimer.current = null
    }
    setDeleteHoldProjectId('')
  }, [deleteHoldTimer, setDeleteHoldProjectId])

  const beginProjectDeleteHold = useCallback((project: Project) => {
    if (busy) return
    cancelProjectDeleteHold()
    setDeleteHoldProjectId(project.id)
    deleteHoldTimer.current = window.setTimeout(() => {
      longPressTriggeredProjectId.current = project.id
      deleteHoldTimer.current = null
      setDeleteHoldProjectId('')
      setDeleteProjectTarget(project)
    }, 850)
  }, [busy, cancelProjectDeleteHold, deleteHoldTimer, longPressTriggeredProjectId, setDeleteHoldProjectId, setDeleteProjectTarget])

  const refreshProjects = useCallback(async (selectId?: string, signal?: AbortSignal) => {
    const loaded = await api<Project[]>('/api/projects', signal ? { signal } : undefined)
    const preferred = selectId && loaded.some((item) => item.id === selectId)
      ? selectId
      : (loaded.some((item) => item.id === currentIdRef.current) ? currentIdRef.current : '')
    const nextId = preferred || loaded[0]?.id || ''
    setProjects((prev) => mergeProjectListSummaries(prev, loaded))
    currentIdRef.current = nextId
    setCurrentId(nextId)
  }, [currentIdRef, setProjects, setCurrentId])

  const selectProject = useCallback((project: Project, event: React.MouseEvent<HTMLButtonElement>) => {
    if (longPressTriggeredProjectId.current === project.id) {
      event.preventDefault()
      longPressTriggeredProjectId.current = ''
      return
    }
    if (project.id !== currentId) resetProjectTransientState()
    currentIdRef.current = project.id
    setCurrentId(project.id)
    setView('overview')
    setTab('meta')
  }, [longPressTriggeredProjectId, currentId, resetProjectTransientState, currentIdRef, setCurrentId, setView, setTab])

  const deleteProject = useCallback(async (project: Project) => {
    const targetId = project.id
    const targetName = project.name
    setBusy(true)
    setStatus(`正在删除项目“${targetName}”...`)
    try {
      await api(`/api/projects/${targetId}`, { method: 'DELETE' })
      const loaded = await api<Project[]>('/api/projects')
      const activeId = currentIdRef.current
      const nextId = loaded.some((item) => item.id === activeId && item.id !== targetId) ? activeId : loaded[0]?.id || ''
      setProjects((prev) => mergeProjectListSummaries(prev, loaded))
      currentIdRef.current = nextId
      setCurrentId(nextId)
      if (targetId === activeId) {
        setView('overview')
        setTab('meta')
      }
      longPressTriggeredProjectId.current = ''
      setDeleteProjectTarget(null)
      setStatus(`项目“${targetName}”已删除`)
    } catch (error) {
      if (/not found/i.test(errorText(error))) {
        await refreshProjects()
        longPressTriggeredProjectId.current = ''
        setDeleteProjectTarget(null)
        setStatus(`项目“${targetName}”已不存在，列表已刷新。`)
      } else {
        setStatus(`删除项目失败：${errorText(error)}`)
      }
    } finally {
      setBusy(false)
    }
  }, [setBusy, setStatus, currentIdRef, setProjects, setCurrentId, setView, setTab, longPressTriggeredProjectId, setDeleteProjectTarget, refreshProjects])

  const refreshCurrent = useCallback(async (projectId = currentIdRef.current): Promise<Project | null> => {
    if (!projectId) return null
    const loaded = await api<Project>(`/api/projects/${projectId}`)
    if (!isCurrentProject(projectId)) return loaded
    setProjects((prev) => prev.map((p) => (p.id === loaded.id ? loaded : p)))
    return loaded
  }, [currentIdRef, isCurrentProject, setProjects])

  const refreshProjectSnapshot = useCallback(async (projectId: string, signal?: AbortSignal): Promise<Project | null> => {
    if (!projectId) return null
    try {
      const loaded = await api<Project>(`/api/projects/${projectId}`, signal ? { signal } : undefined)
      setProjects((prev) => prev.map((p) => (p.id === loaded.id ? loaded : p)))
      return loaded
    } catch (error) {
      if (/not found/i.test(errorText(error))) await refreshProjects()
      return null
    }
  }, [setProjects, refreshProjects])

  const refreshRuntimeVersion = useCallback(async () => {
    try {
      const payload = await api<AppRuntimeVersion>('/api/version')
      setRuntimeVersion(payload)
    } catch {
      setRuntimeVersion({ version: 'unknown', deployment_mode: 'unknown' })
    }
  }, [setRuntimeVersion])

  const refreshSettings = useCallback(async () => {
    setSettings(await api<AppSettings>('/api/settings'))
  }, [setSettings])

  const saveProjectMeta = useCallback(async (updates: Partial<Project>) => {
    if (!current) return
    try {
      await api<Project>(`/api/projects/${current.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      })
      await refreshCurrent()
      setStatus('项目元信息已保存')
    } catch (error) {
      setStatus(`项目元信息保存失败：${errorText(error)}`)
      throw error
    }
  }, [current, refreshCurrent, setStatus])

  const loadQualityIssues = useCallback(async (runId: string, projectId = currentIdRef.current): Promise<QualityIssue[]> => {
    try {
      const result = await api<{ issues: QualityIssue[] }>(`/api/runs/${runId}/quality-issues`)
      if (isCurrentProject(projectId)) setQualityIssues(result.issues)
      return result.issues
    } catch (error) {
      setStatusForProject(projectId, `QA 问题加载失败：${errorText(error)}`)
      return []
    }
  }, [currentIdRef, isCurrentProject, setQualityIssues, setStatusForProject])

  const createProject = useCallback(async (form: FormData) => {
    const created = await api<Project>('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.get('name'),
        type: form.get('type'),
        icon: form.get('icon') || '',
        description: form.get('description') || ''
      })
    })
    setNewProjectOpen(false)
    await refreshProjects(created.id)
    setView('overview')
    setTab('meta')
    setStatus(created.duplicate ? `项目“${created.name}”已存在，已切换到已有项目。` : `项目“${created.name}”已创建。`)
  }, [setNewProjectOpen, refreshProjects, setView, setTab, setStatus])

  const upload = useCallback(async (file: File, kind: string, purpose = ''): Promise<Artifact | null> => {
    if (!current) return null
    setBusy(true)
    setStatus(`正在上传：${file.name}`)
    try {
      const artifact = await uploadProjectFile(current.id, file, kind, purpose, (done, total) => {
        if (total > 1) setStatus(`正在上传：${file.name}（分片 ${done}/${total}）`)
      })
      await refreshCurrent()
      if (artifact.duplicate) {
        setStatus(`已存在，已复用：${artifactPickerLabel(artifact)}`)
      } else {
        setStatus(`已上传：${artifactPickerLabel(artifact)}`)
      }
      return artifact
    } catch (error) {
      setStatus(`上传失败：${errorText(error)}`)
      return null
    } finally {
      setBusy(false)
    }
  }, [current, setBusy, setStatus, refreshCurrent])

  const runAnalysis = useCallback(async () => {
    if (!current) return
    setBusy(true)
    setStatus('正在读取项目资料并调用 AI 分析...')
    try {
      const result = await api<ProjectAnalysisResponse>(`/api/projects/${current.id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intro: intro.trim() || current.description || `${current.name} ${current.type}`,
          asset_artifact_ids: assetArtifacts.map((artifact) => artifact.id),
          target_language: selectedLanguage
        })
      })
      if (isCurrentProject(current.id)) {
        setProjects((prev) => prev.map((p) => (p.id === result.project.id ? result.project : p)))
      }
      const summary = result.analysis?.summary || {}
      const warning = result.analysis?.warning
      setStatus(`${currentLang.short} 项目分析完成：已读取 ${summary.parsed ?? 0}/${summary.total ?? 0} 个资料${warning ? `；${warning}` : ''}`)
      const candidates = result.analysis?.language_table_candidates || []
      if (candidates.length) {
        const confirmScan = await confirm(`识别到 ${candidates.length} 个完整语言表。是否现在扫描术语候选？候选不会直接进入项目术语库。`, {
          title: '扫描术语候选',
          confirmLabel: '现在扫描',
          cancelLabel: '暂不扫描'
        })
        if (confirmScan) {
          const candidate = candidates[0]
          const artifacts = result.project.artifacts || []
          const artifact = artifacts.find((item) => item.id === candidate.artifact_id) || assetArtifacts.find((item) => item.id === candidate.artifact_id) || null
          if (artifact) {
            setSourceArtifact(artifact)
            await runGlossaryExtract(artifact)
          }
        }
      }
    } catch (error) {
      setStatus(`项目分析失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }, [current, setBusy, setStatus, intro, assetArtifacts, selectedLanguage, isCurrentProject, setProjects, currentLang, confirm, setSourceArtifact, runGlossaryExtract])

  const saveHarness = useCallback(async (updates: Partial<ProjectHarness>) => {
    if (!current) return
    await api(`/api/projects/${current.id}/harness`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshCurrent()
    setStatus('项目规则已保存，仅对当前项目生效')
  }, [current, refreshCurrent, setStatus])

  const uploadAsset = useCallback(async (file: File): Promise<Artifact | null> => {
    const artifact = await upload(file, 'asset')
    if (artifact) {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `参考素材已存在，已复用：${artifactPickerLabel(artifact)}` : `参考素材已归档：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }, [upload, setAssetArtifacts, setStatus])

  const uploadProjectMaterial = useCallback(async (file: File): Promise<Artifact | null> => {
    const artifact = await upload(file, 'asset', 'project_material')
    if (artifact) {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `参考素材已存在，已复用：${artifactPickerLabel(artifact)}` : `参考素材已归档：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }, [upload, setAssetArtifacts, setStatus])

  return {
    cancelProjectDeleteHold,
    beginProjectDeleteHold,
    selectProject,
    deleteProject,
    refreshProjects,
    refreshCurrent,
    refreshProjectSnapshot,
    refreshRuntimeVersion,
    refreshSettings,
    saveProjectMeta,
    loadQualityIssues,
    createProject,
    upload,
    runAnalysis,
    saveHarness,
    uploadAsset,
    uploadProjectMaterial
  }
}
