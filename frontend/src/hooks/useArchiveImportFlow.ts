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
  type GlossaryConflictGroup,
  type GlossaryImportInspection,
  type GlossaryImportRow,
  type GlossaryRowDecision,
} from '../domain/archiveImport'
import { uploadProjectFile } from '../domain/projectApi'
import type { LanguageCode } from '../languages'
import type { Artifact, Project } from '../types'

type ArchiveBatchReadback = {
  id?: string
  status?: string
  summary?: Record<string, number>
  revision?: string
  result?: ArchiveImportCommitResult
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

function inspectionConfigKey(projectId: string, artifactId: string, settings: ArchiveImportSettings): string {
  return JSON.stringify([projectId, artifactId, settings.sheet, settings.sourceColumn,
    settings.targetColumn, settings.idColumn, settings.categoryColumn, settings.noteColumn])
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
    () => createArchiveImportState(initialArtifact, defaultLanguage, kind),
  )
  const stateRef = useRef(state)
  stateRef.current = state
  const generationRef = useRef(0)
  const requestRef = useRef<AbortController | null>(null)
  const inspectionAppliedKeyRef = useRef('')
  const manualLanguagesRef = useRef(false)
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
    inspectionAppliedKeyRef.current = ''
    manualLanguagesRef.current = false
    cancelRequest()
    generationRef.current += 1
    const next = createArchiveImportState(initialArtifact, defaultLanguage, kind)
    scopeRef.current = {
      projectId,
      artifactId: initialArtifact?.id || '',
      configKey: archiveImportConfigKey(next.settings),
    }
    tokenScopeRef.current = null
    dispatch({ type: 'reset', artifact: initialArtifact, language: defaultLanguage, kind })
  }, [cancelRequest, defaultLanguage, initialArtifact, kind, projectId])

  // Language choices are intentionally excluded: a user's manual selection must
  // not trigger a new inspection that overwrites that selection.
  useEffect(() => {
    const current = stateRef.current
    if (kind !== 'glossary' || !current.artifact) return
    if (inspectionAppliedKeyRef.current === inspectionConfigKey(projectId, current.artifact.id, current.settings)) return
    cancelRequest()
    const controller = new AbortController()
    requestRef.current = controller
    const generation = generationRef.current
    const artifactId = current.artifact.id
    const settings = current.settings
    const payload = {
      artifact_id: artifactId,
      sheet: settings.sheet || undefined,
      source_column: settings.sourceColumn || undefined,
      target_column: settings.targetColumn || undefined,
      term_key_column: settings.idColumn || undefined,
      category_column: settings.categoryColumn || undefined,
      note_column: settings.noteColumn || undefined,
      language: settings.languages[0] || defaultLanguage,
    }
    dispatch({ type: 'inspect_start' })
    void api<GlossaryImportInspection>(`/api/projects/${projectId}/glossary/import/inspect`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: controller.signal,
    }, '识别术语表语言').then((inspection) => {
      if (controller.signal.aborted || generation !== generationRef.current || scopeRef.current.artifactId !== artifactId) return
      const nextSettings = {
        ...stateRef.current.settings,
        languages: settings.targetColumn.trim() || manualLanguagesRef.current ? stateRef.current.settings.languages : inspection.languages,
        sheet: inspection.sheet && !['__csv__', '__json__'].includes(inspection.sheet) ? inspection.sheet : stateRef.current.settings.sheet,
      }
      inspectionAppliedKeyRef.current = inspectionConfigKey(projectId, artifactId, nextSettings)
      scopeRef.current = { projectId, artifactId, configKey: archiveImportConfigKey(nextSettings) }
      tokenScopeRef.current = null
      dispatch({ type: 'inspect_success', inspection, settings: nextSettings })
    }).catch((error) => {
      if (isAbort(error) || generation !== generationRef.current || scopeRef.current.artifactId !== artifactId) return
      const detail = detailFromError(error)
      const message = messageFromError(error, '未能识别语言，请选择目标语言并检查列映射。')
      if (detail?.code === 'sheet_selection_required') dispatch({ type: 'sheet_required', detail, message })
      else dispatch({ type: 'inspect_failure', message })
    }).finally(() => {
      if (requestRef.current === controller) requestRef.current = null
    })
    return () => controller.abort()
  }, [cancelRequest, defaultLanguage, kind, projectId, state.artifact?.id,
    state.settings.sheet, state.settings.sourceColumn, state.settings.targetColumn,
    state.settings.idColumn, state.settings.categoryColumn, state.settings.noteColumn])

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
    inspectionAppliedKeyRef.current = ''
    manualLanguagesRef.current = false
    const settings = resetSourceSpecificSettings(current.settings)
    if (kind === 'glossary') settings.languages = []
    invalidate(artifact?.id || '', settings)
    dispatch({ type: 'select_artifact', artifact, settings })
  }, [invalidate, kind])

  const uploadFile = useCallback(async (file: File) => {
    const current = stateRef.current
    inspectionAppliedKeyRef.current = ''
    manualLanguagesRef.current = false
    const settings = resetSourceSpecificSettings(current.settings)
    if (kind === 'glossary') settings.languages = []
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
    if (current.commitUncertain) return
    const settings: ArchiveImportSettings = {
      ...current.settings,
      ...updates,
      mode: kind === 'glossary' ? 'merge' : (updates.mode || current.settings.mode),
    }
    if (archiveImportConfigKey(settings) === archiveImportConfigKey(current.settings)) return
    if (updates.sheet !== undefined && updates.sheet !== current.settings.sheet) manualLanguagesRef.current = false
    if (updates.languages !== undefined) manualLanguagesRef.current = true
    invalidate(current.artifact?.id || '', settings)
    dispatch({ type: 'update_settings', settings, preserveDecisions: kind === 'glossary' && Object.keys(updates).every((key) => ['overrideProtected', 'datasetKey'].includes(key)) })
  }, [invalidate, kind])

  const toggleLanguage = useCallback((language: LanguageCode) => {
    if (kind === 'glossary' && stateRef.current.settings.targetColumn.trim()) {
      updateSettings({ languages: [language] })
      return
    }
    const selected = stateRef.current.settings.languages
    const languages = selected.includes(language)
      ? selected.filter((item) => item !== language)
      : [...selected, language]
    if (!languages.length) return
    updateSettings({ languages })
  }, [kind, updateSettings])

  const updateDecisions = useCallback((decisions: GlossaryRowDecision[]) => {
    const current = stateRef.current
    if (kind !== 'glossary' || current.busy === 'commit' || current.commitUncertain) return
    invalidate(current.artifact?.id || '', current.settings)
    const rows = new Map<string, GlossaryImportRow>(current.decisionRows.map((row) => [row.row_key, row]))
    for (const group of current.preview?.conflict_groups || []) {
      for (const row of group.rows) if (!rows.has(row.row_key)) rows.set(row.row_key, row)
    }
    dispatch({ type: 'update_decisions', decisions, rows: [...rows.values()] })
  }, [invalidate, kind])

  const setRowDecision = useCallback((rowKey: string, decision: GlossaryRowDecision | null) => {
    const decisions = stateRef.current.rowDecisions.filter((item) => item.row_key !== rowKey)
    if (decision) decisions.push(decision)
    updateDecisions(decisions)
  }, [updateDecisions])

  const keepConflictRow = useCallback((group: GlossaryConflictGroup, rowKey: string) => {
    const rowKeys = new Set(group.rows.map((row) => row.row_key))
    const decisions = stateRef.current.rowDecisions.filter((item) => !rowKeys.has(item.row_key) || (item.row_key === rowKey && item.action === 'edit'))
    for (const row of group.rows) if (row.row_key !== rowKey) decisions.push({ row_key: row.row_key, action: 'ignore' })
    updateDecisions(decisions)
  }, [updateDecisions])

  const scopeStillCurrent = useCallback((scope: { projectId: string; generation: number; artifactId: string; configKey: string }) => (
    scope.projectId === projectId
    && scope.generation === generationRef.current
    && scope.projectId === scopeRef.current.projectId
    && scope.artifactId === scopeRef.current.artifactId
    && scope.configKey === scopeRef.current.configKey
  ), [projectId])

  const analyze = useCallback(async (decisionsOverride?: GlossaryRowDecision[]) => {
    const current = stateRef.current
    if (current.commitUncertain) return false
    if (!current.artifact) {
      dispatch({ type: 'failure', message: '请先选择或上传文件。' })
      return false
    }
    if (!current.settings.languages.length) {
      dispatch({ type: 'failure', message: '请至少选择一种目标语言。' })
      return false
    }
    if (kind === 'glossary' && current.settings.targetColumn.trim() && current.settings.languages.length !== 1) {
      dispatch({ type: 'failure', message: '已指定单个目标译文列，请只选择一种目标语言，避免将同一列写入多个语种。' })
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
      payload.row_decisions = decisionsOverride || current.rowDecisions
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

  const ignoreAllConflicts = useCallback(async () => {
    const current = stateRef.current
    const decisions = new Map(current.rowDecisions.map((item) => [item.row_key, item]))
    for (const group of current.preview?.conflict_groups || []) {
      for (const row of group.rows) decisions.set(row.row_key, { row_key: row.row_key, action: 'ignore' })
    }
    const next = [...decisions.values()]
    updateDecisions(next)
    return analyze(next)
  }, [analyze, updateDecisions])

  const commit = useCallback(async () => {
    const current = stateRef.current
    const preview = current.preview
    const tokenScope = tokenScopeRef.current
    if (!preview || !preview.can_commit || !tokenScope || current.decisionsDirty) {
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
      const readCommittedResult = async () => {
        const payload = await api<{ batches?: ArchiveBatchReadback[] }>(
          `/api/projects/${projectId}/${archiveImportEndpoint(kind)}/import/batches`,
          { signal: controller.signal }, '核对提交批次',
        )
        const batch = payload.batches?.find((item) => item.id === preview.batch_id)
        return batch?.status === 'committed' && batch.result?.batch_id === preview.batch_id
          && batch.result.status === 'committed' ? batch.result : null
      }
      let result: ArchiveImportCommitResult | null = null
      // Failure to read a prior outcome is still uncertain, not a rejected write.
      if (current.commitUncertain) {
        try { result = await readCommittedResult() } catch (error) {
          if (controller.signal.aborted || !scopeStillCurrent(scope)) return false
          dispatch({ type: 'commit_uncertain', message: `仍无法核对原批次：${messageFromError(error, '请稍后重试。')}` })
          return false
        }
      }
      try {
        // A recovery click checks the original batch before retrying its idempotent token.
        if (!result) result = await api<ArchiveImportCommitResult>(
          `/api/projects/${projectId}/${archiveImportEndpoint(kind)}/import/commit?compact=true`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: preview.token }),
            signal: controller.signal,
          },
          '提交导入',
        )
        if (result?.batch_id !== preview.batch_id || result.status !== 'committed') throw new Error('提交响应未包含匹配的已保存批次。')
      } catch (error) {
        if (controller.signal.aborted || !scopeStillCurrent(scope)) return false
        if (error instanceof ApiRequestError && error.status >= 400 && error.status < 500) throw error
        // Network/5xx/invalid response does not prove that the transaction failed.
        result = null
        try { result = await readCommittedResult() } catch { /* Keep the original token for recovery. */ }
        if (controller.signal.aborted || !scopeStillCurrent(scope)) return false
        if (!result) {
          dispatch({ type: 'commit_uncertain', message: `未收到可核验的提交结果：${messageFromError(error, '请稍后核对本批次。')}` })
          return false
        }
      }
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
      if (error instanceof ApiRequestError && error.status >= 400 && error.status < 500) {
        generationRef.current += 1
        scopeRef.current = {
          projectId,
          artifactId: current.artifact?.id || '',
          configKey: archiveImportConfigKey(current.settings),
        }
        tokenScopeRef.current = null
        dispatch({ type: 'commit_rejected', message: messageFromError(error, '提交被拒绝，请重新分析后重试。'), detail })
        return false
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
    && !state.commitUncertain
    && state.settings.languages.length
    && !(kind === 'glossary' && state.settings.targetColumn.trim() && state.settings.languages.length !== 1)
    && (state.settings.mode !== 'snapshot' || (state.settings.datasetKey && state.settings.sheet))
    && !state.busy,
  )
  const canCommit = Boolean(
    state.stage === 'preview'
    && state.preview?.can_commit
    && !state.decisionsDirty
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
    setRowDecision,
    keepConflictRow,
    resetRowDecisions: () => updateDecisions([]),
    ignoreAllConflicts,
    analyze,
    commit,
    retryReadback,
    showSource,
    showSettings,
    close,
  }
}
