import { useCallback } from 'react'
import { api } from '../apiClient'
import { errorText } from '../appText'
import { translationInputMode, translationReadinessUserMessage } from '../domain/translationFlow'
import { languageQuery, languageSpec, normalizeLanguageCode, type LanguageCode } from '../languages'
import type {
  Artifact,
  GlossaryBatch,
  GlossaryCandidate,
  GlossaryPreviewRow,
  GlossaryTerm,
  Project,
  Run,
  TranslationReadiness
} from '../types'

export interface UseGlossaryActionsParams {
  current: Project | undefined
  currentId: string
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  assetArtifacts: Artifact[]
  intro: string
  selectedLanguage: LanguageCode
  isCurrentProject: (projectId?: string | null) => boolean
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setLatestRun: (run: Run | null) => void
  setStep: (step: number) => void
  setBusy: (value: boolean) => void
  setStatus: (message: string) => void
  setStatusForProject: (projectId: string, message: string) => void
  setBusyForProject: (projectId: string, value: boolean) => void
  setGlossaryPreview: (rows: GlossaryPreviewRow[]) => void
  setGlossaryBatches: (batches: GlossaryBatch[]) => void
  setGlossaryCandidates: (candidates: GlossaryCandidate[]) => void
  setQaArtifact: (artifact: Artifact | null) => void
  refreshCurrent: (projectId?: string) => Promise<Project | null>
  refreshProjectSnapshot: (projectId: string) => Promise<Project | null>
  syncLanguageFromArtifact: (artifact: Artifact) => Promise<LanguageCode>
  refreshTranslationReadiness: (artifactId: string, projectId?: string, language?: LanguageCode) => Promise<TranslationReadiness | null>
}

// Glossary/term handlers moved verbatim out of main.tsx's App component.
// `runGlossaryExtract` depends on useTranslationActions' syncLanguageFromArtifact
// and refreshTranslationReadiness (passed in as params); useProjectActions'
// runAnalysis calls back into this hook's runGlossaryExtract via a ref forwarded
// from main.tsx, since useProjectActions is constructed before this hook.
//
// Every returned handler is wrapped in `useCallback` (see useProjectActions.ts
// for why) so the memoized `GlossaryTab`/wide-table components can skip
// re-rendering when their dependencies haven't changed. Declaration order
// matters: `refreshGlossaryBatches` is used by several other functions here
// and is declared first.
export function useGlossaryActions(params: UseGlossaryActionsParams) {
  const {
    current,
    currentId,
    sourceArtifact,
    termArtifact,
    assetArtifacts,
    intro,
    selectedLanguage,
    isCurrentProject,
    setSourceArtifact,
    setTermArtifact,
    setLatestRun,
    setStep,
    setBusy,
    setStatus,
    setStatusForProject,
    setBusyForProject,
    setGlossaryPreview,
    setGlossaryBatches,
    setGlossaryCandidates,
    setQaArtifact,
    refreshCurrent,
    refreshProjectSnapshot,
    syncLanguageFromArtifact,
    refreshTranslationReadiness
  } = params

  const refreshGlossaryBatches = useCallback(async (projectId = currentId) => {
    if (!projectId) return
    const loaded = await api<{ batches: GlossaryBatch[]; active_batch: GlossaryBatch | null; candidates: GlossaryCandidate[] }>(`/api/projects/${projectId}/glossary/batches?${languageQuery(selectedLanguage)}`)
    setGlossaryBatches(loaded.batches || [])
    setGlossaryCandidates(loaded.candidates || [])
  }, [currentId, selectedLanguage, setGlossaryBatches, setGlossaryCandidates])

  const runGlossaryExtract = useCallback(async (inputArtifact?: Artifact | null) => {
    const artifact = inputArtifact || sourceArtifact
    if (!current) return
    if (!artifact) {
      setStatus('请先在「判定输入」步骤选择或上传语言表，再扫描术语候选。')
      return
    }
    if (!sourceArtifact || sourceArtifact.id !== artifact.id) {
      setSourceArtifact(artifact)
    }
    const detectedLanguage = await syncLanguageFromArtifact(artifact)
    const readiness = await refreshTranslationReadiness(artifact.id, current.id, detectedLanguage)
    if (!isCurrentProject(current.id)) return
    const inputMode = translationInputMode(readiness)
    if (inputMode === 'invalid') {
      setStatus(`语言表格式需要修正：${translationReadinessUserMessage(readiness)}`)
      setStep(4)
      return
    }
    if (inputMode === 'ready_for_qa') {
      setQaArtifact(artifact)
      setStep(8)
      setStatus(`这份表已有完整译文：${readiness?.translated_rows || 0}/${readiness?.source_rows || 0} 行。无需扫描术语候选，请直接运行 QA。`)
      return
    }
    const extractionLanguage = normalizeLanguageCode(readiness?.target_language) || detectedLanguage || selectedLanguage
    const extractionLang = languageSpec(extractionLanguage)
    setBusy(true)
    setStatus('正在从待翻译语言表扫描术语候选...')
    try {
      const result = await api<{
        run: Run
        artifacts: Artifact[]
        glossary_backfill?: {
          candidates?: number
          unique_candidates?: number
          inserted?: number
          updated?: number
          skipped_existing?: number
          skipped_duplicate?: number
          conflicts?: number
          pending_confirmation?: number
        }
      }>(`/api/projects/${current.id}/glossary/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: artifact.id,
          project_name: current.name,
          source_only: false,
          id_column: 'ID',
          source_column: 'cn',
          target_column: extractionLang.targetHeader,
          language: extractionLanguage,
          project_material_artifact_ids: assetArtifacts.map((artifact) => artifact.id),
          project_notes: [intro.trim() || current.description || `${current.name} ${current.type}`].filter(Boolean),
          include_empty_final_terms: true,
          ai_candidate_supplement: true
        })
      })
      setTermArtifact(result.artifacts.find((a) => a.kind === 'glossary_final') || null)
      setLatestRun(result.run)
      await refreshCurrent()
      await refreshGlossaryBatches(current.id)
      const backfill = result.glossary_backfill || {}
      const pendingConfirmation = backfill.pending_confirmation ?? backfill.inserted ?? 0
      setStatus(`术语候选已生成：候选 ${backfill.candidates ?? 0}，按中文去重后 ${backfill.unique_candidates ?? 0}，已在库中跳过 ${backfill.skipped_existing ?? 0}，待人工确认 ${pendingConfirmation}，重复跳过 ${backfill.skipped_duplicate ?? 0}`)
    } catch (error) {
      setStatus(`术语提取失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }, [sourceArtifact, current, setStatus, setSourceArtifact, syncLanguageFromArtifact, refreshTranslationReadiness, isCurrentProject, setStep, setQaArtifact, selectedLanguage, setBusy, assetArtifacts, intro, setTermArtifact, setLatestRun, refreshCurrent, refreshGlossaryBatches])

  const previewGlossaryImport = useCallback(async () => {
    if (!current || !termArtifact) return
    setBusy(true)
    setStatus('正在预览术语表...')
    try {
      const result = await api<{ rows: GlossaryPreviewRow[]; languages?: LanguageCode[] }>(`/api/projects/${current.id}/glossary/import-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: termArtifact.id, language: selectedLanguage })
      })
      setGlossaryPreview(result.rows)
      const languageText = result.languages?.length ? `（${result.languages.map((item) => item.toUpperCase()).join('/')}）` : ''
      setStatus(`术语表预览完成：${result.rows.length} 条${languageText}`)
    } catch (error) {
      setStatus(`术语表预览失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }, [current, termArtifact, setBusy, setStatus, selectedLanguage, setGlossaryPreview])

  const importGlossaryArtifact = useCallback(async () => {
    if (!current || !termArtifact) return
    const projectId = current.id
    const artifactId = termArtifact.id
    const language = selectedLanguage
    setBusyForProject(projectId, true)
    setStatusForProject(projectId, '正在导入术语表...')
    try {
      const result = await api<{ imported_count: number; languages?: LanguageCode[] }>(`/api/projects/${projectId}/glossary/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: artifactId, language })
      })
      await refreshProjectSnapshot(projectId)
      const languageText = result.languages?.length ? `（${result.languages.map((item) => languageSpec(item).short).join('/')}）` : ''
      setStatusForProject(projectId, `术语表已导入：${result.imported_count} 条${languageText}`)
    } catch (error) {
      setStatusForProject(projectId, `术语表导入失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }, [current, termArtifact, selectedLanguage, setBusyForProject, setStatusForProject, refreshProjectSnapshot])

  const addGlossaryTerm = useCallback(async (form: FormData) => {
    if (!current) return
    const projectId = current.id
    try {
      await api(`/api/projects/${projectId}/glossary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          term_key: form.get('term_key') || '',
          source: form.get('source'),
          target: form.get('target'),
          target_alt: form.get('target_alt') || '',
          language: form.get('language') || selectedLanguage,
          category: form.get('category') || 'manual',
          note: form.get('note') || '',
          source_type: 'manual',
          confirmed: true
        })
      })
      await refreshProjectSnapshot(projectId)
      setStatusForProject(projectId, '词条已新增')
    } catch (error) {
      setStatusForProject(projectId, `词条新增失败：${errorText(error)}`)
    }
  }, [current, selectedLanguage, refreshProjectSnapshot, setStatusForProject])

  const updateGlossaryTerm = useCallback(async (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => {
    if (!current) return
    const projectId = current.id
    try {
      await api(`/api/projects/${projectId}/glossary/${term.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      })
      await refreshProjectSnapshot(projectId)
      setStatusForProject(projectId, '词条已保存')
    } catch (error) {
      setStatusForProject(projectId, `词条保存失败：${errorText(error)}`)
    }
  }, [current, refreshProjectSnapshot, setStatusForProject])

  const updateGlossaryCandidate = useCallback(async (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => {
    if (!current) return
    try {
      await api(`/api/projects/${current.id}/glossary/candidates/${candidate.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      })
      await refreshGlossaryBatches(current.id)
      setStatus('候选词条已保存')
    } catch (error) {
      setStatus(`候选词条保存失败：${errorText(error)}`)
    }
  }, [current, refreshGlossaryBatches, setStatus])

  const translateMissingGlossaryCandidates = useCallback(async (batchId: string) => {
    if (!current || !batchId) return
    setBusy(true)
    setStatus(`正在补齐缺失 ${languageSpec(selectedLanguage).short} 译文...`)
    try {
      const result = await api<{ translated_count: number; skipped_count: number }>(`/api/projects/${current.id}/glossary/batches/${batchId}/translate-missing`, {
        method: 'POST'
      })
      await refreshGlossaryBatches(current.id)
      setStatus(`候选译文已补齐 ${result.translated_count} 条，跳过已有译文 ${result.skipped_count} 条；请人工审核后加入术语库。`)
    } catch (error) {
      setStatus(`候选译文补齐失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }, [current, setBusy, setStatus, selectedLanguage, refreshGlossaryBatches])

  const resolveGlossaryCandidates = useCallback(async (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => {
    if (!current || !batchId || !candidates.length) return
    const projectId = current.id
    setBusy(true)
    setStatusForProject(projectId, action === 'accept' ? `正在确认加入 ${candidates.length} 条术语...` : `正在跳过 ${candidates.length} 条候选...`)
    try {
      await api(`/api/projects/${projectId}/glossary/batches/${batchId}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_ids: candidates.map((candidate) => candidate.id) })
      })
      await refreshProjectSnapshot(projectId)
      await refreshGlossaryBatches(projectId)
      setStatusForProject(projectId, action === 'accept' ? `已加入 ${candidates.length} 条术语，后续翻译和 QA 会使用项目术语库。` : `已跳过 ${candidates.length} 条候选，不会进入项目术语库。`)
    } catch (error) {
      setStatusForProject(projectId, `术语批次处理失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }, [current, setBusy, setStatusForProject, refreshProjectSnapshot, refreshGlossaryBatches, setBusyForProject])

  const deleteGlossaryTerm = useCallback(async (term: GlossaryTerm) => {
    if (!current) return
    const projectId = current.id
    try {
      await api(`/api/projects/${projectId}/glossary/${term.id}`, { method: 'DELETE' })
      await refreshProjectSnapshot(projectId)
      setStatusForProject(projectId, '词条已删除')
    } catch (error) {
      setStatusForProject(projectId, `词条删除失败：${errorText(error)}`)
    }
  }, [current, refreshProjectSnapshot, setStatusForProject])

  return {
    refreshGlossaryBatches,
    runGlossaryExtract,
    previewGlossaryImport,
    importGlossaryArtifact,
    addGlossaryTerm,
    updateGlossaryTerm,
    updateGlossaryCandidate,
    translateMissingGlossaryCandidates,
    resolveGlossaryCandidates,
    deleteGlossaryTerm
  }
}
