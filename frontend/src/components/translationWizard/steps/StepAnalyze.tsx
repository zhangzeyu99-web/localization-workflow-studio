import { projectPromptForLanguage } from '../../../domain/projectAssets'
import { languageSpec, type LanguageCode } from '../../../languages'
import { ProjectMetaTable } from '../../project/ProjectMeta'
import { AiInputAuditPanel } from '../../shared/AiInputAudit'
import type { Artifact, Project, ProjectMaterialAnalysis } from '../../../types'

function projectMaterialAnalysis(project: Project): ProjectMaterialAnalysis | null {
  const packet = project.profile?.material_packet
  if (!packet || typeof packet !== 'object') return null
  const record = packet as Record<string, unknown>
  return {
    summary: record.summary as ProjectMaterialAnalysis['summary'],
    materials: record.materials as ProjectMaterialAnalysis['materials'],
    language_table_candidates: record.language_table_candidates as ProjectMaterialAnalysis['language_table_candidates'],
    warning: String(project.profile?.analysis_warning || '')
  }
}


function materialTypeLabel(value: unknown): string {
  const key = String(value || '').toLowerCase()
  const labels: Record<string, string> = {
    markdown: '\u9879\u76ee brief',
    text: '\u6587\u672c\u8d44\u6599',
    document: '\u6587\u6863\u8d44\u6599',
    spreadsheet: '\u8868\u683c\u8d44\u6599',
    image: '\u56fe\u7247\u8d44\u6599',
    video: '\u89c6\u9891\u8d44\u6599',
    json: 'JSON \u8d44\u6599',
  }
  return labels[key] || '\u8d44\u6599'
}

function materialStatusLabel(value: unknown): string {
  const key = String(value || '').toLowerCase()
  if (key.startsWith('vision_analyzed')) return '\u5df2\u505a\u753b\u9762\u5206\u6790'
  if (key.startsWith('parsed')) return '\u5df2\u8bfb\u53d6'
  if (key.startsWith('language_table')) return '\u5df2\u8bc6\u522b\u8bed\u8a00\u8868'
  if (key.startsWith('archived_only')) return '\u5df2\u5f52\u6863\uff0c\u672a\u8fdb\u5165 AI \u5206\u6790'
  if (key.includes('unsupported')) return '\u6682\u672a\u652f\u6301\u89e3\u6790'
  if (!key || key === '\u672a\u89e3\u6790') return '\u672a\u89e3\u6790'
  return '\u5df2\u5904\u7406'
}

function StepAnalyzeMaterialStatus({ project }: { project: Project }) {
  const analysis = projectMaterialAnalysis(project)
  if (!analysis) return null
  const summary = analysis.summary || {}
  const materials = analysis.materials || []
  const imageDone = materials.filter((item) => item.material_type === 'image' && item.status === 'vision_analyzed').length
  const imageTotal = materials.filter((item) => item.material_type === 'image').length
  const videoDone = materials.filter((item) => item.material_type === 'video' && String(item.status || '').startsWith('vision_analyzed')).length
  const videoTotal = materials.filter((item) => item.material_type === 'video').length
  const languageTables = analysis.language_table_candidates?.length || 0
  const unsupported = materials.filter((item) => String(item.status || '').startsWith('archived_only') || item.warning).length
  const warnings = materials.map((item) => item.warning).filter(Boolean).slice(0, 3)
  return (
    <>
      <div className="status-grid">
        <div className="metric-card">
          <div className="metric-label">资料读取</div>
          <strong>{summary.parsed ?? 0}/{summary.total ?? 0}</strong>
        </div>
        <div className="metric-card">
          <div className="metric-label">语言表识别</div>
          <strong>{languageTables} 个</strong>
        </div>
        <div className="metric-card">
          <div className="metric-label">图片视觉分析</div>
          <strong>{imageTotal ? `${imageDone}/${imageTotal}` : '-'}</strong>
        </div>
        <div className="metric-card">
          <div className="metric-label">视频画面分析</div>
          <strong>{videoTotal ? `${videoDone}/${videoTotal}` : '-'}</strong>
        </div>
        <div className="metric-card">
          <div className="metric-label">未完整分析</div>
          <strong>{unsupported || '-'}</strong>
        </div>
        {analysis.warning ? <div className="inline-warning span-all">{analysis.warning}</div> : null}
        {warnings.length ? <div className="muted-left span-all">{warnings.join('；')}</div> : null}
      </div>
      <div className="material-read-list">
        <div className="ai-header">资料读取明细</div>
        {materials.length ? materials.slice(0, 8).map((item, index) => {
          const status = String(item.status || '未解析')
          const entered = Boolean(item.excerpt) && (status.startsWith('parsed') || status.startsWith('vision_analyzed'))
          return (
            <div className="material-read-row" key={`${item.artifact_id || index}`}>
              <strong>{item.filename || item.label || `资料 ${index + 1}`}</strong>
              <span>{item.material_type || 'unknown'} · {status}</span>
              <em>{entered ? '已进入 AI' : '未进入 AI'}</em>
            </div>
          )
        }) : <div className="muted-left">暂无资料读取明细。请先上传资料并运行 AI 分析。</div>}
        {materials.length > 8 ? <div className="muted-left">还有 {materials.length - 8} 个资料，可在 AI 输入摘要里查看。</div> : null}
      </div>
    </>
  )
}

export function StepAnalyze({
  onAnalyze,
  project,
  busy,
  assetArtifacts,
  selectedLanguage
}: {
  onAnalyze: () => void
  project: Project
  busy: boolean
  assetArtifacts: Artifact[]
  selectedLanguage: LanguageCode
}) {
  const lang = languageSpec(selectedLanguage)
  const hasPrompt = Boolean(projectPromptForLanguage(project, selectedLanguage))
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 2</span>AI 分析项目资料</div>
      <div className="panel-desc">读取「项目资料」步骤投入的资料，生成项目元信息和翻译提示词。已上传 {assetArtifacts.length} 个资料；重复资料会在资料包里去重。</div>
      <div className="step-brief-card">
        <div>
          <strong>{hasPrompt ? '已生成项目提示词' : '尚未生成项目提示词'}</strong>
          <span>后续 AI 翻译和 QA 会读取这里生成的项目信息；人工编辑后也会影响后续任务。</span>
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={onAnalyze}>{hasPrompt ? '重新分析项目资料' : '启动 AI 分析'}</button>
      </div>
      <StepAnalyzeMaterialStatus project={project} />
      <details className="history-collapsed">
        <summary>查看本次 AI 输入摘要</summary>
        <AiInputAuditPanel endpoint={`/api/projects/${project.id}/ai-input-summary`} title="项目资料 AI 输入摘要" />
      </details>
      <div className="ai-card"><div className="ai-header">当前 {lang.short} 提示词</div><pre>{projectPromptForLanguage(project, selectedLanguage) || '尚未生成'}</pre></div>
      <ProjectMetaTable project={project} />
    </>
  )
}
