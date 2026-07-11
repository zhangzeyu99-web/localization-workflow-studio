import React, { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { FolderKanban, Languages, Plus, Settings, WandSparkles, Zap } from 'lucide-react'
import './styles.css'
import './styles/workbench.css'
import { API } from './apiClient'
import { refreshLanguageOptions, languageSpec, type LanguageCode } from './languages'
import { SettingsModal } from './SettingsModal'
import { useConfirmDialog } from './components/modals/ConfirmModal'
import { DeleteProjectModal } from './components/modals/DeleteProjectModal'
import { CancelAnnouncementTaskModal } from './components/modals/CancelAnnouncementTaskModal'
import { NewProjectModal } from './components/modals/NewProjectModal'
import { FrequencyModal } from './components/modals/FrequencyModal'
import { EmptyState } from './components/project/EmptyState'
import { ProjectOverview } from './components/project/ProjectOverview'
import { ProjectListItem } from './components/project/ProjectListItem'
import { useProjectListPolling } from './hooks/useProjectListPolling'
import { useProjectSnapshotPolling } from './hooks/useProjectSnapshotPolling'
import { useRunStatusPolling } from './hooks/useRunStatusPolling'
import { useAnnouncementTaskPolling } from './hooks/useAnnouncementTaskPolling'
import { useActiveJobsPolling } from './hooks/useActiveJobsPolling'
import { useProjectActions } from './hooks/useProjectActions'
import { useTranslationActions } from './hooks/useTranslationActions'
import { useGlossaryActions } from './hooks/useGlossaryActions'
import { useAnnouncementActions } from './hooks/useAnnouncementActions'
import { ActiveJobsBadge } from './components/system/ActiveJobsBadge'
import { ActiveJobsPanel } from './components/system/ActiveJobsPanel'
import { onOpenActiveJobsPanelRequest } from './components/system/activeJobsPanelBus'
import { artifactsByRole, newestArtifact, runArtifacts, uniqueArtifactsByContent } from './domain/artifacts'
import { preferredTranslationResultArtifact } from './domain/projectState'
import { projectTranslationPassedStatusText } from './domain/projectActivity'
import { canSkipModelTranslation } from './domain/translationFlow'
import { scopeProjectToLanguage } from './domain/projectAssets'

const QuickTaskWizard = lazy(() => import('./components/quickTask/QuickTaskWizard').then((m) => ({ default: m.QuickTaskWizard })))
const AnnouncementWizard = lazy(() => import('./components/announcement/AnnouncementWorkflow').then((m) => ({ default: m.AnnouncementWizard })))
const Wizard = lazy(() => import('./components/translationWizard/TranslationWizard').then((m) => ({ default: m.Wizard })))

declare global {
  interface Window {
    __lwsRoot?: ReturnType<typeof createRoot>
  }
}

import type { AnnouncementLookupResult, AnnouncementTask, AppRuntimeVersion, AppSettings, Artifact, DeliverableTask, DeliveryFile, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, Project, ProjectTab, QualityIssue, Run, TranslationReadiness, AppView } from './types'


function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectsReady, setProjectsReady] = useState(false)
  const [, setLanguageVersion] = useState(0)
  const [currentId, setCurrentId] = useState<string>('')
  const [view, setView] = useState<AppView>('overview')
  const [tab, setTab] = useState<ProjectTab>('meta')
  const [step, setStep] = useState(1)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [deleteProjectTarget, setDeleteProjectTarget] = useState<Project | null>(null)
  const [deleteHoldProjectId, setDeleteHoldProjectId] = useState('')
  const deleteHoldTimer = useRef<number | null>(null)
  const longPressTriggeredProjectId = useRef('')
  const [announcementCancelTarget, setAnnouncementCancelTarget] = useState<AnnouncementTask | null>(null)
  const [announcementCancelHoldTaskId, setAnnouncementCancelHoldTaskId] = useState('')
  const announcementCancelHoldTimer = useRef<number | null>(null)
  const longPressTriggeredAnnouncementTaskId = useRef('')
  const [announcementFocusTaskId, setAnnouncementFocusTaskId] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [runtimeVersion, setRuntimeVersion] = useState<AppRuntimeVersion | null>(null)
  const [freqOpen, setFreqOpen] = useState(false)
  const [activeJobsPanelOpen, setActiveJobsPanelOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('准备就绪')
  const currentIdRef = useRef('')
  const [intro, setIntro] = useState('')
  const [sourceArtifact, setSourceArtifact] = useState<Artifact | null>(null)
  const [termArtifact, setTermArtifact] = useState<Artifact | null>(null)
  const [qaArtifact, setQaArtifact] = useState<Artifact | null>(null)
  const [archiveArtifact, setArchiveArtifact] = useState<Artifact | null>(null)
  const [assetArtifacts, setAssetArtifacts] = useState<Artifact[]>([])
  const [latestRun, setLatestRun] = useState<Run | null>(null)
  const [selectedLanguage, setSelectedLanguage] = useState<LanguageCode>('en')
  const [selectedLanguages, setSelectedLanguages] = useState<LanguageCode[]>(['en'])
  const [lineProofread, setLineProofread] = useState(false)
  const [glossaryPreview, setGlossaryPreview] = useState<GlossaryPreviewRow[]>([])
  const [glossaryBatches, setGlossaryBatches] = useState<GlossaryBatch[]>([])
  const [glossaryCandidates, setGlossaryCandidates] = useState<GlossaryCandidate[]>([])
  const [qualityIssues, setQualityIssues] = useState<QualityIssue[]>([])
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [deliverables, setDeliverables] = useState<DeliverableTask[]>([])
  const [deliverablesLoading, setDeliverablesLoading] = useState(false)
  const [deliverablesError, setDeliverablesError] = useState('')
  const [generatedDelivery, setGeneratedDelivery] = useState<{ projectId: string; runId: string; files: DeliveryFile[] } | null>(null)
  const [translationReadiness, setTranslationReadiness] = useState<TranslationReadiness | null>(null)
  const [sourceInputNotice, setSourceInputNotice] = useState<TranslationReadiness | null>(null)
  const [invalidSourceArtifactIds, setInvalidSourceArtifactIds] = useState<string[]>([])
  const translationBatchSize = 90
  const [announcementText, setAnnouncementText] = useState('')
  const [announcementLookupResult, setAnnouncementLookupResult] = useState<AnnouncementLookupResult | null>(null)
  const { confirm, alertDialog, dialog: confirmDialog } = useConfirmDialog()
  const runGlossaryExtractRef = useRef<(inputArtifact?: Artifact | null) => Promise<void>>(async () => undefined)

  const current = useMemo(() => projects.find((p) => p.id === currentId), [projects, currentId])
  const currentScoped = useMemo(() => current ? scopeProjectToLanguage(current, selectedLanguage) : undefined, [current, selectedLanguage])
  const currentLang = languageSpec(selectedLanguage)

  const setPrimaryLanguage = useCallback((language: LanguageCode) => {
    setSelectedLanguage(language)
    setSelectedLanguages((prev) => prev.includes(language) ? prev : [...prev, language])
  }, [])

  const setPrimaryLanguages = useCallback((languages: LanguageCode[], primary?: LanguageCode | null) => {
    const normalized = languages.length ? languages : [primary || selectedLanguage]
    const nextPrimary = primary && normalized.includes(primary) ? primary : normalized[0]
    setSelectedLanguages(normalized)
    setSelectedLanguage(nextPrimary)
  }, [selectedLanguage])

  const toggleTargetLanguage = useCallback((language: LanguageCode) => {
    setSelectedLanguages((prev) => {
      const wasSelected = prev.includes(language)
      const next = wasSelected
        ? prev.filter((item) => item !== language)
        : [...prev, language]
      const normalized = next.length ? next : [language]
      if (wasSelected && selectedLanguage === language) setSelectedLanguage(normalized[0])
      if (!wasSelected) setSelectedLanguage(language)
      return normalized
    })
  }, [selectedLanguage])

  const isCurrentProject = useCallback((projectId?: string | null): boolean => {
    return Boolean(projectId) && currentIdRef.current === projectId
  }, [])

  const setStatusForProject = useCallback((projectId: string, message: string) => {
    if (isCurrentProject(projectId)) setStatus(message)
  }, [isCurrentProject])

  const setBusyForProject = useCallback((projectId: string, value: boolean) => {
    if (isCurrentProject(projectId)) setBusy(value)
  }, [isCurrentProject])

  const resetProjectTransientState = useCallback((message = '准备就绪') => {
    setBusy(false)
    setStatus(message)
    setSourceArtifact(null)
    setTermArtifact(null)
    setQaArtifact(null)
    setArchiveArtifact(null)
    setAssetArtifacts([])
    setLatestRun(null)
    setSelectedLanguage('en')
    setSelectedLanguages(['en'])
    setLineProofread(false)
    setGlossaryPreview([])
    setGlossaryBatches([])
    setGlossaryCandidates([])
    setQualityIssues([])
    setDeliverables([])
    setDeliverablesLoading(false)
    setDeliverablesError('')
    setGeneratedDelivery(null)
    setTranslationReadiness(null)
    setAnnouncementText('')
    setAnnouncementLookupResult(null)
  }, [])

  const {
    cancelProjectDeleteHold, beginProjectDeleteHold, selectProject, deleteProject, refreshProjects,
    refreshCurrent, refreshProjectSnapshot, refreshRuntimeVersion, refreshSettings, saveProjectMeta,
    loadQualityIssues, createProject, upload, runAnalysis, saveHarness, uploadAsset, uploadProjectMaterial
  } = useProjectActions({
    current, currentId, currentIdRef, intro, assetArtifacts, selectedLanguage, currentLang, busy,
    deleteHoldTimer, longPressTriggeredProjectId, isCurrentProject,
    setProjects, setCurrentId, setView, setTab, setBusy, setStatus, setStatusForProject, setQualityIssues,
    setRuntimeVersion, setSettings, setNewProjectOpen, setDeleteHoldProjectId, setDeleteProjectTarget,
    setSourceArtifact, setAssetArtifacts, resetProjectTransientState, confirm,
    runGlossaryExtract: (inputArtifact) => runGlossaryExtractRef.current(inputArtifact)
  })
  const handleUploadTerm = useCallback(async (file: File) => {
    setTermArtifact(await upload(file, 'term_base'))
  }, [upload])
  const handleProjectPointerDown = useCallback((project: Project, event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button === 0) beginProjectDeleteHold(project)
  }, [beginProjectDeleteHold])
  const {
    refreshTranslationReadiness, selectSourceArtifact, selectQaArtifact, syncLanguageFromArtifact,
    classifySourceArtifact, inspectTranslationTargets, startQuickTask, runTranslate,
    startMultilingualTranslationQueue, cancelTranslateRun, runDirectQA, cancelQaRun, startMultilingualQAQueue,
    applyManualFixes, applyModelFixes, uploadSourceWorkbook, uploadArchiveWorkbook, uploadTranslationWorkbook,
    importTranslationArchive, skipQAArchive, addTranslationEntry, updateTranslationEntry, deleteTranslationEntry,
    refreshDeliverables, loadDeliverables, createDeliveryPackage, finishWizardDelivery, createMergedDeliveryPackage
  } = useTranslationActions({
    current, currentIdRef, sourceArtifact, termArtifact, qaArtifact, archiveArtifact, latestRun,
    translationReadiness, glossaryCandidates, settings, translationBatchSize, tab, selectedLanguage,
    selectedLanguages, lineProofread, currentLang, isCurrentProject,
    setSourceArtifact, setQaArtifact, setArchiveArtifact, setTranslationReadiness, setSourceInputNotice,
    setInvalidSourceArtifactIds, setStep, setBusy, setStatus, setStatusForProject, setBusyForProject,
    setQualityIssues, setLatestRun, setDeliverables, setDeliverablesLoading, setDeliverablesError, setGeneratedDelivery, setTab, setView,
    setPrimaryLanguage, setPrimaryLanguages, confirm, refreshCurrent, loadQualityIssues, upload
  })
  const glossaryActions = useGlossaryActions({
    current, currentId, sourceArtifact, termArtifact, assetArtifacts, intro, selectedLanguage, isCurrentProject,
    setSourceArtifact, setTermArtifact, setLatestRun, setStep, setBusy, setStatus, setStatusForProject,
    setBusyForProject, setGlossaryPreview, setGlossaryBatches, setGlossaryCandidates, setQaArtifact,
    refreshCurrent, refreshProjectSnapshot, syncLanguageFromArtifact, refreshTranslationReadiness
  })
  runGlossaryExtractRef.current = glossaryActions.runGlossaryExtract
  const {
    refreshGlossaryBatches, runGlossaryExtract, previewGlossaryImport, importGlossaryArtifact, addGlossaryTerm,
    updateGlossaryTerm, updateGlossaryCandidate, translateMissingGlossaryCandidates, resolveGlossaryCandidates,
    deleteGlossaryTerm
  } = glossaryActions
  const {
    cancelAnnouncementCancelHold, beginAnnouncementCancelHold, openAnnouncementTask, cancelAnnouncementTask,
    uploadAnnouncementResponse, uploadAnnouncementConstraint, uploadAnnouncementTermsFile, createAnnouncementTask,
    runAnnouncementTaskAction, runAnnouncementLookup
  } = useAnnouncementActions({
    current, currentLang, currentIdRef, selectedLanguage, busy, announcementFocusTaskId,
    announcementCancelHoldTimer, longPressTriggeredAnnouncementTaskId, isCurrentProject,
    setAnnouncementCancelHoldTaskId, setAnnouncementCancelTarget, setAnnouncementFocusTaskId,
    setAnnouncementLookupResult, setView, setBusy, setStatus, setStatusForProject, setBusyForProject,
    setLatestRun, setAssetArtifacts, refreshCurrent, upload, alertDialog
  })

  useEffect(() => {
    refreshProjects().catch(() => undefined).finally(() => setProjectsReady(true))
    refreshSettings()
    refreshRuntimeVersion()
    refreshLanguageOptions(API)
      .then(() => setLanguageVersion((value) => value + 1))
      .catch(() => undefined)
  }, [])

  useProjectListPolling(refreshProjects, currentIdRef)
  const activeJobs = useActiveJobsPolling()

  useEffect(() => onOpenActiveJobsPanelRequest(() => setActiveJobsPanelOpen(true)), [])

  useEffect(() => {
    currentIdRef.current = currentId
    resetProjectTransientState('准备就绪')
    return () => {
      if (deleteHoldTimer.current !== null) window.clearTimeout(deleteHoldTimer.current)
      if (announcementCancelHoldTimer.current !== null) window.clearTimeout(announcementCancelHoldTimer.current)
    }
  }, [currentId])

  useEffect(() => {
    if (currentId) refreshCurrent()
  }, [currentId])

  const activeRunPolling = Boolean(latestRun && ['queued', 'running'].includes(latestRun.status))
  const activeAnnouncementPolling = Boolean(current?.announcement_tasks?.some((task) => ['queued', 'running'].includes(task.status)))
  useProjectSnapshotPolling(currentId, currentIdRef, refreshProjectSnapshot, isCurrentProject, setLatestRun, setBusy, setStatus, activeRunPolling || activeAnnouncementPolling)

  useEffect(() => {
    if (deleteProjectTarget && !projects.some((project) => project.id === deleteProjectTarget.id)) {
      longPressTriggeredProjectId.current = ''
      setDeleteProjectTarget(null)
    }
  }, [deleteProjectTarget?.id, projects.map((project) => project.id).join('|')])

  useEffect(() => {
    if (!current) return
    setIntro(current.description || '')
    setAnnouncementText('')
    setAnnouncementLookupResult(null)
  }, [currentId])

  useEffect(() => {
    if (!current) {
      setSourceArtifact(null)
      setTermArtifact(null)
      setQaArtifact(null)
      setArchiveArtifact(null)
      setAssetArtifacts([])
      setLatestRun(null)
      setSelectedLanguage('en')
      setSelectedLanguages(['en'])
      setGlossaryPreview([])
      setGlossaryBatches([])
      setGlossaryCandidates([])
      setQualityIssues([])
      setDeliverables([])
      setDeliverablesLoading(false)
      setDeliverablesError('')
      setSourceInputNotice(null)
      setInvalidSourceArtifactIds([])
      setAnnouncementText('')
      setAnnouncementLookupResult(null)
      return
    }
    const artifacts = current.artifacts || []
    const latestProjectRun = (current.runs || [])[0] || null
    const hydratedRun = latestProjectRun ? { ...latestProjectRun, artifacts: runArtifacts(current, latestProjectRun.id) } : null
    setSourceArtifact(artifactsByRole(current, 'language_source')[0] || newestArtifact(artifacts, ['language_table']))
    setTermArtifact(artifactsByRole(current, 'glossary_curated')[0] || artifactsByRole(current, 'glossary_source')[0] || newestArtifact(artifacts, ['glossary_final', 'term_base']))
    const preferredQa = preferredTranslationResultArtifact(current, hydratedRun)
    setQaArtifact(preferredQa || artifactsByRole(current, 'translation_workbook')[0] || newestArtifact(artifacts, ['final_workbook']))
    setArchiveArtifact(preferredQa || artifactsByRole(current, 'translation_workbook')[0] || artifactsByRole(current, 'language_source')[0] || newestArtifact(artifacts, ['final_workbook', 'language_table']))
    setAssetArtifacts(uniqueArtifactsByContent(artifacts.filter((artifact) => artifact.kind === 'asset')))
    setLatestRun(hydratedRun)
    setDeliverables([])
    setDeliverablesLoading(false)
    setDeliverablesError('')
    setSourceInputNotice(null)
    setInvalidSourceArtifactIds([])
  }, [current?.id, current?.artifacts?.length, current?.runs?.length])

  useEffect(() => {
    if (current?.id) refreshGlossaryBatches(current.id)
  }, [current?.id, latestRun?.id, latestRun?.status, selectedLanguage])

  useEffect(() => {
    // Reset the content scroll position when the user switches project, view,
    // tab, or wizard step; otherwise a long previous page leaves the new one
    // scrolled halfway down.
    const main = document.querySelector('.main')
    if (main) main.scrollTop = 0
    window.scrollTo(0, 0)
  }, [currentId, view, tab, step])

  useEffect(() => {
    if (current?.id && (tab === 'delivery' || (view === 'wizard' && step === 9))) {
      refreshDeliverables()
    }
    // current?.artifacts?.length is a dep because delivery generation registers
    // new artifacts (readback gate / retro), which resets deliverables above and
    // must trigger a refetch to keep download links visible.
  }, [current?.id, current?.runs?.length, current?.artifacts?.length, tab, selectedLanguage, view, step])

  useEffect(() => {
    if (!sourceArtifact?.id) {
      setTranslationReadiness(null)
      return
    }
    refreshTranslationReadiness(sourceArtifact.id)
  }, [sourceArtifact?.id, settings?.batch_size, selectedLanguage])

  useEffect(() => {
    if (!qaArtifact && sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && canSkipModelTranslation(translationReadiness)) {
      setQaArtifact(sourceArtifact)
    }
  }, [qaArtifact?.id, sourceArtifact?.id, translationReadiness?.artifact_id, translationReadiness?.ready_for_qa, translationReadiness?.translated_rows, translationReadiness?.empty_target_rows, translationReadiness?.cjk_target_rows])

  useEffect(() => {
    if (!current || qaArtifact) return
    const artifact = preferredTranslationResultArtifact(current, latestRun)
    if (artifact) setQaArtifact(artifact)
  }, [current?.id, current?.artifacts?.length, current?.runs?.length, latestRun?.id, latestRun?.status, qaArtifact?.id])

  useEffect(() => {
    if (!current || !latestRun || latestRun.kind !== 'translation' || latestRun.status !== 'passed') return
    if (!isCurrentProject(latestRun.project_id) || !busy) return
    const resultArtifact = preferredTranslationResultArtifact(current, latestRun)
    if (resultArtifact) setQaArtifact(resultArtifact)
    setStep((prev) => (prev < 8 ? 8 : prev))
    setBusyForProject(latestRun.project_id, false)
    setStatusForProject(latestRun.project_id, projectTranslationPassedStatusText(latestRun, selectedLanguage))
  }, [busy, current?.id, current?.artifacts?.length, latestRun?.id, latestRun?.kind, latestRun?.status])

  useEffect(() => {
    if (!latestRun || !['failed', 'needs_input'].includes(latestRun.status)) {
      setQualityIssues([])
      return
    }
    loadQualityIssues(latestRun.id)
  }, [latestRun?.id, latestRun?.status])

  useRunStatusPolling(
    latestRun,
    tab,
    selectedLanguage,
    isCurrentProject,
    setLatestRun,
    setStep,
    setQualityIssues,
    setQaArtifact,
    setStatus,
    setStatusForProject,
    setBusyForProject,
    loadQualityIssues,
    refreshCurrent,
    refreshDeliverables,
    () => refreshProjects(currentIdRef.current)
  )

  useAnnouncementTaskPolling(current, refreshProjectSnapshot, isCurrentProject, setBusyForProject, setStatusForProject)

  const isCloudDeployment = runtimeVersion?.deployment_mode === 'cloud'
  const showSettingsButton = !__HIDE_SETTINGS__ && runtimeVersion?.deployment_mode === 'local'
  const bundleVersion = __APP_VERSION__
  const backendVersion = runtimeVersion?.version || ''
  const versionMismatch = Boolean(backendVersion) && backendVersion !== 'unknown' && backendVersion !== bundleVersion

  return (
    <div className="shell">
      <div className="app">
        <header className="header">
          <div className="brand-lockup">
            <span className="brand-mark"><Languages size={22} aria-hidden="true" /></span>
            <div>
              <h1>本地化工作台</h1>
              <p>Localization Workflow Studio</p>
            </div>
          </div>
          <div className="header-actions">
            <span className={`status ${busy ? 'running' : ''}`} role="status" aria-live="polite">{busy ? <span className="loading" /> : null}{status}</span>
            <div className="active-jobs-anchor">
              <ActiveJobsBadge jobs={activeJobs} open={activeJobsPanelOpen} onToggle={() => setActiveJobsPanelOpen((value) => !value)} />
              {activeJobsPanelOpen ? <ActiveJobsPanel jobs={activeJobs} onClose={() => setActiveJobsPanelOpen(false)} /> : null}
            </div>
            <span
              className={versionMismatch ? 'runtime-version-badge version-mismatch' : 'runtime-version-badge'}
              title={versionMismatch
                ? `前端 v${bundleVersion} 与后端 v${backendVersion} 版本不一致，请刷新页面或重新部署前端`
                : (runtimeVersion?.git_sha ? `commit ${runtimeVersion.git_sha}` : 'current deployment version')}
            >
              {versionMismatch ? `v${bundleVersion} / 后端 v${backendVersion} 版本不一致` : `v${bundleVersion}`}
            </span>
            {showSettingsButton ? <button className="btn btn-ghost" onClick={() => setSettingsOpen(true)}><Settings size={16} aria-hidden="true" />设置</button> : null}
          </div>
        </header>

        <div className="layout">
          <aside className="sidebar">
            <div className="sidebar-title"><FolderKanban size={15} aria-hidden="true" />项目</div>
            <div className="project-list">
              {projects.map((project) => (
                <ProjectListItem
                  key={project.id}
                  project={project}
                  isActive={project.id === currentId}
                  isDeleteHold={deleteHoldProjectId === project.id}
                  onPointerDown={handleProjectPointerDown}
                  onPointerUp={cancelProjectDeleteHold}
                  onPointerLeave={cancelProjectDeleteHold}
                  onPointerCancel={cancelProjectDeleteHold}
                  onSelect={selectProject}
                />
              ))}
            </div>
            <button className="new-project-btn" onClick={() => setNewProjectOpen(true)}><Plus size={15} aria-hidden="true" />新建项目</button>
            <div className="sidebar-title quick"><Zap size={15} aria-hidden="true" />快捷入口</div>
            <button className="project-item quick-entry" onClick={() => {
              if (!current) return
              setStatusForProject(current.id, '翻译任务已就绪。')
              setView('wizard')
            }} disabled={!current}>
              <span className="pname"><WandSparkles size={16} aria-hidden="true" />新翻译任务</span>
              <span className="pmeta">基于当前项目启动工作流</span>
            </button>
            <button className="project-item quick-entry" data-testid="quick-task-entry" onClick={() => {
              if (!current) return
              setStatusForProject(current.id, '\u5feb\u901f\u4efb\u52a1\u5df2\u5c31\u7eea\u3002')
              setView('quick')
            }} disabled={!current}>
              <span className="pname"><Zap size={16} aria-hidden="true" />快速任务</span>
              <span className="pmeta">三步完成翻译或校对</span>
            </button>
          </aside>

          <main className="main">
            <div className="main-content">
              {!current ? <EmptyState onCreate={() => setNewProjectOpen(true)} loading={!projectsReady} /> : view === 'overview' ? (
              <ProjectOverview
                project={current}
                tab={tab}
                setTab={setTab}
                settings={settings}
                busy={busy}
                status={status}
                intro={intro}
                setIntro={setIntro}
                sourceArtifact={sourceArtifact}
                termArtifact={termArtifact}
                qaArtifact={qaArtifact}
                archiveArtifact={archiveArtifact}
                latestRun={latestRun}
                translationReadiness={translationReadiness}
                qualityIssues={qualityIssues}
                glossaryPreview={glossaryPreview}
                deliverables={deliverables}
                deliverablesLoading={deliverablesLoading}
                deliverablesError={deliverablesError}
                assetArtifacts={assetArtifacts}
                setSourceArtifact={selectSourceArtifact}
                setTermArtifact={setTermArtifact}
                setQaArtifact={selectQaArtifact}
                setArchiveArtifact={setArchiveArtifact}
                onSaveMeta={saveProjectMeta}
                onAnalyze={runAnalysis}
                onUploadSource={uploadSourceWorkbook}
                onUploadTerm={handleUploadTerm}
                onGlossaryPreview={previewGlossaryImport}
                onGlossaryImport={importGlossaryArtifact}
                onGlossaryExtract={runGlossaryExtract}
                onAddTerm={addGlossaryTerm}
                onUpdateTerm={updateGlossaryTerm}
                onDeleteTerm={deleteGlossaryTerm}
                onAddTranslation={addTranslationEntry}
                onUpdateTranslation={updateTranslationEntry}
                onDeleteTranslation={deleteTranslationEntry}
                onUploadArchive={uploadArchiveWorkbook}
                onImportArchive={importTranslationArchive}
                onSaveHarness={saveHarness}
                onUploadMaterial={uploadProjectMaterial}
                onTranslate={() => runTranslate('T')}
                onTranslateQueue={() => startMultilingualTranslationQueue('T')}
                onDirectQA={(artifact) => runDirectQA('QA', artifact)}
                onDirectQAQueue={() => startMultilingualQAQueue('QA')}
                onCancelQa={cancelQaRun}
                onSkipQAArchive={skipQAArchive}
                onManualFixes={applyManualFixes}
                onModelFixes={applyModelFixes}
                onUploadTranslation={uploadTranslationWorkbook}
                onCreateDelivery={createDeliveryPackage}
                onRefreshDelivery={refreshDeliverables}
                onCreateMergedDelivery={createMergedDeliveryPackage}
                onStartTask={() => { setStatusForProject(current.id, '翻译任务已就绪。'); setView('wizard') }}
                onStartAnnouncement={() => openAnnouncementTask()}
                onStartQuickTask={() => { setStatusForProject(current.id, '快速任务已就绪。'); setView('quick') }}
                onStartAnnouncementTask={openAnnouncementTask}
                onBeginAnnouncementCancelHold={beginAnnouncementCancelHold}
                onCancelAnnouncementHold={cancelAnnouncementCancelHold}
                announcementCancelHoldTaskId={announcementCancelHoldTaskId}
                selectedLanguage={selectedLanguage}
                setSelectedLanguage={setPrimaryLanguage}
                selectedLanguages={selectedLanguages}
                toggleSelectedLanguage={toggleTargetLanguage}
                confirm={confirm}
              />
            ) : (
              <Suspense fallback={<span className="loading" />}>
                {view === 'quick' ? (
                  <QuickTaskWizard
                    project={current}
                    busy={busy}
                    status={status}
                    settings={settings}
                    latestRun={latestRun}
                    onBack={() => { setStatusForProject(current.id, '准备就绪'); setView('overview') }}
                    onUploadFile={upload}
                    onInspectTargets={inspectTranslationTargets}
                    onStartQuickTask={startQuickTask}
                    onViewResult={(run) => { setView('overview'); setTab(run?.kind === 'qa' ? 'qa' : 'translation') }}
                  />
                ) : view === 'announcement' ? (
                  <AnnouncementWizard
                    project={current}
                    busy={busy}
                    status={status}
                    selectedLanguage={selectedLanguage}
                    setSelectedLanguage={setSelectedLanguage}
                    assetArtifacts={assetArtifacts}
                    announcementText={announcementText}
                    setAnnouncementText={setAnnouncementText}
                    lookupResult={announcementLookupResult}
                    onUploadAsset={uploadAsset}
                    onUploadConstraint={uploadAnnouncementConstraint}
                    onUploadTermsFile={uploadAnnouncementTermsFile}
                    onCreateTask={createAnnouncementTask}
                    onTaskAction={runAnnouncementTaskAction}
                    onLookup={runAnnouncementLookup}
                    onBack={() => { setStatusForProject(current.id, '准备就绪'); setView('overview') }}
                    onUploadResponse={uploadAnnouncementResponse}
                    onBeginAnnouncementCancelHold={beginAnnouncementCancelHold}
                    onCancelAnnouncementHold={cancelAnnouncementCancelHold}
                    announcementCancelHoldTaskId={announcementCancelHoldTaskId}
                    initialTaskId={announcementFocusTaskId}
                    settings={settings}
                    confirm={confirm}
                  />
                ) : (
                  <Wizard
                    project={currentScoped || current}
                    step={step}
                    setStep={setStep}
                    intro={intro}
                    setIntro={setIntro}
                    sourceArtifact={sourceArtifact}
                    termArtifact={termArtifact}
                    qaArtifact={qaArtifact}
                    assetArtifacts={assetArtifacts}
                    latestRun={latestRun}
                    translationReadiness={translationReadiness}
                    sourceInputNotice={sourceInputNotice}
                    invalidSourceArtifactIds={invalidSourceArtifactIds}
                    glossaryBatches={glossaryBatches}
                    glossaryCandidates={glossaryCandidates}
                    qualityIssues={qualityIssues}
                    deliverables={deliverables}
                    generatedDeliveryRunId={generatedDelivery?.projectId === current.id ? generatedDelivery.runId : undefined}
                    generatedDeliveryFiles={generatedDelivery?.projectId === current.id ? generatedDelivery.files : []}
                    selectedLanguage={selectedLanguage}
                    setSelectedLanguage={setPrimaryLanguage}
                    selectedLanguages={selectedLanguages}
                    toggleSelectedLanguage={toggleTargetLanguage}
                    lineProofread={lineProofread}
                    setLineProofread={setLineProofread}
                    setSourceArtifact={selectSourceArtifact}
                    setTermArtifact={setTermArtifact}
                    setQaArtifact={selectQaArtifact}
                    glossaryPreview={glossaryPreview}
                    settings={settings}
                    status={status}
                    onBack={() => { setStatusForProject(current.id, '准备就绪'); setView('overview') }}
                    onUploadSource={uploadSourceWorkbook}
                    onUploadTerm={handleUploadTerm}
                    onUploadAsset={uploadProjectMaterial}
                    onAnalyze={runAnalysis}
                    onGlossaryExtract={runGlossaryExtract}
                    onGlossaryPreview={previewGlossaryImport}
                    onGlossaryImport={importGlossaryArtifact}
                    onTranslate={() => runTranslate('A')}
                    onTranslateQueue={() => startMultilingualTranslationQueue('T')}
                    onCancelTranslate={cancelTranslateRun}
                    onDirectQA={(artifact) => runDirectQA('QA', artifact)}
                    onDirectQAQueue={() => startMultilingualQAQueue('QA')}
                    onCancelQa={cancelQaRun}
                    onSkipQAArchive={skipQAArchive}
                    allowSkipQAArchive
                    onManualFixes={applyManualFixes}
                    onModelFixes={applyModelFixes}
                    onUploadTranslation={uploadTranslationWorkbook}
                    onCreateDelivery={createDeliveryPackage}
                    onCreateMergedDelivery={createMergedDeliveryPackage}
                    onFinishDelivery={finishWizardDelivery}
                    onFreq={() => setFreqOpen(true)}
                    onSaveHarness={saveHarness}
                    onUpdateCandidate={updateGlossaryCandidate}
                    onResolveCandidates={resolveGlossaryCandidates}
                    onTranslateMissingCandidates={translateMissingGlossaryCandidates}
                    busy={busy}
                    confirm={confirm}
                  />
                )}
              </Suspense>
              )}
            </div>
          </main>
        </div>
      </div>

      {newProjectOpen ? <NewProjectModal onClose={() => setNewProjectOpen(false)} onCreate={createProject} /> : null}
      {deleteProjectTarget ? <DeleteProjectModal project={deleteProjectTarget} busy={busy} onClose={() => { longPressTriggeredProjectId.current = ''; setDeleteProjectTarget(null) }} onDelete={deleteProject} /> : null}
      {announcementCancelTarget ? <CancelAnnouncementTaskModal task={announcementCancelTarget} busy={busy} onClose={() => { longPressTriggeredAnnouncementTaskId.current = ''; setAnnouncementCancelTarget(null) }} onCancelTask={cancelAnnouncementTask} /> : null}
      {settingsOpen ? <SettingsModal onClose={() => { setSettingsOpen(false); refreshSettings() }} /> : null}
      {freqOpen ? <FrequencyModal onClose={() => setFreqOpen(false)} /> : null}
      {confirmDialog}
    </div>
  )
}

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Missing root element')
}
window.__lwsRoot = window.__lwsRoot ?? createRoot(rootElement)
window.__lwsRoot.render(<App />)
