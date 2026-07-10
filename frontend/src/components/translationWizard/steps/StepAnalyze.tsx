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
      <div className="panel-title"><span className="badge">步骤 2/9</span>AI 分析</div>
      <div className="panel-desc">确认项目信息与分析结果。</div>
      <div className="step-brief-card">
        <div>
          <strong>{hasPrompt ? '分析完成' : '等待分析'}</strong>
          <span>{assetArtifacts.length} 个参考资料</span>
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={onAnalyze}>{hasPrompt ? '重新分析' : '开始分析'}</button>
      </div>
      <div className="analysis-summary">
        <div><span>项目</span><strong>{project.name}</strong></div>
        <div><span>目标语言</span><strong>{lang.label}</strong></div>
        <div><span>参考资料</span><strong>{assetArtifacts.length} 个</strong></div>
        <div><span>提示词</span><strong>{hasPrompt ? '已生成' : '未生成'}</strong></div>
      </div>
      <details className="analysis-details">
        <summary>查看分析详情</summary>
        <div className="analysis-details-body">
          <StepAnalyzeMaterialStatus project={project} />
          <AiInputAuditPanel endpoint={`/api/projects/${project.id}/ai-input-summary`} title="项目资料 AI 输入摘要" />
          <div className="ai-card"><div className="ai-header">{lang.short} 提示词</div><pre>{projectPromptForLanguage(project, selectedLanguage) || '尚未生成'}</pre></div>
          <ProjectMetaTable project={project} />
        </div>
      </details>
    </>
  )
}
