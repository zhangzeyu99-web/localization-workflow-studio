import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../apiClient'
import { errorText } from '../appText'
import { uploadProjectFile } from '../domain/projectApi'
import { languageQuery, languageSpec, type LanguageCode } from '../languages'
import type { Artifact, GlossaryBatch, GlossaryCandidate, Project } from '../types'

type CandidateBusy = 'upload' | 'scan' | 'update' | 'resolve' | 'translate' | null

type CandidateScope = {
  projectId: string
  generation: number
  artifactId: string
  batchId: string
}

type ProjectGlossaryCandidateOptions = {
  project: Project
  language: LanguageCode
  onReadback: () => void | Promise<void>
}

type ExtractResult = {
  glossary_backfill?: {
    batch_id?: string
    candidates?: number
    pending_confirmation?: number
  }
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function useProjectGlossaryCandidates({ project, language, onReadback }: ProjectGlossaryCandidateOptions) {
  const [artifact, setArtifact] = useState<Artifact | null>(null)
  const [batch, setBatch] = useState<GlossaryBatch | null>(null)
  const [candidates, setCandidates] = useState<GlossaryCandidate[]>([])
  const [busy, setBusy] = useState<CandidateBusy>(null)
  const [status, setStatus] = useState('请选择项目内完整语言表，或上传新的 XLSX。')
  const artifactRef = useRef<Artifact | null>(null)
  const generationRef = useRef(0)
  const requestRef = useRef<AbortController | null>(null)
  const scopeRef = useRef<CandidateScope>({ projectId: project.id, generation: 0, artifactId: '', batchId: '' })
  const languageRef = useRef(language)

  const cancelRequest = useCallback(() => {
    requestRef.current?.abort()
    requestRef.current = null
  }, [])

  const invalidate = useCallback((nextArtifact: Artifact | null): CandidateScope => {
    cancelRequest()
    generationRef.current += 1
    artifactRef.current = nextArtifact
    const scope = {
      projectId: project.id,
      generation: generationRef.current,
      artifactId: nextArtifact?.id || '',
      batchId: '',
    }
    scopeRef.current = scope
    setArtifact(nextArtifact)
    setBatch(null)
    setCandidates([])
    setBusy(null)
    setStatus(nextArtifact ? '语言表已就绪；扫描只生成候选，不会直接写入术语库。' : '请选择项目内完整语言表，或上传新的 XLSX。')
    return scope
  }, [cancelRequest, project.id])

  useEffect(() => {
    invalidate(null)
  }, [invalidate, project.id])

  useEffect(() => {
    if (languageRef.current === language) return
    languageRef.current = language
    invalidate(artifactRef.current)
  }, [invalidate, language])

  useEffect(() => () => {
    requestRef.current?.abort()
    generationRef.current += 1
  }, [])

  const generationStillCurrent = useCallback((scope: CandidateScope) => (
    scope.projectId === project.id
    && scope.projectId === scopeRef.current.projectId
    && scope.generation === generationRef.current
    && scope.generation === scopeRef.current.generation
  ), [project.id])

  const baseScopeStillCurrent = useCallback((scope: CandidateScope) => (
    generationStillCurrent(scope)
    && scope.artifactId === scopeRef.current.artifactId
  ), [generationStillCurrent])

  const fullScopeStillCurrent = useCallback((scope: CandidateScope) => (
    baseScopeStillCurrent(scope)
    && Boolean(scope.batchId)
    && scope.batchId === scopeRef.current.batchId
  ), [baseScopeStillCurrent])

  const readBatch = useCallback(async (scope: CandidateScope, signal?: AbortSignal) => {
    const loaded = await api<{ batches: GlossaryBatch[]; active_batch: GlossaryBatch | null; candidates: GlossaryCandidate[] }>(
      `/api/projects/${scope.projectId}/glossary/batches?${languageQuery(language)}`,
      signal ? { signal } : undefined,
      '读回术语候选批次',
    )
    if (!fullScopeStillCurrent(scope)) return false
    const scopedBatch = (loaded.batches || []).find((item) => item.id === scope.batchId) || null
    const activeMatches = loaded.active_batch?.id === scope.batchId
      && loaded.active_batch.source_artifact_id === scope.artifactId
    if (!scopedBatch || !activeMatches) {
      setBatch(null)
      setCandidates([])
      setStatus('候选批次已被新的并发扫描替代，请重新扫描当前语言表。')
      return false
    }
    setBatch(scopedBatch)
    setCandidates((loaded.candidates || []).filter((candidate) => candidate.batch_id === scope.batchId))
    return true
  }, [fullScopeStillCurrent, language])

  const selectArtifact = useCallback((nextArtifact: Artifact | null) => {
    if (nextArtifact?.id === artifactRef.current?.id) return
    invalidate(nextArtifact)
  }, [invalidate])

  const uploadFile = useCallback(async (file: File) => {
    const scope = invalidate(null)
    const controller = new AbortController()
    requestRef.current = controller
    setBusy('upload')
    setStatus(`正在上传：${file.name}`)
    try {
      const uploaded = await uploadProjectFile(scope.projectId, file, 'language_table', '', () => undefined, controller.signal)
      if (!generationStillCurrent(scope)) return null
      const uploadedScope = { ...scope, artifactId: uploaded.id }
      scopeRef.current = uploadedScope
      artifactRef.current = uploaded
      setArtifact(uploaded)
      setStatus('语言表已上传；扫描只生成候选，不会直接写入术语库。')
      return uploaded
    } catch (error) {
      if (!isAbort(error) && generationStillCurrent(scope)) setStatus(`语言表上传失败：${errorText(error)}`)
      return null
    } finally {
      if (requestRef.current === controller) requestRef.current = null
      if (generationStillCurrent(scope)) setBusy(null)
    }
  }, [generationStillCurrent, invalidate])

  const scan = useCallback(async () => {
    const selected = artifactRef.current
    if (!selected) {
      setStatus('请先选择或上传完整语言表。')
      return false
    }
    const scope = invalidate(selected)
    const controller = new AbortController()
    requestRef.current = controller
    setBusy('scan')
    setStatus('正在扫描术语候选；项目术语库暂不会变化。')
    try {
      const result = await api<ExtractResult>(`/api/projects/${scope.projectId}/glossary/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: selected.id,
          project_name: project.name,
          source_only: false,
          id_column: 'ID',
          source_column: 'cn',
          ...(language === 'vn' ? {} : { target_column: languageSpec(language).targetHeader }),
          language,
          project_material_artifact_ids: [],
          project_notes: [project.description || `${project.name} ${project.type}`].filter(Boolean),
          include_empty_final_terms: true,
          ai_candidate_supplement: true,
          update_project_prompt: false,
        }),
        signal: controller.signal,
      }, '扫描术语候选')
      if (!baseScopeStillCurrent(scope)) return false
      const batchId = String(result.glossary_backfill?.batch_id || '')
      if (!batchId) {
        setStatus('扫描完成，但后端没有返回候选批次；术语库未变化。')
        return false
      }
      const scopedBatch = { ...scope, batchId }
      scopeRef.current = scopedBatch
      const loaded = await readBatch(scopedBatch, controller.signal)
      if (!loaded || !fullScopeStillCurrent(scopedBatch)) return false
      const pending = result.glossary_backfill?.pending_confirmation ?? result.glossary_backfill?.candidates ?? 0
      setStatus(`候选扫描完成：待人工确认 ${pending} 条；接受前不会进入项目术语库。`)
      return true
    } catch (error) {
      if (!isAbort(error) && baseScopeStillCurrent(scope)) setStatus(`候选扫描失败：${errorText(error)}`)
      return false
    } finally {
      if (requestRef.current === controller) requestRef.current = null
      if (baseScopeStillCurrent(scope)) setBusy(null)
    }
  }, [baseScopeStillCurrent, fullScopeStillCurrent, invalidate, language, project.description, project.name, project.type, readBatch])

  const updateCandidate = useCallback(async (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => {
    const scope = { ...scopeRef.current }
    if (!fullScopeStillCurrent(scope) || candidate.batch_id !== scope.batchId) return false
    const controller = new AbortController()
    requestRef.current = controller
    setBusy('update')
    setStatus(`正在保存候选“${candidate.source}”…`)
    try {
      await api(`/api/projects/${scope.projectId}/glossary/candidates/${candidate.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
        signal: controller.signal,
      }, '保存术语候选')
      if (!fullScopeStillCurrent(scope)) return false
      const loaded = await readBatch(scope, controller.signal)
      if (!loaded || !fullScopeStillCurrent(scope)) return false
      if (fullScopeStillCurrent(scope)) setStatus(`候选“${candidate.source}”已保存。`)
      return true
    } catch (error) {
      if (!isAbort(error) && fullScopeStillCurrent(scope)) setStatus(`候选保存失败：${errorText(error)}`)
      return false
    } finally {
      if (requestRef.current === controller) requestRef.current = null
      if (fullScopeStillCurrent(scope)) setBusy(null)
    }
  }, [fullScopeStillCurrent, readBatch])

  const resolveCandidates = useCallback(async (
    batchId: string,
    selectedCandidates: GlossaryCandidate[],
    action: 'accept' | 'reject',
  ) => {
    const scope = { ...scopeRef.current }
    if (!selectedCandidates.length || batchId !== scope.batchId || !fullScopeStillCurrent(scope)) return
    const controller = new AbortController()
    requestRef.current = controller
    setBusy('resolve')
    setStatus(action === 'accept' ? `正在加入 ${selectedCandidates.length} 条候选…` : `正在跳过 ${selectedCandidates.length} 条候选…`)
    try {
      await api(`/api/projects/${scope.projectId}/glossary/batches/${batchId}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_ids: selectedCandidates.map((candidate) => candidate.id) }),
        signal: controller.signal,
      }, action === 'accept' ? '加入术语候选' : '跳过术语候选')
      if (!fullScopeStillCurrent(scope)) return
      await onReadback()
      if (!fullScopeStillCurrent(scope)) return
      await readBatch(scope, controller.signal)
      if (fullScopeStillCurrent(scope)) {
        setStatus(action === 'accept'
          ? `已加入 ${selectedCandidates.length} 条候选；项目术语库已读回。`
          : `已跳过 ${selectedCandidates.length} 条候选；项目术语库未增加。`)
      }
    } catch (error) {
      if (!isAbort(error) && fullScopeStillCurrent(scope)) setStatus(`候选处理失败：${errorText(error)}`)
    } finally {
      if (requestRef.current === controller) requestRef.current = null
      if (fullScopeStillCurrent(scope)) setBusy(null)
    }
  }, [fullScopeStillCurrent, onReadback, readBatch])

  const translateMissing = useCallback(async (batchId: string) => {
    const scope = { ...scopeRef.current }
    if (batchId !== scope.batchId || !fullScopeStillCurrent(scope)) return
    const controller = new AbortController()
    requestRef.current = controller
    setBusy('translate')
    setStatus(`正在补译缺失的 ${languageSpec(language).short} 候选…`)
    try {
      const result = await api<{ translated_count?: number }>(
        `/api/projects/${scope.projectId}/glossary/batches/${batchId}/translate-missing`,
        { method: 'POST', signal: controller.signal },
        '补译术语候选',
      )
      if (!fullScopeStillCurrent(scope)) return
      await readBatch(scope, controller.signal)
      if (fullScopeStillCurrent(scope)) setStatus(`已补译 ${result.translated_count || 0} 条候选，请人工审核。`)
    } catch (error) {
      if (!isAbort(error) && fullScopeStillCurrent(scope)) setStatus(`候选补译失败：${errorText(error)}`)
    } finally {
      if (requestRef.current === controller) requestRef.current = null
      if (fullScopeStillCurrent(scope)) setBusy(null)
    }
  }, [fullScopeStillCurrent, language, readBatch])

  return {
    artifact,
    batch,
    candidates,
    busy: Boolean(busy),
    busyAction: busy,
    status,
    selectArtifact,
    uploadFile,
    scan,
    updateCandidate,
    resolveCandidates,
    translateMissing,
  }
}
