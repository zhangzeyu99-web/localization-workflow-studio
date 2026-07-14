import { useCallback, useRef } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { api } from '../apiClient'
import { errorText } from '../appText'
import { newestArtifact, artifactRole, artifactPickerLabel } from '../domain/artifacts'
import { projectRunStatusText, projectTranslationPassedStatusText } from '../domain/projectActivity'
import {
  canSkipModelTranslation,
  effectiveBatchSize,
  findResumableTranslationRun,
  isTranslationRunResumable,
  matchesTranslationRun,
  translationInputMode,
  translationReadinessUserMessage
} from '../domain/translationFlow'
import { formalTranslationBlockReason } from '../components/translationWizard/translationGuards'
import { translationTaskIdOfRun } from '../domain/translationTaskLifecycle'
import { languageQuery, languageSpec, normalizeLanguageArray, normalizeLanguageCode, type LanguageCode } from '../languages'
import type { ConfirmDialogOptions } from '../components/modals/ConfirmModal'
import { issueCountPhrase } from '../uiText'
import type {
  AppSettings,
  AppView,
  Artifact,
  DeliverableTask,
  DeliveryFile,
  GeneratedDeliveryState,
  GlossaryCandidate,
  MultilingualQueueStatus,
  Project,
  ProjectTab,
  QualityIssue,
  Run,
  TranslationEntry,
  TranslationReadiness,
  TranslationTargets
} from '../types'

export interface UseTranslationActionsParams {
  current: Project | undefined
  currentIdRef: { current: string }
  translationTaskId: string
  translationTaskIdRef: { current: string }
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  qaArtifact: Artifact | null
  archiveArtifact: Artifact | null
  latestRun: Run | null
  translationReadiness: TranslationReadiness | null
  glossaryCandidates: GlossaryCandidate[]
  settings: AppSettings | null
  translationBatchSize: number
  tab: ProjectTab
  selectedLanguage: LanguageCode
  selectedLanguages: LanguageCode[]
  lineProofread: boolean
  currentLang: { short: string }
  isCurrentProject: (projectId?: string | null) => boolean
  isCurrentTranslationTask: (projectId: string, translationTaskId: string) => boolean
  setSourceArtifact: (artifact: Artifact | null) => void
  setQaArtifact: Dispatch<SetStateAction<Artifact | null>>
  setArchiveArtifact: (artifact: Artifact | null) => void
  setTranslationReadiness: (readiness: TranslationReadiness | null) => void
  setSourceInputNotice: (readiness: TranslationReadiness | null) => void
  setInvalidSourceArtifactIds: Dispatch<SetStateAction<string[]>>
  setStep: Dispatch<SetStateAction<number>>
  setBusy: (value: boolean) => void
  setStatus: (message: string) => void
  setStatusForProject: (projectId: string, message: string) => void
  setBusyForProject: (projectId: string, value: boolean) => void
  setQualityIssues: (issues: QualityIssue[]) => void
  setLatestRun: (run: Run | null) => void
  setDeliverables: Dispatch<SetStateAction<DeliverableTask[]>>
  setDeliverablesLoading: (value: boolean) => void
  setDeliverablesError: (message: string) => void
  setGeneratedDelivery: (value: GeneratedDeliveryState | null) => void
  setTab: (tab: ProjectTab) => void
  setView: (view: AppView) => void
  setPrimaryLanguage: (language: LanguageCode) => void
  setPrimaryLanguages: (languages: LanguageCode[], primary?: LanguageCode | null) => void
  confirm: (message: string, options?: ConfirmDialogOptions) => Promise<boolean>
  refreshCurrent: (projectId?: string) => Promise<Project | null>
  loadQualityIssues: (runId: string, projectId?: string, accept?: () => boolean) => Promise<QualityIssue[]>
  upload: (file: File, kind: string, purpose?: string, accept?: () => boolean) => Promise<Artifact | null>
}

// Translation / QA / delivery handlers moved verbatim out of main.tsx's App
// component. Depends on useProjectActions' refreshCurrent/loadQualityIssues/
// upload (passed in as params); useGlossaryActions depends back on this
// hook's syncLanguageFromArtifact/refreshTranslationReadiness.
export function useTranslationActions(params: UseTranslationActionsParams) {
  const {
    current,
    currentIdRef,
    translationTaskId,
    translationTaskIdRef,
    sourceArtifact,
    termArtifact,
    qaArtifact,
    archiveArtifact,
    latestRun,
    translationReadiness,
    glossaryCandidates,
    settings,
    translationBatchSize,
    tab,
    selectedLanguage,
    selectedLanguages,
    lineProofread,
    currentLang,
    isCurrentProject,
    isCurrentTranslationTask,
    setSourceArtifact,
    setQaArtifact,
    setArchiveArtifact,
    setTranslationReadiness,
    setSourceInputNotice,
    setInvalidSourceArtifactIds,
    setStep,
    setBusy,
    setStatus,
    setStatusForProject,
    setBusyForProject,
    setQualityIssues,
    setLatestRun,
    setDeliverables,
    setDeliverablesLoading,
    setDeliverablesError,
    setGeneratedDelivery,
    setTab,
    setView,
    setPrimaryLanguage,
    setPrimaryLanguages,
    confirm,
    refreshCurrent,
    loadQualityIssues,
    upload
  } = params

  // Shared re-entry lock for the formal translation start actions.
  const translateStartingRef = useRef(false)
  const taskStillCurrent = (projectId: string, taskId: string) => (
    isCurrentTranslationTask(projectId, taskId)
    && (!taskId || translationTaskIdRef.current === taskId)
  )

  async function refreshTranslationReadiness(
    artifactId: string,
    projectId = currentIdRef.current,
    language: LanguageCode = selectedLanguage,
    autoCorrectLanguage = true,
    taskId = translationTaskId,
  ) {
    const batchSize = effectiveBatchSize(settings, translationBatchSize)
    try {
      const result = await api<TranslationReadiness>(`/api/projects/${projectId}/artifacts/${artifactId}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      if (
        autoCorrectLanguage &&
        taskStillCurrent(projectId, taskId) &&
        result.reason === 'target_column_missing' &&
        result.format_errors?.includes('target_column_missing')
      ) {
        const targets = await inspectTranslationTargets(artifactId, projectId, taskId)
        if (!taskStillCurrent(projectId, taskId)) return result
        const suggested = targets?.suggested_language
        if (suggested && suggested !== language) {
          setPrimaryLanguages(targets.detected_languages?.length ? targets.detected_languages : [suggested], suggested)
          const corrected = await api<TranslationReadiness>(`/api/projects/${projectId}/artifacts/${artifactId}/translation-readiness?batch_size=${batchSize}&${languageQuery(suggested)}`)
          if (taskStillCurrent(projectId, taskId)) setTranslationReadiness(corrected)
          return corrected
        }
      }
      if (taskStillCurrent(projectId, taskId)) setTranslationReadiness(result)
      return result
    } catch (error) {
      // Without feedback the step keeps showing "正在检查" forever; surface the
      // failure so the user knows to re-select the file or retry.
      if (taskStillCurrent(projectId, taskId)) {
        setTranslationReadiness(null)
        setStatusForProject(projectId, `语言表检查失败：${errorText(error)}，请重新选择文件或稍后重试。`)
      }
      return null
    }
  }

  function selectSourceArtifact(artifact: Artifact | null) {
    if (!artifact) {
      setSourceArtifact(null)
      setSourceInputNotice(null)
      setTranslationReadiness(null)
      return
    }
    if (artifactRole(artifact) === 'language_source') {
      setSourceArtifact(artifact)
      setSourceInputNotice(null)
      void classifySourceArtifact(artifact)
    } else {
      setSourceArtifact(artifact)
    }
  }

  function selectQaArtifact(artifact: Artifact | null) {
    setQaArtifact(artifact)
    if (artifact && artifactRole(artifact) === 'language_source') {
      void refreshTranslationReadiness(artifact.id)
    }
  }

  async function syncLanguageFromArtifact(artifact: Artifact): Promise<LanguageCode> {
    const projectId = currentIdRef.current
    const taskId = translationTaskId
    const targets = await inspectTranslationTargets(artifact.id, projectId, taskId)
    if (!taskStillCurrent(projectId, taskId)) return selectedLanguage
    const suggested = targets?.suggested_language
    const detected = targets?.detected_languages || []
    if (detected.length) {
      setPrimaryLanguages(detected, suggested || detected[0])
      setStatus(`已识别语言表目标语言：${detected.map((item) => languageSpec(item).short).join(' / ')}`)
      return suggested || detected[0]
    }
    if (suggested && suggested !== selectedLanguage) {
      setPrimaryLanguage(suggested)
      setStatus(`已识别语言表目标语言：${languageSpec(suggested).short}`)
      return suggested
    }
    return suggested || selectedLanguage
  }

  async function classifySourceArtifact(artifact: Artifact) {
    const projectId = currentIdRef.current
    const taskId = translationTaskId
    const language = await syncLanguageFromArtifact(artifact)
    if (!taskStillCurrent(projectId, taskId)) return
    const readiness = await refreshTranslationReadiness(artifact.id, projectId, language, true, taskId)
    if (!taskStillCurrent(projectId, taskId) || !readiness) return
    const mode = translationInputMode(readiness)
    if (mode === 'invalid') {
      setInvalidSourceArtifactIds((prev) => prev.includes(artifact.id) ? prev : [...prev, artifact.id])
      setSourceInputNotice(readiness)
      setTranslationReadiness(readiness)
      setSourceArtifact(null)
      setStatus(`语言表格式需要修正：${translationReadinessUserMessage(readiness)}`)
      return
    }
    setInvalidSourceArtifactIds((prev) => prev.filter((id) => id !== artifact.id))
    setSourceArtifact(artifact)
    setSourceInputNotice(null)
    if (mode === 'ready_for_qa') {
      setQaArtifact(artifact)
      setStatus(`检测到已有完整译文：${readiness.translated_rows}/${readiness.source_rows} 行，可直接进入校对。`)
    } else {
      setQaArtifact((currentQa) => currentQa && artifactRole(currentQa) === 'language_source' ? null : currentQa)
      setStatus(`检测到待翻译语言表：${readiness.source_rows} 行，下一步扫描术语候选。`)
    }
  }

  async function inspectTranslationTargets(artifactId: string, projectId = currentIdRef.current, taskId = translationTaskId): Promise<TranslationTargets | null> {
    try {
      const result = await api<TranslationTargets>(`/api/projects/${projectId}/artifacts/${artifactId}/translation-targets`)
      const languages = normalizeLanguageArray(result.detected_languages)
      return { ...result, detected_languages: languages, suggested_language: normalizeLanguageCode(result.suggested_language) }
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatus(`语言识别失败：${errorText(error)}`)
      return null
    }
  }

  async function startQuickTask(payload: { inputArtifact: Artifact; referenceArtifacts: Artifact[]; objective: 'translate' | 'qa'; language: LanguageCode }): Promise<Run | null> {
    if (!current) return null
    const projectId = current.id
    const { inputArtifact, referenceArtifacts, objective, language } = payload
    const referenceArtifactIds = referenceArtifacts.map((artifact) => artifact.id)
    const batchSize = effectiveBatchSize(settings, translationBatchSize)
    setBusy(true)
    setStatusForProject(projectId, objective === 'qa' ? `快速校对准备中：${languageSpec(language).short}` : `快速翻译准备中：${languageSpec(language).short}`)
    try {
      const inputName = `${inputArtifact.label || ''} ${inputArtifact.path || ''}`.toLowerCase()
      if (objective === 'qa' && /\.(txt|md|markdown)(\s|$)/i.test(inputName)) {
        setStatusForProject(projectId, 'TXT 快速任务目前支持翻译并输出同格式文本；校对请上传已译语言表。')
        return null
      }
      if (objective === 'qa') {
        const run = await api<Run>('/api/runs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: current.id,
            kind: 'qa',
            language,
            input_artifact_id: inputArtifact.id,
            term_artifact_id: termArtifact?.id || null,
            reference_artifact_ids: referenceArtifactIds,
            task_origin: 'quick_task',
            task_code: 'QA'
          })
        })
        // QA runs as a background job (same lease as translation); the quick
        // task panel and the 2s run poller follow the run to its terminal state.
        const started = await api<Run>(`/api/runs/${run.id}/qa/start`, { method: 'POST' })
        if (!isCurrentProject(projectId)) return started
        setLatestRun(started)
        setStatusForProject(projectId, `快速校对已进入后台：${languageSpec(language).short} · 正在检查变量、标签、术语、中文残留和格式问题。`)
        return started
      }

      const readiness = await api<TranslationReadiness>(`/api/projects/${projectId}/artifacts/${inputArtifact.id}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      if (!isCurrentProject(projectId)) return null
      if (canSkipModelTranslation(readiness)) {
        setStatusForProject(projectId, `已检测到 ${readiness.translated_rows}/${readiness.source_rows} 行已有译文；建议切换为“校对”直接跑 QA。`)
        return null
      }
      const blockReason = formalTranslationBlockReason(settings, inputArtifact, current, readiness)
      if (blockReason) {
        setStatusForProject(projectId, `无法开始快速翻译：${blockReason}`)
        return null
      }
      const resumableRun = (current.runs || []).find((run) =>
        matchesTranslationRun(run, language, inputArtifact.id, 'quick_task')
        && isTranslationRunResumable(run)
      ) || null
      const run = resumableRun || await api<Run>('/api/runs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: current.id,
            kind: 'translation',
            language,
            input_artifact_id: inputArtifact.id,
            term_artifact_id: termArtifact?.id || null,
            reference_artifact_ids: referenceArtifactIds,
            batch_size: batchSize,
            task_origin: 'quick_task',
            task_code: 'T'
          })
        })
      if (!isCurrentProject(projectId)) return null
      setLatestRun(run)
      const endpoint = resumableRun ? 'resume' : 'start'
      const started = await api<Run>(`/api/runs/${run.id}/translate/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_size: batchSize })
      })
      if (!isCurrentProject(projectId)) return null
      setLatestRun(started)
      if (started.status === 'passed') {
        const resultArtifact = newestArtifact(started.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook', 'final_text'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
        setStatusForProject(projectId, `快速翻译已完成并通过 QA：${languageSpec(language).short}。可到交付页下载。`)
        return started
      }
      if (started.status === 'failed') {
        const resultArtifact = newestArtifact(started.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook', 'final_text'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
        setStatusForProject(projectId, `快速翻译已完成，但 QA 未通过：${projectRunStatusText(started)}。请到校对页修复；时间受限时可生成带问题摘要的交付。`)
        return started
      }
      setStatusForProject(projectId, resumableRun
        ? `快速翻译已继续：${languageSpec(language).short} · 会从已保存批次接着跑。`
        : `快速翻译已进入后台：${languageSpec(language).short} · ${readiness.source_rows} 行 · 预计 ${readiness.estimated_batches || '-'} 批。`)
      return started
    } catch (error) {
      setStatusForProject(projectId, `快速任务失败：${errorText(error)}`)
      return null
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  function selectedQueueLanguages() {
    const languages = selectedLanguages.length ? selectedLanguages : [selectedLanguage]
    return languages.filter((language, index) => languages.indexOf(language) === index)
  }

  async function confirmTermGapBeforeTranslate(language: LanguageCode): Promise<boolean> {
    if (!current || termArtifact) return true
    const confirmedTerms = (current.glossary || []).filter((term) => term.language === language && String(term.target || '').trim()).length
    const readyCandidates = glossaryCandidates.filter((item) =>
      item.status === 'pending' &&
      (item.language || language) === language &&
      String(item.target || '').trim()
    ).length
    if (confirmedTerms > 0 || readyCandidates === 0) return true
    const shouldContinue = await confirm(
      `检测到 ${languageSpec(language).short} 有 ${readyCandidates} 条候选术语尚未加入项目术语库。\n\n` +
      '这些候选术语默认不会参与本次翻译，可能导致译文不按术语表执行。\n\n' +
      '建议返回「术语候选」步骤先确认术语。仍要继续无术语翻译吗？',
      { title: '有未确认的候选术语', confirmLabel: '继续翻译', cancelLabel: '先去确认术语', tone: 'warn' }
    )
    if (!shouldContinue) {
      setStep(5)
      setStatusForProject(current.id, '已暂停翻译：请先在「术语候选」步骤确认候选术语，再启动 AI 翻译。')
    }
    return shouldContinue
  }

  async function confirmTermGapForLanguages(languages: LanguageCode[]): Promise<boolean> {
    for (const language of languages) {
      if (!(await confirmTermGapBeforeTranslate(language))) return false
    }
    return true
  }

  async function runTranslate(taskCode: 'A' | 'T' = 'T') {
    if (!current || !sourceArtifact) return
    // Re-entry lock: the global busy flag is only set after async pre-checks
    // (readiness refresh, term-gap confirm), leaving a double-click window.
    if (translateStartingRef.current) return
    translateStartingRef.current = true
    try {
      await runTranslateInner(taskCode)
    } finally {
      translateStartingRef.current = false
    }
  }

  async function runTranslateInner(taskCode: 'A' | 'T') {
    if (!current || !sourceArtifact) return
    const projectId = current.id
    const taskId = translationTaskId
    const selectedBatchSize = effectiveBatchSize(settings, translationBatchSize)
    const readiness = translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === selectedBatchSize
      ? translationReadiness
      : await refreshTranslationReadiness(sourceArtifact.id, projectId)
    if (!taskStillCurrent(projectId, taskId)) return
    if (readiness && canSkipModelTranslation(readiness)) {
      setQaArtifact(sourceArtifact)
      setStep(8)
      setStatus(`已检测到 ${readiness.translated_rows}/${readiness.source_rows} 行已有译文，无需 AI 翻译，请直接运行 QA。`)
      return
    }
    const blockReason = formalTranslationBlockReason(settings, sourceArtifact, current, readiness)
    if (blockReason) {
      setStatus(`无法开始翻译：${blockReason}`)
      return
    }
    const confirmedTermGap = await confirmTermGapBeforeTranslate(selectedLanguage)
    if (!confirmedTermGap || !taskStillCurrent(projectId, taskId)) return
    setBusy(true)
    setStatusForProject(projectId, `${currentLang.short} 翻译前检查通过，准备分批翻译：${readiness?.source_rows || 0} 行，预计 ${readiness?.estimated_batches || '-'} 批。`)
    try {
      const batchSize = selectedBatchSize
      const latestRunMatches = latestRun && matchesTranslationRun(latestRun, selectedLanguage, sourceArtifact.id, 'translation_run', taskId)
        ? latestRun
        : null
      const resumableRun = latestRunMatches && isTranslationRunResumable(latestRunMatches)
        ? latestRunMatches
        : findResumableTranslationRun(current, selectedLanguage, sourceArtifact.id, 'translation_run', taskId)
      const run = resumableRun || await api<Run>('/api/runs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: current.id,
            kind: 'translation',
            language: selectedLanguage,
            input_artifact_id: sourceArtifact.id,
            term_artifact_id: termArtifact?.id || null,
            batch_size: batchSize,
            task_code: taskCode,
            translation_task_id: taskId || null,
          })
        })
      if (!taskStillCurrent(projectId, taskId)) return
      setLatestRun(run)
      const needsBudgetConfirm = run.metadata?.reason === 'api_budget_confirmation_required'
      const confirmedBudget = needsBudgetConfirm
        ? await confirm('该任务预计 API token 用量超过设置的提醒阈值。确认后会从已完成批次继续，不会重跑已落盘批次。是否继续？', {
            title: 'API 用量确认',
            confirmLabel: '继续翻译',
            cancelLabel: '暂不继续'
          })
        : false
      if (!taskStillCurrent(projectId, taskId)) return
      if (needsBudgetConfirm && !confirmedBudget) {
        setStatusForProject(projectId, '已暂停：等待确认 API 用量预算后继续。')
        return
      }
      const endpoint = resumableRun ? 'resume' : 'start'
      const started = await api<Run>(`/api/runs/${run.id}/translate/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_size: batchSize, confirm_api_budget: confirmedBudget, confirm_term_gap: confirmedTermGap, large_text_mode: 'auto', enable_line_proofread: lineProofread })
      })
      if (!taskStillCurrent(projectId, taskId)) return
      setLatestRun(started)
      if (started.status === 'needs_input' && ['glossary_candidates_not_confirmed', 'selected_term_artifact_empty'].includes(String(started.metadata?.reason || ''))) {
        setStep(5)
        setStatusForProject(projectId, String(started.metadata?.user_message || '术语未正确进入翻译包，已暂停翻译；请先检查术语表或确认候选术语。'))
        return
      }
      if (started.status === 'passed') {
        const resultArtifact = newestArtifact(started.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        setStep((prev) => (prev < 8 ? 8 : prev))
        setStatusForProject(projectId, projectTranslationPassedStatusText(started, selectedLanguage))
        await refreshCurrent()
        if (!taskStillCurrent(projectId, taskId)) return
        if (tab === 'delivery') await refreshDeliverables()
        return
      }
      if (started.status === 'failed') {
        const resultArtifact = newestArtifact(started.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        setStep((prev) => (prev < 8 ? 8 : prev))
        setStatusForProject(projectId, `翻译已完成，但 QA 未通过：${projectRunStatusText(started)}。请进入「QA 校对」步骤查看问题并修复；时间受限时可生成带问题摘要的交付。`)
        await refreshCurrent()
        if (!taskStillCurrent(projectId, taskId)) return
        if (tab === 'delivery') await refreshDeliverables()
        return
      }
      setStatusForProject(projectId, `${currentLang.short} 翻译已进入后台队列：系统会自动拆批、限流、落盘和续跑。`)
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `翻译失败：${errorText(error)}`)
    } finally {
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  async function startMultilingualTranslationQueue(taskCode: 'A' | 'T' = 'T') {
    if (!current || !sourceArtifact) return
    if (translateStartingRef.current) return
    translateStartingRef.current = true
    try {
      await startMultilingualTranslationQueueInner(taskCode)
    } finally {
      translateStartingRef.current = false
    }
  }

  async function startMultilingualTranslationQueueInner(taskCode: 'A' | 'T') {
    if (!current || !sourceArtifact) return
    const projectId = current.id
    const taskId = translationTaskId
    const languages = selectedQueueLanguages()
    const selectedBatchSize = effectiveBatchSize(settings, translationBatchSize)
    const readiness = translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === selectedBatchSize
      ? translationReadiness
      : await refreshTranslationReadiness(sourceArtifact.id, projectId)
    if (!taskStillCurrent(projectId, taskId)) return
    const blockReason = formalTranslationBlockReason(settings, sourceArtifact, current, readiness)
    if (blockReason) {
      setStatusForProject(projectId, `无法开始多语言翻译：${blockReason}`)
      return
    }
    setBusyForProject(projectId, true)
    setStatusForProject(projectId, `正在启动多语言翻译队列：${languages.map((language) => languageSpec(language).short).join(' / ')}`)
    try {
      const confirmedTermGap = await confirmTermGapForLanguages(languages)
      if (!confirmedTermGap || !taskStillCurrent(projectId, taskId)) return
      const result = await api<MultilingualQueueStatus>(`/api/projects/${current.id}/multilingual/translate/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: sourceArtifact.id,
          languages,
          batch_size: selectedBatchSize,
          task_code: taskCode,
          term_artifact_id: termArtifact?.id || null,
          confirm_api_budget: false,
          confirm_term_gap: confirmedTermGap,
          large_text_mode: 'auto',
          enable_line_proofread: lineProofread,
          translation_task_id: taskId || null,
        })
      })
      if (!taskStillCurrent(projectId, taskId)) return
      const firstRunId = result.languages.find((item) => item.translation_run_id || item.run_id)?.translation_run_id || result.languages.find((item) => item.run_id)?.run_id
      if (firstRunId) {
        const run = await api<Run>(`/api/runs/${firstRunId}`)
        if (taskStillCurrent(projectId, taskId)) setLatestRun(run)
      }
      await refreshCurrent()
      if (!taskStillCurrent(projectId, taskId)) return
      setStatusForProject(projectId, `多语言翻译队列已启动：${result.languages.map((item) => item.visible_language).join(' / ')}`)
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `多语言翻译启动失败：${errorText(error)}`)
    } finally {
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  async function cancelTranslateRun(target?: Run | null) {
    // The pause button in StepTranslate is rendered for the run the user is
    // looking at (currentTranslationRun), which in multilingual queues can be
    // a different run from latestRun — cancel the one the user sees.
    const run = target && target.kind === 'translation' ? target : latestRun && latestRun.kind === 'translation' ? latestRun : null
    if (!run) return
    const projectId = run.project_id
    const taskId = translationTaskIdOfRun(run) || translationTaskId
    setBusy(true)
    setStatus('正在取消后台翻译任务...')
    try {
      const canceled = await api<Run>(`/api/runs/${run.id}/translate/cancel`, { method: 'POST' })
      if (!taskStillCurrent(projectId, taskId)) return
      setLatestRun(canceled)
      setStatus('已请求取消：当前已完成批次会保留，后续可继续。')
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `取消翻译失败：${errorText(error)}`)
    } finally {
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  async function runDirectQA(taskCode: 'QA' = 'QA', overrideArtifact?: Artifact | null) {
    const inputQaArtifact = overrideArtifact || qaArtifact
    if (!current || !inputQaArtifact) return
    const projectId = current.id
    const taskId = translationTaskId
    if (artifactRole(inputQaArtifact) === 'language_source') {
      const readiness = await refreshTranslationReadiness(inputQaArtifact.id, projectId)
      if (!taskStillCurrent(projectId, taskId)) return
      if (!canSkipModelTranslation(readiness)) {
        setSourceArtifact(inputQaArtifact)
        setStep(7)
        setStatusForProject(projectId, '这份语言表还不像完整译文表：请先进入 AI 翻译补齐空译文或明显非目标语言内容，再运行 QA。')
        return
      }
    }
    const sourceRunId = inputQaArtifact.run_id && (current.runs || []).some((run) => run.id === inputQaArtifact.run_id && run.kind === 'translation')
      ? inputQaArtifact.run_id
      : null
    if (overrideArtifact) setQaArtifact(overrideArtifact)
    setBusy(true)
    setStatusForProject(projectId, '正在对已有译文表格执行 QA...')
    try {
      const run = await api<Run>('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: current.id,
          kind: 'qa',
          language: selectedLanguage,
          input_artifact_id: inputQaArtifact.id,
          term_artifact_id: termArtifact?.id || null,
          task_origin: sourceRunId ? 'translation_continuation' : 'direct_import',
          source_run_id: sourceRunId,
          task_code: taskCode,
          translation_task_id: taskId || null,
        })
      })
      if (!taskStillCurrent(projectId, taskId)) return
      setQualityIssues([])
      // QA runs as a background job so the UI stays responsive and the task
      // can be canceled; the 2s run poller reports the result when it lands.
      const started = await api<Run>(`/api/runs/${run.id}/qa/start`, { method: 'POST' })
      if (!taskStillCurrent(projectId, taskId)) return
      setLatestRun(started)
      setStatusForProject(projectId, 'QA 已进入后台：正在检查变量、标签、术语、中文残留和格式问题，完成后本页会自动更新。')
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `已有译文 QA 失败：${errorText(error)}`)
    } finally {
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  async function cancelQaRun(target?: Run | null) {
    const run = target && target.kind === 'qa' ? target : latestRun && latestRun.kind === 'qa' ? latestRun : null
    if (!run) return
    const projectId = run.project_id
    const taskId = translationTaskIdOfRun(run) || translationTaskId
    setBusy(true)
    setStatus('正在取消 QA 任务...')
    try {
      const updated = await api<Run>(`/api/runs/${run.id}/qa/cancel`, { method: 'POST' })
      if (!taskStillCurrent(projectId, taskId)) return
      setLatestRun(updated)
      setStatus('已请求取消 QA：会在当前检查阶段结束后停止，不会写入部分结果。')
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `取消 QA 失败：${errorText(error)}`)
    } finally {
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  async function startMultilingualQAQueue(taskCode: 'QA' = 'QA') {
    if (!current) return
    const projectId = current.id
    const taskId = translationTaskId
    const inputArtifact = sourceArtifact || qaArtifact
    if (!inputArtifact) {
      setStatusForProject(projectId, '请先选择语言表或已译表格，再运行多语言 QA。')
      return
    }
    const languages = selectedQueueLanguages()
    setBusyForProject(projectId, true)
    setStatusForProject(projectId, `正在启动多语言 QA 队列：${languages.map((language) => languageSpec(language).short).join(' / ')}`)
    try {
      const result = await api<MultilingualQueueStatus>(`/api/projects/${current.id}/multilingual/qa/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: inputArtifact.id,
          languages,
          task_code: taskCode,
          term_artifact_id: termArtifact?.id || null,
          translation_task_id: taskId || null,
        })
      })
      if (!taskStillCurrent(projectId, taskId)) return
      const firstRunId = result.languages.find((item) => item.qa_run_id || item.run_id)?.qa_run_id || result.languages.find((item) => item.run_id)?.run_id
      if (firstRunId) {
        const run = await api<Run>(`/api/runs/${firstRunId}`)
        if (taskStillCurrent(projectId, taskId)) setLatestRun(run)
      }
      await refreshCurrent()
      if (!taskStillCurrent(projectId, taskId)) return
      if (tab === 'delivery') await refreshDeliverables()
      setStatusForProject(projectId, `多语言 QA 队列已启动：${result.languages.map((item) => item.visible_language).join(' / ')}`)
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `多语言 QA 启动失败：${errorText(error)}`)
    } finally {
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  async function applyManualFixes(fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) {
    if (!current || !latestRun || !fixes.length) return
    const projectId = current.id
    const taskId = translationTaskIdOfRun(latestRun) || translationTaskId
    setBusy(true)
    setStatusForProject(projectId, '正在保存手工修复...')
    try {
      // Fixes are applied synchronously (fast); the QA rerun happens as a
      // background job so a large workbook doesn't lock the page for minutes.
      const result = await api<{
        fixed_artifact: Artifact
        manual_fixes: Record<string, unknown>[]
        qa_run?: Run | null
      }>(`/api/runs/${latestRun.id}/manual-fixes/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fixes, rerun_qa: true })
      })
      if (!taskStillCurrent(projectId, taskId)) return
      if (result.qa_run) {
        setLatestRun(result.qa_run)
        setQualityIssues([])
        setStatusForProject(projectId, `手工修复已保存 ${result.manual_fixes.length} 处，重新 QA 已进入后台，完成后本页会自动更新。`)
      } else {
        setQaArtifact(result.fixed_artifact)
        setStatusForProject(projectId, '手工修复已保存，等待重新 QA')
      }
      await refreshCurrent()
      if (!taskStillCurrent(projectId, taskId)) return
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `手工修复失败：${errorText(error)}`)
    } finally {
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  async function applyModelFixes() {
    if (!current || !latestRun) return
    const projectId = current.id
    const taskId = translationTaskIdOfRun(latestRun) || translationTaskId
    setBusy(true)
    setStatusForProject(projectId, '正在启动模型修复后台任务...')
    try {
      const run = await api<Run>(`/api/runs/${latestRun.id}/model-fixes/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_issues: 80, rerun_qa: true })
      })
      if (!taskStillCurrent(projectId, taskId)) return
      const resultRunId = String(run.metadata?.model_fix_result_run_id || '')
      if (resultRunId && run.metadata?.model_fix_status !== 'running') {
        const resultRun = await api<Run>(`/api/runs/${resultRunId}`)
        if (!taskStillCurrent(projectId, taskId)) return
        setLatestRun(resultRun)
        if (resultRun.status === 'passed') {
          setQualityIssues([])
          setStatusForProject(projectId, '模型修复并重跑 QA 已通过，可进入交付。')
        } else {
          const issues = await loadQualityIssues(resultRun.id, projectId, () => taskStillCurrent(projectId, taskId))
          if (!taskStillCurrent(projectId, taskId)) return
          const hardCount = issues.filter((issue) => issue.severity === 'hard').length
          setStatusForProject(projectId, `模型修复已完成，但 QA 仍有${issueCountPhrase(hardCount || issues.length)}问题。请继续修复；时间受限时可生成带问题摘要的交付。`)
        }
      } else {
        setLatestRun(run)
        setStatusForProject(projectId, '模型修复已进入后台：系统会修复可定位问题并自动重跑 QA，完成后会更新本页状态。')
      }
      await refreshCurrent()
      if (!taskStillCurrent(projectId, taskId)) return
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `模型修复失败：${errorText(error)}`)
    } finally {
      // Kickoff done — release the interactive lock. The background job's
      // progress is tracked through the run poller, not the global busy flag.
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  async function uploadSourceWorkbook(file: File) {
    if (!current) return null
    const projectId = current.id
    const taskId = translationTaskId
    const uploadStillCurrent = () => taskStillCurrent(projectId, taskId)
    const artifact = await upload(file, 'language_table', '', uploadStillCurrent)
    if (artifact && uploadStillCurrent()) await classifySourceArtifact(artifact)
    return artifact
  }

  const addTranslationEntry = useCallback(async (form: FormData) => {
    if (!current) return
    await api(`/api/projects/${current.id}/translations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        entry_key: String(form.get('entry_key') || ''),
        source: String(form.get('source') || ''),
        target: String(form.get('target') || ''),
        target_alt: String(form.get('target_alt') || ''),
        language: form.get('language') || selectedLanguage,
        note: String(form.get('note') || ''),
        source_type: 'manual'
      })
    })
    await refreshCurrent()
    setStatus('译文条目已保存')
  }, [current, selectedLanguage, refreshCurrent, setStatus])

  const updateTranslationEntry = useCallback(async (entry: TranslationEntry, updates: Partial<TranslationEntry>) => {
    if (!current) return
    await api(`/api/projects/${current.id}/translations/${entry.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshCurrent()
    setStatus('译文条目已保存')
  }, [current, refreshCurrent, setStatus])

  const deleteTranslationEntry = useCallback(async (entry: TranslationEntry) => {
    if (!current) return
    await api(`/api/projects/${current.id}/translations/${entry.id}`, { method: 'DELETE' })
    await refreshCurrent()
    setStatus('译文条目已删除')
  }, [current, refreshCurrent, setStatus])

  const uploadArchiveWorkbook = useCallback(async (file: File) => {
    const artifact = await upload(file, 'final_workbook')
    if (artifact) setArchiveArtifact(artifact)
    return artifact
  }, [upload, setArchiveArtifact])

  const importTranslationArchive = useCallback(async (artifactOverride?: Artifact | null): Promise<boolean> => {
    const targetArtifact = artifactOverride || archiveArtifact
    if (!current || !targetArtifact) return false
    setBusy(true)
    setStatus('正在导入译文归档...')
    try {
      const result = await api<{ imported_count: number; languages?: LanguageCode[] }>(`/api/projects/${current.id}/translations/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: targetArtifact.id, auto_languages: true, language: selectedLanguage })
      })
      await refreshCurrent()
      const languageText = result.languages?.length ? `（${result.languages.map((item) => languageSpec(item).short).join('/')}）` : ''
      setStatus(`译文归档已导入：${result.imported_count} 条${languageText}`)
      return true
    } catch (error) {
      setStatus(`译文归档导入失败：${errorText(error)}`)
      return false
    } finally {
      setBusy(false)
    }
  }, [archiveArtifact, current, setBusy, setStatus, selectedLanguage, refreshCurrent])

  async function skipQAArchive(artifactOverride?: Artifact | null) {
    const targetArtifact = artifactOverride || qaArtifact
    if (!current || !targetArtifact) {
      setStatus('请选择已有译文语言表后再跳过 QA。')
      return
    }
    const imported = await importTranslationArchive(targetArtifact)
    if (imported) {
      setStatus('已跳过 QA 并导入译文归档；建议后续补跑 QA。')
      await refreshCurrent()
    }
  }

  async function uploadTranslationWorkbook(file: File) {
    if (!current) return
    const projectId = current.id
    const taskId = translationTaskId
    const uploadStillCurrent = () => taskStillCurrent(projectId, taskId)
    const artifact = await upload(file, 'final_workbook', '', uploadStillCurrent)
    if (artifact && uploadStillCurrent()) {
      setQaArtifact(artifact)
      setStatus(`已有译文已登记：${artifactPickerLabel(artifact)}`)
    }
  }

  async function refreshDeliverables(projectId = currentIdRef.current) {
    if (!projectId) {
      setDeliverables([])
      setDeliverablesLoading(false)
      setDeliverablesError('')
      return
    }
    if (isCurrentProject(projectId)) {
      setDeliverablesLoading(true)
      setDeliverablesError('')
    }
    try {
      const result = await api<{ deliverables: DeliverableTask[] }>(`/api/projects/${projectId}/deliverables`)
      if (isCurrentProject(projectId)) setDeliverables(result.deliverables || [])
    } catch (error) {
      if (isCurrentProject(projectId)) setDeliverablesError(`交付列表加载失败：${errorText(error)}`)
    } finally {
      if (isCurrentProject(projectId)) setDeliverablesLoading(false)
    }
  }

  async function loadDeliverables(projectId: string): Promise<DeliverableTask[]> {
    const result = await api<{ deliverables: DeliverableTask[] }>(`/api/projects/${projectId}/deliverables`)
    return result.deliverables || []
  }

  function mergeGeneratedDeliveryTask(tasks: DeliverableTask[], generated?: DeliverableTask | null): DeliverableTask[] {
    if (!generated) return tasks
    const next = tasks.filter((task) => task.run_id !== generated.run_id)
    return [generated, ...next]
  }

  async function createDeliveryPackage(runId: string): Promise<DeliveryFile[] | null> {
    if (!current) return null
    const projectId = current.id
    const requestTaskId = translationTaskId
    const targetRun = [latestRun, ...(current.runs || [])].find((run) => run?.id === runId) || null
    const targetTaskId = translationTaskIdOfRun(targetRun)
    setBusy(true)
    setStatus('正在生成最终交付文件...')
    try {
      const result = await api<{ files: DeliveryFile[]; deliverable?: DeliverableTask }>(`/api/projects/${projectId}/delivery-package?run_id=${encodeURIComponent(runId)}`, { method: 'POST' })
      const files = result.files || []
      const generatedTask = result.deliverable || null
      if (taskStillCurrent(projectId, requestTaskId)) {
        setGeneratedDelivery({ projectId, runId, translationTaskId: generatedTask?.translation_task_id || targetTaskId || undefined, files })
        try {
          const refreshed = await loadDeliverables(projectId)
          setDeliverables(mergeGeneratedDeliveryTask(refreshed, generatedTask))
        } catch {
          setDeliverables((previous) => mergeGeneratedDeliveryTask(previous, generatedTask))
        }
      }
      await refreshCurrent(projectId)
      if (!taskStillCurrent(projectId, requestTaskId)) return files
      setStatus(`最终交付已生成：${files.length} 个文件`)
      return files
    } catch (error) {
      if (taskStillCurrent(projectId, requestTaskId)) setStatus(`最终交付生成失败：${errorText(error)}`)
      return null
    } finally {
      if (taskStillCurrent(projectId, requestTaskId)) setBusy(false)
    }
  }

  async function finishWizardDelivery(): Promise<boolean> {
    if (!current) return false
    const projectId = current.id
    const taskId = translationTaskId
    await refreshDeliverables(projectId)
    if (!taskStillCurrent(projectId, taskId)) return false
    await refreshCurrent(projectId)
    if (!taskStillCurrent(projectId, taskId)) return false
    setTab('delivery')
    setView('overview')
    setStatus('交付已完成，可在项目概览的“交付”页下载最新文件。')
    return true
  }

  async function createMergedDeliveryPackage(): Promise<DeliveryFile[] | null> {
    if (!current || !sourceArtifact) return null
    const projectId = current.id
    const taskId = translationTaskId
    const languages = selectedQueueLanguages()
    const deliveryRunId = latestRun?.id || (current.runs || []).find((run) => (
      ['translation', 'qa'].includes(run.kind)
      && (!taskId || translationTaskIdOfRun(run) === taskId)
    ))?.id || ''
    setBusyForProject(projectId, true)
    setStatusForProject(projectId, `正在生成多语言合并交付：${languages.map((language) => languageSpec(language).short).join(' / ')}`)
    try {
      const result = await api<{ files: DeliveryFile[]; merged_languages?: string[]; skipped_languages?: string[]; language_results?: GeneratedDeliveryState['languageResults']; deliverable?: DeliverableTask }>(`/api/projects/${current.id}/delivery-package/merged`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: sourceArtifact.id,
          languages,
          translation_task_id: taskId || null,
        })
      })
      if (!taskStillCurrent(projectId, taskId)) return null
      setGeneratedDelivery({
        projectId,
        runId: result.deliverable?.run_id || deliveryRunId || `merged:${sourceArtifact.id}`,
        sourceArtifactId: sourceArtifact.id,
        translationTaskId: result.deliverable?.translation_task_id || taskId || undefined,
        files: result.files || [],
        mergedLanguages: result.merged_languages || [],
        skippedLanguages: result.skipped_languages || [],
        languageResults: result.language_results || [],
      })
      await refreshDeliverables()
      if (!taskStillCurrent(projectId, taskId)) return result.files || []
      await refreshCurrent()
      if (!taskStillCurrent(projectId, taskId)) return result.files || []
      const skipped = result.skipped_languages?.length ? `，未合并：${result.skipped_languages.join(' / ')}` : ''
      setStatusForProject(projectId, `多语言合并交付已生成：${result.files.length} 个文件${skipped}`)
      return result.files || []
    } catch (error) {
      if (taskStillCurrent(projectId, taskId)) setStatusForProject(projectId, `多语言合并交付失败：${errorText(error)}`)
      return null
    } finally {
      if (taskStillCurrent(projectId, taskId)) setBusyForProject(projectId, false)
    }
  }

  return {
    refreshTranslationReadiness,
    selectSourceArtifact,
    selectQaArtifact,
    syncLanguageFromArtifact,
    classifySourceArtifact,
    inspectTranslationTargets,
    startQuickTask,
    runTranslate,
    startMultilingualTranslationQueue,
    cancelTranslateRun,
    runDirectQA,
    cancelQaRun,
    startMultilingualQAQueue,
    applyManualFixes,
    applyModelFixes,
    uploadSourceWorkbook,
    uploadArchiveWorkbook,
    uploadTranslationWorkbook,
    importTranslationArchive,
    skipQAArchive,
    addTranslationEntry,
    updateTranslationEntry,
    deleteTranslationEntry,
    refreshDeliverables,
    loadDeliverables,
    createDeliveryPackage,
    finishWizardDelivery,
    createMergedDeliveryPackage
  }
}
