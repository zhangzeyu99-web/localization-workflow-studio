import React, { useCallback } from 'react'
import type { LanguageCode } from '../../languages'
import { glossaryWideRows, translationWideRows } from '../../domain/projectAssets'
import { projectActivityRuns, projectRunStatusText, projectRunTitle, visibleAnnouncementTaskCount } from '../../domain/projectActivity'
import { AnnouncementProjectPanel } from '../announcement/AnnouncementWorkflow'
import { GlossaryTab, TranslationArchiveTab } from '../assets/ProjectAssetTabs'
import type { ConfirmDialogOptions } from '../modals/ConfirmModal'
import { DeliveryTab, TranslationTab } from '../translationWizard/ProjectTabs'
import { StepQA } from '../translationWizard/steps/StepQA'
import { MetaTab } from './ProjectMeta'
import type { AnnouncementTask, AppSettings, Artifact, DeliverableTask, DeliveryFile, GlossaryPreviewRow, GlossaryTerm, Project, ProjectHarness, ProjectTab, QualityIssue, Run, TranslationEntry, TranslationReadiness } from '../../types'

export interface ProjectOverviewProps {
  project: Project
  tab: ProjectTab
  setTab: (tab: ProjectTab) => void
  settings: AppSettings | null
  busy: boolean
  status: string
  intro: string
  setIntro: (value: string) => void
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  qaArtifact: Artifact | null
  archiveArtifact: Artifact | null
  latestRun: Run | null
  translationReadiness: TranslationReadiness | null
  qualityIssues: QualityIssue[]
  glossaryPreview: GlossaryPreviewRow[]
  deliverables: DeliverableTask[]
  assetArtifacts: Artifact[]
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setQaArtifact: (artifact: Artifact | null) => void
  setArchiveArtifact: (artifact: Artifact | null) => void
  onSaveMeta: (updates: Partial<Project>) => Promise<void>
  onAnalyze: () => void
  onUploadSource: (file: File) => void
  onUploadTerm: (file: File) => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onGlossaryExtract: () => void
  onAddTerm: (form: FormData) => void
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => Promise<void>
  onDeleteTerm: (term: GlossaryTerm) => Promise<void>
  onAddTranslation: (form: FormData) => void
  onUpdateTranslation: (entry: TranslationEntry, updates: Partial<TranslationEntry>) => Promise<void>
  onDeleteTranslation: (entry: TranslationEntry) => Promise<void>
  onUploadArchive: (file: File) => Promise<Artifact | null>
  onImportArchive: (artifact?: Artifact | null) => Promise<boolean>
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
  onUploadMaterial: (file: File) => Promise<Artifact | null>
  onTranslate: () => void
  onTranslateQueue?: () => void
  onDirectQA: (artifact?: Artifact | null) => void
  onDirectQAQueue?: () => void
  onSkipQAArchive: (artifact?: Artifact | null) => void
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  onCreateDelivery: (runId: string) => Promise<DeliveryFile[] | null>
  onCreateMergedDelivery?: () => void
  onStartTask: () => void
  onStartAnnouncement: () => void
  onStartAnnouncementTask: (task: AnnouncementTask) => void
  onBeginAnnouncementCancelHold: (task: AnnouncementTask) => void
  onCancelAnnouncementHold: () => void
  announcementCancelHoldTaskId: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  selectedLanguages: LanguageCode[]
  toggleSelectedLanguage: (language: LanguageCode) => void
  confirm: (message: string, options?: ConfirmDialogOptions) => Promise<boolean>
}

function ProjectOverviewImpl({
  project,
  tab,
  setTab,
  settings,
  busy,
  status,
  intro,
  setIntro,
  sourceArtifact,
  termArtifact,
  qaArtifact,
  archiveArtifact,
  latestRun,
  translationReadiness,
  qualityIssues,
  glossaryPreview,
  deliverables,
  assetArtifacts,
  setSourceArtifact,
  setTermArtifact,
  setQaArtifact,
  setArchiveArtifact,
  onSaveMeta,
  onAnalyze,
  onUploadSource,
  onUploadTerm,
  onGlossaryPreview,
  onGlossaryImport,
  onGlossaryExtract,
  onAddTerm,
  onUpdateTerm,
  onDeleteTerm,
  onAddTranslation,
  onUpdateTranslation,
  onDeleteTranslation,
  onUploadArchive,
  onImportArchive,
  onSaveHarness,
  onUploadMaterial,
  onTranslate,
  onTranslateQueue,
  onDirectQA,
  onDirectQAQueue,
  onSkipQAArchive,
  onManualFixes,
  onModelFixes,
  onUploadTranslation,
  onCreateDelivery,
  onCreateMergedDelivery,
  onStartTask,
  onStartAnnouncement,
  onStartAnnouncementTask,
  onBeginAnnouncementCancelHold,
  onCancelAnnouncementHold,
  announcementCancelHoldTaskId,
  selectedLanguage,
  setSelectedLanguage,
  selectedLanguages,
  toggleSelectedLanguage,
  confirm
}: ProjectOverviewProps) {
  const glossaryRows = glossaryWideRows(project)
  const archiveRows = translationWideRows(project)
  const languageTaskCount = project.stats.language_tasks ?? ((project.stats.translation_runs || 0) + (project.stats.qa_runs || 0))
  const announcementTaskCount = visibleAnnouncementTaskCount(project)
  const fallbackDeliverableCount = (project.runs || []).filter((run) =>
    ['translation', 'qa'].includes(run.kind)
    && run.status === 'passed'
    && (project.artifacts || []).some((artifact) => artifact.run_id === run.id && artifact.kind === 'qa_final_workbook')
  ).length
  const deliverableCount = project.stats.deliverables ?? fallbackDeliverableCount
  const activityRuns = projectActivityRuns(project)
  const goToQaTab = useCallback(() => setTab('qa'), [setTab])
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>{project.icon ? <span className="project-icon">{project.icon}</span> : null}{project.name}</h2>
        </div>
        <div className="row-actions">
          <button className="btn btn-primary" onClick={onStartTask}>🚀 启动新翻译任务</button>
          <button className="btn btn-ghost" onClick={onStartAnnouncement}>📣 公告翻译</button>
        </div>
      </div>
      <div className="stat-grid">
        <button type="button" className="stat-card stat-action" onClick={() => setTab('translation')} title="进入语言包翻译任务">
          <div className="num">{languageTaskCount}</div><div className="lbl">语言包任务</div><div className="stat-hint">进入翻译</div>
        </button>
        <button type="button" className="stat-card stat-action" onClick={onStartAnnouncement} title="进入公告翻译任务">
          <div className="num">{announcementTaskCount}</div><div className="lbl">公告任务</div><div className="stat-hint">进入公告</div>
        </button>
        <button type="button" className="stat-card stat-action" onClick={() => setTab('delivery')} title="查看可交付文件">
          <div className="num">{deliverableCount}</div><div className="lbl">可交付</div><div className="stat-hint">查看下载</div>
        </button>
        <button type="button" className="stat-card stat-action" onClick={() => setTab('archive')} title="查看译文归档">
          <div className="num">{archiveRows.length}</div><div className="lbl">已归档文本</div><div className="stat-hint">查看归档</div>
        </button>
      </div>
      {activityRuns.length ? (
        <div className="project-activity-panel">
          <div className="section-head">
            <div>
              <strong>后台任务</strong>
              <span>刷新或换浏览器后也会从服务器同步；正在跑、失败待处理的任务会显示在这里。</span>
            </div>
          </div>
          <div className="activity-list">
            {activityRuns.map((run) => (
              <div key={run.id} className={`activity-item ${run.status}`}>
                <div>
                  <strong>{projectRunTitle(run)}</strong>
                  <span>{projectRunStatusText(run)}</span>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => {
                  setTab(run.kind === 'qa' ? 'qa' : 'translation')
                }}>{run.status === 'failed' ? '去处理' : '查看'}</button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <AnnouncementProjectPanel
        tasks={project.announcement_tasks || []}
        holdTaskId={announcementCancelHoldTaskId}
        onStartAnnouncement={onStartAnnouncement}
        onStartTask={onStartAnnouncementTask}
        onBeginCancelHold={onBeginAnnouncementCancelHold}
        onCancelHold={onCancelAnnouncementHold}
      />
      <div className="view-tabs">
        <button className={`view-tab ${tab === 'meta' ? 'active' : ''}`} onClick={() => setTab('meta')}>📝 元信息</button>
        <button className={`view-tab ${tab === 'glossary' ? 'active' : ''}`} onClick={() => setTab('glossary')}>📚 术语表</button>
        <button className={`view-tab ${tab === 'translation' ? 'active' : ''}`} onClick={() => setTab('translation')}>⚡ 翻译</button>
        <button className={`view-tab ${tab === 'qa' ? 'active' : ''}`} onClick={() => setTab('qa')}>🔧 校对</button>
        <button className={`view-tab ${tab === 'archive' ? 'active' : ''}`} onClick={() => setTab('archive')}>🗄️ 译文归档</button>
        <button className={`view-tab ${tab === 'delivery' ? 'active' : ''}`} onClick={() => setTab('delivery')}>📥 交付</button>
      </div>
      {tab === 'meta' ? (
        <MetaTab
          project={project}
          intro={intro}
          setIntro={setIntro}
          busy={busy}
          selectedLanguage={selectedLanguage}
          onSaveMeta={onSaveMeta}
          onAnalyze={onAnalyze}
          onSaveHarness={onSaveHarness}
          assetArtifacts={assetArtifacts}
          onUploadMaterial={onUploadMaterial}
        />
      ) : null}
      {tab === 'glossary' ? (
        <GlossaryTab
          project={project}
          sourceArtifact={sourceArtifact}
          termArtifact={termArtifact}
          setTermArtifact={setTermArtifact}
          glossaryPreview={glossaryPreview}
          busy={busy}
          status={status}
          onUploadTerm={onUploadTerm}
          onGlossaryPreview={onGlossaryPreview}
          onGlossaryImport={onGlossaryImport}
          onGlossaryExtract={onGlossaryExtract}
          onAddTerm={onAddTerm}
          onUpdateTerm={onUpdateTerm}
          onDeleteTerm={onDeleteTerm}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
        />
      ) : null}
      {tab === 'translation' ? (
        <TranslationTab
          project={project}
          settings={settings}
          busy={busy}
          status={status}
          sourceArtifact={sourceArtifact}
          termArtifact={termArtifact}
          latestRun={latestRun}
          translationReadiness={translationReadiness}
          qualityIssues={qualityIssues}
          setSourceArtifact={setSourceArtifact}
          setTermArtifact={setTermArtifact}
          onUploadSource={onUploadSource}
          onTranslate={onTranslate}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
        />
      ) : null}
      {tab === 'qa' ? (
        <StepQA
          project={project}
          latestRun={latestRun}
          sourceArtifact={sourceArtifact}
          translationReadiness={translationReadiness}
          qualityIssues={qualityIssues}
          qaArtifact={qaArtifact}
          setQaArtifact={setQaArtifact}
          onDirectQA={onDirectQA}
          onDirectQAQueue={onDirectQAQueue}
          onSkipQAArchive={onSkipQAArchive}
          onManualFixes={onManualFixes}
          onModelFixes={onModelFixes}
          onUploadTranslation={onUploadTranslation}
          busy={busy}
          status={status}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
          selectedLanguages={selectedLanguages}
          toggleSelectedLanguage={toggleSelectedLanguage}
          onGoDelivery={() => setTab('delivery')}
          confirm={confirm}
        />
      ) : null}
      {tab === 'archive' ? (
        <TranslationArchiveTab
          project={project}
          archiveArtifact={archiveArtifact}
          setArchiveArtifact={setArchiveArtifact}
          busy={busy}
          status={status}
          onUploadArchive={onUploadArchive}
          onImportArchive={onImportArchive}
          onAddTranslation={onAddTranslation}
          onUpdateTranslation={onUpdateTranslation}
          onDeleteTranslation={onDeleteTranslation}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
          onGoQA={goToQaTab}
        />
      ) : null}
      {tab === 'delivery' ? (
        <DeliveryTab
          project={project}
          deliverables={deliverables}
          busy={busy}
          status={status}
          onCreateDelivery={onCreateDelivery}
          onGoTranslate={() => setTab('translation')}
          onGoQA={() => setTab('qa')}
          onGoArchive={() => setTab('archive')}
        />
      ) : null}
    </>
  )
}

export const ProjectOverview = React.memo(ProjectOverviewImpl)
