import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { api, ApiRequestError } from '../apiClient'
import {
  archiveImportConfigKey,
  archiveImportEndpoint,
  archiveImportReducer,
  createArchiveImportState,
  type ArchiveImportCommitResult,
  type ArchiveImportErrorDetail,
  type ArchiveImportKind,
  type ArchiveImportPreview,
  type ArchiveImportSettings,
} from '../domain/archiveImport'
import { uploadProjectFile } from '../domain/projectApi'
import type { LanguageCode } from '../languages'
import type { Artifact, Project } from '../types'

type ArchiveBatchReadback = {
  id?: string
  status?: string
  summary?: Record<string, number>
  revision?: string
}

type ArchiveBatchLineage = {
  id?: string
  status?: string
  dataset_key?: string
  sheet_key?: string
  languages?: LanguageCode[]
  revision?: string
}

export type UseArchiveImportFlowOptions = {
  projectId: string
  kind: ArchiveImportKind
  defaultLanguage: LanguageCode
  initialArtifact?: Artifact | null
  onReadback?: (project: Project) => void | Promise<void>
}

function resetSourceSpecificSettings(settings: ArchiveImportSettings): ArchiveImportSettings {
  return {
    ...settings,
    sheet: '',
    datasetKey: '',
    idColumn: '',
    sourceColumn: '',
    targetColumn: '',
    categoryColumn: '',
    noteColumn: '',
    overrideProtected: false,
  }
}

function detailFromError(error: unknown): ArchiveImportErrorDetail | null {
  if (!(error instanceof ApiRequestError) || !error.detail || typeof error.detail !== 'object') return null
  if (Array.isArray(error.detail)) {
    return { code: 'validation_error', message: error.message, issues: error.detail }
  }
  return error.detail as ArchiveImportErrorDetail
}

function messageFromError(error: unknown, fallback: string): string {
  const detail = detailFromError(error)
  if (typeof detail?.message === 'string' && detail.message.trim()) return detail.message
  if (error instanceof Error && error.message.trim()) return error.message
  return fallback
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function useArchiveImportFlow({
  projectId,
  kind,
  defaultLanguage,
  initialArtifact = null,
  onReadback,
}: UseArchiveImportFlowOptions) {
  const [state, dispatch] = useReducer(
    archiveImportReducer,
    undefined,
    () => createArchiveImportState(initialArtifact, defaultLanguage),
  )
  const stateRef = useRef(state)
  stateRef.current = state
  const generationRef = useRef(0)
  const requestRef = useRef<AbortController | null>(null)
  const lineageGenerationRef = useRef(0)
  const lineageRequestRef = useRef<AbortController | null>(null)
  const [lineages, setLineages] = useState<Array<{ key: string; sheet: string; value: string }>>([])
  const [lineagesLoading, setLineagesLoading] = useState(false)
  const [lineagesError, setLineagesError] = useState('')
  const scopeRef = useRef({
    projectId,
    artifactId: initialArtifact?.id || '',
    configKey: archiveImportConfigKey(state.settings),
  })
  const tokenScopeRef = useRef<{ projectId: string; generation: number; artifactId: string; configKey: string; token: string } | null>(null)

  const cancelRequest = useCallback(() => {
    requestRef.current?.abort()
    requestRef.current = null
  }, [])

  useEffect(() => {
    lineageRequestRef.current?.abort()
    lineageGenerationRef.current += 1
    const generation = lineageGenerationRef.current
    const controller = new AbortController()
    lineageRequestRef.current = controller
    setLineages([])
    setLineagesLoading(true)
    setLineagesError('')
    api<{ batches?: ArchiveBatchLineage[] }>(
      `/api/projects/${projectId}/${archiveImportEndpoint(kind)}/import/batches?compact=true`,
      { signal: controller.signal },
      '读取归档数据集',
    ).then((payload) => {
      if (controller.signal.aborted || lineageGenerationRef.current !== generation) return
      const unique = new Map<string, { key: string; sheet: string; value: string }>()
      for (const batch of payload.batches || []) {
        if (batch.status !== 'committed') continue
        const key = String(batch.dataset_key || '').trim()
        const sheet = String(batch.sheet_key || '').trim()
        if (!key || !sheet) continue
        const value = JSON.stringify([key, sheet])
        if (!unique.has(value)) unique.set(value, { key, sheet, value })
      }
      setLineages([...unique.values()])
    }).catch((error) => {
      if (!isAbort(error) && lineageGenerationRef.current === generation) {
        setLineagesError(messageFromError(error, '读取既有数据集失败。'))
      }
    }).finally(() => {
      if (lineageRequestRef.current === controller) lineageRequestRef.current = null
      if (!controller.signal.aborted && lineageGenerationRef.current === generation) setLineagesLoading(false)
    })
    return () => {
      controller.abort()
      if (lineageRequestRef.current === controller) lineageRequestRef.current = null
    }
  }, [kind, projectId])

  const invalidate = useCallback((artifactId: string, settings: ArchiveImportSettings) => {
    cancelRequest()
    generationRef.current += 1
    scopeRef.current = { projectId, artifactId, configKey: archiveImportConfigKey(settings) }
    tokenScopeRef.current = null
  }, [cancelRequest, projectId])

  useEffect(() => {
    if (scopeRef.current.projectId === projectId) return
    cancelRequest()
    generationRef.current += 1
    const next = createArchiveImportState(initialArtifact, defaultLanguage)
    scopeRef.current = {
      projectId,
      artifactId: initialArtifact?.id || '',
      configKey: archiveImportConfigKey(next.settings),
    }
    tokenScopeRef.current = null
    dispatch({ type: 'reset', artifact: initialArtifact, language: defaultLanguage })
  }, [cancelRequest, defaultLanguage, initialArtifact, projectId])

  useEffect(() => () => {
    requestRef.current?.abort()
    lineageRequestRef.current?.abort()
    generationRef.current += 1
    lineageGenerationRef.current += 1
    tokenScopeRef.current = null
  }, [])

  const selectArtifact = useCallback((artifact: Artifact | null) => {
    const current = stateRef.current
    if (artifact?.id === current.artifact?.id) return
    const settings = resetSourceSpecificSettings(current.settings)
    invalidate(artifact?.id || '', settings)
    dispatch({ type: 'select_artifact', artifact, settings })
  }, [invalidate])

  const uploadFile = useCallback(async (file: File) => {
    const current = stateRef.current
    const settings = resetSourceSpecificSettings(current.settings)
    invalidate('', settings)
    const generation = generationRef.current
    const uploadProjectId = projectId
    const controller = new AbortController()
    requestRef.current = controller
    dispatch({ type: 'select_artifact', artifact: null, settings })
    dispatch({ type: 'upload_start', filename: file.name })
    try {
      const artifact = await uploadProjectFile(
        uploadProjectId,
        file,
        kind === 'glossary' ? 'term_base' : (file.name.toLowerCase().endsWith('.json') ? 'language_table' : 'final_workbook'),
        '',
        () => undefined,
        controller.signal,
      )
      if (generationRef.current !== generation || scopeRef.current.projectId !== uploadProjectId) return null
      scopeRef.current = {
        projectId: uploadProjectId,
        artifactId: artifact.id,
        configKey: archiveImportConfigKey(settings),
      }
      dispatch({ type: 'select_artifact', artifact, settings })
      return artifact
    } catch (error) {
      if (!isAbort(error) && generationRef.current === generation && scopeRef.current.projectId === uploadProjectId) {
        dispatch({ type: 'failure', message: messageFromError(error, '上传失败，请重试。') })
      }
      return null
    } finally {
      if (requestRef.current === controller) requestRef.current = null
    }
  }, [invalidate, kind, projectId])

  const updateSettings = useCallback((updates: Partial<ArchiveImportSettings>) => {
    const current = stateRef.current
    const settings: ArchiveImportSettings = {
      ...current.settings,
      ...updates,
      mode: kind === 'glossary' ? 'merge' : (updates.mode || current.settings.mode),
    }
    if (archiveImportConfigKey(settings) === archiveImportConfigKey(current.settings)) return
    invalidate(current.artifact?.id || '', settings)
    dispatch({ type: 'update_settings', settings })
  }, [invalidate, kind])

  const toggleLanguage = useCallback((language: LanguageCode) => {
    const selected = stateRef.current.settings.languages
    const languages = selected.includes(language)
      ? selected.filter((item) => item !== language)
      : [...selected, language]
    if (!languages.length) return
    updateSettings({ languages })
  }, [updateSettings])

  const scopeStillCurrent = useCallback((scope: { projectId: string; generation: number; artifactId: string; configKey: string }) => (
    scope.projectId === projectId
    && scope.generation === generationRef.current
    && scope.projectId === scopeRef.current.projectId
    && scope.artifactId === scopeRef.current.artifactId
    && scope.configKey === scopeRef.current.configKey
  ), [projectId])

  const analyze = useCallback(async () => {
    const current = stateRef.current
    if (!current.artifact) {
      dispatch({ type: 'failure', message: '请先选择或上传文件。' })
      return false
    }
    if (!current.settings.languages.length) {
      dispatch({ type: 'failure', message: '请至少选择一种目标语言。' })
      return false
    }
    if (current.settings.mode === 'snapshot' && (!current.settings.datasetKey || !current.settings.sheet)) {
      dispatch({ type: 'failure', message: '快照覆盖必须选择后端已识别的既有数据集与工作表。' })
      return false
    }
    cancelRequest()
    const controller = new AbortController()
    requestRef.current = controller
    const scope = {
      projectId,
      generation: generationRef.current,
      artifactId: current.artifact.id,
      configKey: archiveImportConfigKey(current.settings),
    }
    dispatch({ type: 'analyze_start' })
    const settings = current.settings
    const payload: Record<string, unknown> = {
      artifact_id: current.artifact.id,
      mode: kind === 'glossary' ? 'merge' : settings.mode,
      languages: settings.languages,
      language: settings.languages[0],
      auto_languages: !settings.targetColumn,
      override_protected: settings.overrideProtected,
    }
    if (settings.sheet) payload.sheet = settings.sheet
    if (settings.datasetKey) payload.dataset_key = settings.datasetKey
    if (settings.sourceColumn) payload.source_column = settings.sourceColumn
    if (settings.targetColumn) payload.target_column = settings.targetColumn
    if (settings.noteColumn) payload.note_column = settings.noteColumn
    if (kind === 'glossary') {
      payload.confirmed_glossary = true
      if (settings.idColumn) payload.term_key_column = settings.idColumn
      if (settings.categoryColumn) payload.category_column = settings.categoryColumn
    } else if (settings.idColumn) {
      payload.id_column = settings.idColumn
    }
    try {
      const preview = await api<ArchiveImportPreview>(
        `/api/projects/${projectId}/${archiveImportEndpoint(kind)}/import/analyze`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: controller.signal,
        },
        '分析导入差异',
      )
      if (!scopeStillCurrent(scope)) return false
      tokenScopeRef.current = { ...scope, token: preview.token }
      dispatch({ type: 'analyze_success', preview })
      return true
    } catch (error) {
      if (isAbort(error) || !scopeStillCurrent(scope)) return false
      const detail = detailFromError(error)
      const message = messageFromError(error, '差异分析失败，请检查文件和设置。')
      if (detail?.code === 'sheet_selection_required') {
        dispatch({ type: 'sheet_required', detail, message })
      } else {
        dispatch({ type: 'failure', message, detail })
      }
      return false
    } finally {
      if (requestRef.current === controller) requestRef.current = null
    }
  }, [cancelRequest, kind, projectId, scopeStillCurrent])

  const commit = useCallback(async () => {
    const current = stateRef.current
    const preview = current.preview
    const tokenScope = tokenScopeRef.current
    if (!preview || !preview.can_commit || !tokenScope) {
      dispatch({ type: 'failure', message: '当前没有可提交的有效预览，请重新分析差异。' })
      return false
    }
    const scope = {
      projectId,
      generation: generationRef.current,
      artifactId: current.artifact?.id || '',
      configKey: archiveImportConfigKey(current.settings),
    }
    if (!scopeStillCurrent(scope)
      || tokenScope.projectId !== scope.projectId
      || tokenScope.generation !== scope.generation
      || tokenScope.artifactId !== scope.artifactId
      || tokenScope.configKey !== scope.configKey
      || tokenScope.token !== preview.token) {
      dispatch({ type: 'failure', message: '预览已过期，请重新分析差异。' })
      return false
    }
    cancelRequest()
    const controller = new AbortController()
    requestRef.current = controller
    dispatch({ type: 'commit_start' })
    try {
      const result = await api<ArchiveImportCommitResult>(
        `/api/projects/${projectId}/${archiveImportEndpoint(kind)}/import/commit?compact=true`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: preview.token }),
          signal: controller.signal,
        },
        '提交导入',
      )
      if (!scopeStillCurrent(scope)) return false
      let readbackWarning = ''
      try {
        const [project, batches] = await Promise.all([
          api<Project>(`/api/projects/${projectId}?include_archives=false`, { signal: controller.signal }, '读回项目归档'),
          api<{ batches?: ArchiveBatchReadback[] }>(
            `/api/projects/${projectId}/${archiveImportEndpoint(kind)}/import/batches?compact=true`,
            { signal: controller.signal },
            '读回导入批次',
          ),
        ])
        if (!scopeStillCurrent(scope)) return false
        const persisted = (batches.batches || []).find((batch) => batch.id === result.batch_id)
        if (!persisted || persisted.status !== 'committed') throw new Error('提交批次读回状态不一致，请刷新后核对。')
        await onReadback?.(project)
      } catch (error) {
        if (isAbort(error) || !scopeStillCurrent(scope)) return false
        readbackWarning = `提交已完成，但自动读回失败：${messageFromError(error, '请关闭后刷新项目。')}`
      }
      if (!scopeStillCurrent(scope)) return false
      dispatch({ type: 'commit_success', result, readbackWarning })
      return true
    } catch (error) {
      if (isAbort(error) || !scopeStillCurrent(scope)) return false
      const detail = detailFromError(error)
      if (error instanceof ApiRequestError && error.status === 409) {
        generationRef.current += 1
        scopeRef.current = {
          projectId,
          artifactId: current.artifact?.id || '',
          configKey: archiveImportConfigKey(current.settings),
        }
        tokenScopeRef.current = null
        dispatch({ type: 'show_settings' })
      }
      dispatch({ type: 'failure', message: messageFromError(error, '提交失败，请重新分析后重试。'), detail })
      return false
    } finally {
      if (requestRef.current === controller) requestRef.current = null
    }
  }, [cancelRequest, kind, onReadback, projectId, scopeStillCurrent])

  const retryReadback = useCallback(async () => {
    const result = stateRef.current.result
    if (!result?.batch_id) return false
    cancelRequest()
    const controller = new AbortController()
    requestRef.current = controller
    const generation = generationRef.current
    dispatch({ type: 'readback_start' })
    try {
      const [project, batches] = await Promise.all([
        api<Project>(`/api/projects/${projectId}?include_archives=false`, { signal: controller.signal }, '读回项目归档'),
        api<{ batches?: ArchiveBatchReadback[] }>(
          `/api/projects/${projectId}/${archiveImportEndpoint(kind)}/import/batches?compact=true`,
          { signal: controller.signal },
          '读回导入批次',
        ),
      ])
      if (controller.signal.aborted || generationRef.current !== generation) return false
      const persisted = (batches.batches || []).find((batch) => batch.id === result.batch_id)
      if (!persisted || persisted.status !== 'committed') throw new Error('提交批次读回状态不一致，请刷新后核对。')
      await onReadback?.(project)
      if (controller.signal.aborted || generationRef.current !== generation) return false
      dispatch({ type: 'readback_success' })
      return true
    } catch (error) {
      if (isAbort(error) || generationRef.current !== generation) return false
      dispatch({
        type: 'readback_failure',
        message: `提交已完成，但自动读回失败：${messageFromError(error, '请关闭后刷新项目。')}`,
      })
      return false
    } finally {
      if (requestRef.current === controller) requestRef.current = null
    }
  }, [cancelRequest, kind, onReadback, projectId])

  const close = useCallback(() => {
    cancelRequest()
    generationRef.current += 1
    tokenScopeRef.current = null
  }, [cancelRequest])

  const showSource = useCallback(() => dispatch({ type: 'show_source' }), [])
  const showSettings = useCallback(() => dispatch({ type: 'show_settings' }), [])

  const tokenScope = tokenScopeRef.current
  const canAnalyze = Boolean(
    state.artifact
    && state.settings.languages.length
    && (state.settings.mode !== 'snapshot' || (state.settings.datasetKey && state.settings.sheet))
    && !state.busy,
  )
  const canCommit = Boolean(
    state.stage === 'preview'
    && state.preview?.can_commit
    && tokenScope
    && tokenScope.token === state.preview.token
    && tokenScope.projectId === projectId
    && tokenScope.generation === generationRef.current
    && tokenScope.artifactId === state.artifact?.id
    && tokenScope.configKey === archiveImportConfigKey(state.settings)
    && !state.busy,
  )

  return {
    state,
    canAnalyze,
    canCommit,
    lineages,
    lineagesLoading,
    lineagesError,
    selectArtifact,
    uploadFile,
    updateSettings,
    toggleLanguage,
    analyze,
    commit,
    retryReadback,
    showSource,
    showSettings,
    close,
  }
}
