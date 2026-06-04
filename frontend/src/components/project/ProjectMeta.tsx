import { useEffect, useState } from 'react'
import { api } from '../../apiClient'
import { formatDate } from '../../domain/format'
import { fieldText, fixedTermsSummary, fixedTermsToLines, getProjectHarness, linesToFixedTerms, linesToList, listToLines, linesToRules, projectPromptForLanguage, profileText, ruleSummary, rulesToLines } from '../../domain/projectAssets'
import { languageSpec, type LanguageCode } from '../../languages'
import type { Project, ProjectHarness } from '../../types'

export function MetaTab({
  project,
  intro,
  setIntro,
  busy,
  selectedLanguage,
  onSaveMeta,
  onAnalyze,
  onSaveHarness
}: {
  project: Project
  intro: string
  setIntro: (value: string) => void
  busy: boolean
  selectedLanguage: LanguageCode
  onSaveMeta: (updates: Partial<Project>) => Promise<void>
  onAnalyze: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
}) {
  const promptText = projectPromptForLanguage(project, selectedLanguage)
  const lang = languageSpec(selectedLanguage)
  const [name, setName] = useState(project.name)
  const [type, setType] = useState(project.type || '')
  const [description, setDescription] = useState(project.description || '')
  const [promptDraft, setPromptDraft] = useState(promptText)
  const [editingPrompt, setEditingPrompt] = useState(false)

  useEffect(() => {
    setName(project.name)
    setType(project.type || '')
    setDescription(project.description || '')
    setPromptDraft(projectPromptForLanguage(project, selectedLanguage))
    setEditingPrompt(false)
  }, [project.id, project.name, project.type, project.description, project.prompt_text, project.profile, selectedLanguage])

  async function submit() {
    await onSaveMeta({ name: name.trim() || project.name, type, description })
    setIntro(description)
  }

  async function savePrompt() {
    const profile = { ...(project.profile || {}) }
    const prompts = { ...((profile.prompts_by_language as Record<string, unknown> | undefined) || {}) }
    prompts[selectedLanguage] = promptDraft
    profile.prompts_by_language = prompts
    await onSaveMeta(selectedLanguage === 'en' ? { prompt_text: promptDraft, profile } : { profile })
    setEditingPrompt(false)
  }

  async function copyPrompt() {
    await navigator.clipboard.writeText(promptText)
  }

  return (
    <>
      <div className="card reference-card">
        <div className="card-title">
          <div className="left">🤖 AI 生成的专属翻译提示词（{lang.short}）</div>
          <div className="card-actions">
            <button className="btn btn-ghost btn-sm" disabled={!promptText} onClick={copyPrompt}>📋 复制</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditingPrompt((value) => !value)}>✏️ 编辑</button>
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onAnalyze}>🔄 重新生成</button>
          </div>
        </div>
        {editingPrompt ? (
          <>
            <textarea className="prompt-editor" value={promptDraft} onChange={(event) => setPromptDraft(event.target.value)} placeholder="输入当前项目专属翻译提示词" />
            <div className="row-actions align-right">
              <button className="btn btn-ghost btn-sm" onClick={() => { setPromptDraft(promptText); setEditingPrompt(false) }}>取消</button>
              <button className="btn btn-primary btn-sm" onClick={savePrompt}>保存提示词</button>
            </div>
          </>
        ) : (
          <pre>{promptText || `尚未生成 ${lang.short} 提示词。点击“重新生成”后会自动保存到当前项目。`}</pre>
        )}
      </div>
      <ProjectMetaTable project={project} />
      <details className="advanced-panel edit-panel">
        <summary>编辑项目元信息 / 重新生成输入</summary>
        <div className="advanced-body">
          <div className="card">
            <div className="card-title">
              <div className="left">项目元信息编辑</div>
              <button className="btn btn-primary btn-sm" onClick={submit}>保存元信息</button>
            </div>
            <div className="meta-grid">
              <label><span>主项目名</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
              <label><span>题材/分类</span><input value={type} onChange={(event) => setType(event.target.value)} placeholder="飞行射击 / 休闲战斗" /></label>
              <label className="wide"><span>来源标注、目标语言、风格要求、素材来源</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder={`来源：语言表、术语表、校对表\n目标语言：${lang.label}\n风格：短句准确，按钮和任务文案清晰，核心术语统一`} /></label>
              <label className="wide"><span>重新生成提示词输入</span><textarea className="compact-textarea" value={intro} onChange={(event) => setIntro(event.target.value)} placeholder="补充本次分析需要的上下文；留空时使用项目描述。" /></label>
            </div>
          </div>
        </div>
      </details>
      <details className="advanced-panel">
        <summary>高级：项目规则与持续改进</summary>
        <div className="advanced-body">
          <HarnessEditor project={project} onSave={onSaveHarness} compact />
          <ImprovementQueue projectId={project.id} />
        </div>
      </details>
    </>
  )
}

export function ProjectMetaTable({ project }: { project: Project }) {
  const harness = getProjectHarness(project)
  const forbidden = fieldText(harness.forbidden_translations, '未设置')
  const fixedTerms = fixedTermsSummary(project)
  const rules = ruleSummary(project)
  const ruleUpdated = harness.updated_at ? `保存于 ${formatDate(harness.updated_at)}` : '未单独保存'
  return (
    <div className="card reference-card">
      <div className="card-title">
        <div className="left">📌 项目元信息</div>
      </div>
      <table className="meta-table">
        <tbody>
          <tr><th>游戏类型</th><td>{profileText(project, 'game_type', project.type || '未填写')}</td></tr>
          <tr><th>目标用户</th><td>{profileText(project, 'target_audience')}</td></tr>
          <tr><th>内容构成</th><td>{profileText(project, 'content_scope')}</td></tr>
          <tr><th>翻译风格</th><td>{profileText(project, 'translation_style')}</td></tr>
          <tr><th>语言资产</th><td>{profileText(project, 'language_assets')}</td></tr>
          <tr><th>素材来源</th><td>{profileText(project, 'source_materials')}</td></tr>
          <tr><th>质量规则摘要</th><td>固定译名：{fixedTerms}；禁用译法：{forbidden}；项目规则：{rules}。{ruleUpdated}</td></tr>
          <tr><th>生成日期</th><td>{profileText(project, 'generated_date', formatDate(project.updated_at))}</td></tr>
        </tbody>
      </table>
    </div>
  )
}

export function ImprovementQueue({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Record<string, unknown>[]>([])
  async function load() {
    setItems(await api<Record<string, unknown>[]>(`/api/projects/${projectId}/improvements`))
  }
  useEffect(() => {
    load()
  }, [projectId])
  return (
    <div className="card">
      <div className="card-title">
        <div className="left">持续改进建议队列</div>
        <button className="btn btn-sm" onClick={load}>刷新</button>
      </div>
      <table>
        <thead><tr><th>类别</th><th>标题</th><th>状态</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={String(item.id)}>
              <td>{String(item.category || '-')}</td>
              <td>{String(item.title || '-')}</td>
              <td><span className="tag tag-new">{String(item.status || 'pending_review')}</span></td>
            </tr>
          ))}
          {!items.length ? <tr><td colSpan={3} className="muted">暂无建议；可在翻译历史里从某次 run 生成。</td></tr> : null}
        </tbody>
      </table>
    </div>
  )
}

export function HarnessEditor({
  project,
  onSave,
  compact = false
}: {
  project: Project
  onSave: (updates: Partial<ProjectHarness>) => Promise<void>
  compact?: boolean
}) {
  const harness = getProjectHarness(project)
  const [styleGuidance, setStyleGuidance] = useState(harness.style_guidance || '')
  const [targetAudience, setTargetAudience] = useState(harness.target_audience || '')
  const [tone, setTone] = useState(harness.tone || '')
  const [forbidden, setForbidden] = useState(listToLines(harness.forbidden_translations))
  const [fixedTerms, setFixedTerms] = useState(fixedTermsToLines(harness.fixed_terms))
  const [hardRules, setHardRules] = useState(rulesToLines(harness.hard_rules))
  const [softRules, setSoftRules] = useState(rulesToLines(harness.soft_rules))
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setStyleGuidance(harness.style_guidance || '')
    setTargetAudience(harness.target_audience || '')
    setTone(harness.tone || '')
    setForbidden(listToLines(harness.forbidden_translations))
    setFixedTerms(fixedTermsToLines(harness.fixed_terms))
    setHardRules(rulesToLines(harness.hard_rules))
    setSoftRules(rulesToLines(harness.soft_rules))
  }, [project.id, harness.updated_at])

  async function submit() {
    setSaving(true)
    try {
      await onSave({
        style_guidance: styleGuidance,
        target_audience: targetAudience,
        tone,
        forbidden_translations: linesToList(forbidden),
        fixed_terms: linesToFixedTerms(fixedTerms),
        hard_rules: linesToRules(hardRules),
        soft_rules: linesToRules(softRules)
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`card ${compact ? 'compact-harness' : ''}`}>
      <div className="card-title">
        <div className="left">项目规则编辑</div>
        <button className="btn btn-primary btn-sm" disabled={saving} onClick={submit}>{saving ? '保存中...' : '保存项目规则'}</button>
      </div>
      <div className="harness-editor">
        <label><span>目标受众</span><input value={targetAudience} onChange={(event) => setTargetAudience(event.target.value)} placeholder="欧美移动端玩家 / 核心策略用户" /></label>
        <label><span>语气</span><input value={tone} onChange={(event) => setTone(event.target.value)} placeholder="冷静、现代、军事化 / 轻松、活泼" /></label>
        <label className="wide"><span>项目风格要求</span><textarea value={styleGuidance} onChange={(event) => setStyleGuidance(event.target.value)} placeholder="只写当前项目特有要求，不写进整体通用规则。" /></label>
        <label><span>禁用译法（一行一个）</span><textarea value={forbidden} onChange={(event) => setForbidden(event.target.value)} placeholder={'例如：\nMock\nraw CN'} /></label>
        <label><span>固定译名（一行一个 source =&gt; target）</span><textarea value={fixedTerms} onChange={(event) => setFixedTerms(event.target.value)} placeholder={'例如：\n最强指挥官 => Strongest Commander'} /></label>
        <label><span>必须规则（一行一个 label | description | regex）</span><textarea value={hardRules} onChange={(event) => setHardRules(event.target.value)} placeholder={'例如：\nNo mock marker | Mock marker must not ship | Mock'} /></label>
        <label><span>建议规则（一行一个 label | description）</span><textarea value={softRules} onChange={(event) => setSoftRules(event.target.value)} placeholder="例如：短 UI 文案优先用动词开头" /></label>
      </div>
    </div>
  )
}
