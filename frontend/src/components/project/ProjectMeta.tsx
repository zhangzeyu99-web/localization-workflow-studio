import { useEffect, useState } from 'react'
import { Bot, Clipboard, FileInput, Pencil, Pin, RefreshCw, SlidersHorizontal } from 'lucide-react'
import { api, sanitizeUserFacingError } from '../../apiClient'
import { formatDate } from '../../domain/format'
import { fieldText, fixedTermsSummary, fixedTermsToLines, getProjectHarness, linesToFixedTerms, linesToList, listToLines, linesToRules, projectPromptForLanguage, profileText, ruleSummary, rulesToLines } from '../../domain/projectAssets'
import { improvementStatusLabel } from '../../uiText'
import { languageSpec, type LanguageCode } from '../../languages'
import type { Artifact, Project, ProjectHarness } from '../../types'
import { ArtifactNote, FileBox } from '../shared/WorkflowPrimitives'

type MetaDraft = {
  game_type: string
  target_audience: string
  content_scope: string
  translation_style: string
  language_assets: string
  source_materials: string
}

const metaFields: { key: keyof MetaDraft; label: string; placeholder: string }[] = [
  { key: 'game_type', label: '游戏类型', placeholder: '例如：地狱监狱经营 SLG / 竖屏模拟经营' },
  { key: 'target_audience', label: '目标用户', placeholder: '例如：欧美移动端 SLG 玩家' },
  { key: 'content_scope', label: '内容构成', placeholder: '例如：UI、任务、建筑、英雄、联盟、战斗、邮件、剧情' },
  { key: 'translation_style', label: '翻译风格', placeholder: '例如：短促直接、适配按钮、剧情自然讽刺' },
  { key: 'language_assets', label: '语言资产', placeholder: '例如：EN 8379 行、术语 485 条、UI 9 条' },
  { key: 'source_materials', label: '素材来源', placeholder: '例如：项目 brief、语言表、需求文档、截图/视频' }
]

function metaDraftFromProject(project: Project): MetaDraft {
  return {
    game_type: profileText(project, 'game_type', project.type || ''),
    target_audience: profileText(project, 'target_audience', ''),
    content_scope: profileText(project, 'content_scope', ''),
    translation_style: profileText(project, 'translation_style', ''),
    language_assets: profileText(project, 'language_assets', ''),
    source_materials: profileText(project, 'source_materials', '')
  }
}

function fileSafeName(value: string): string {
  return (value || 'project').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/\s+/g, '_').replace(/^[_ .]+|[_ .]+$/g, '') || 'project'
}

export function MetaTab({
  project,
  intro,
  setIntro,
  busy,
  selectedLanguage,
  onSaveMeta,
  onAnalyze,
  onSaveHarness,
  assetArtifacts,
  onUploadMaterial
}: {
  project: Project
  intro: string
  setIntro: (value: string) => void
  busy: boolean
  selectedLanguage: LanguageCode
  onSaveMeta: (updates: Partial<Project>) => Promise<void>
  onAnalyze: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
  assetArtifacts: Artifact[]
  onUploadMaterial: (file: File) => Promise<Artifact | null>
}) {
  const promptText = projectPromptForLanguage(project, selectedLanguage)
  const lang = languageSpec(selectedLanguage)
  const [name, setName] = useState(project.name)
  const [type, setType] = useState(project.type || '')
  const [materialNotes, setMaterialNotes] = useState(project.description || '')
  const [metaDraft, setMetaDraft] = useState<MetaDraft>(() => metaDraftFromProject(project))
  const [editingMeta, setEditingMeta] = useState(false)
  const [promptDraft, setPromptDraft] = useState(promptText)
  const [editingPrompt, setEditingPrompt] = useState(false)

  useEffect(() => {
    setName(project.name)
    setType(project.type || '')
    setMaterialNotes(project.description || '')
    setMetaDraft(metaDraftFromProject(project))
    setEditingMeta(false)
    setPromptDraft(projectPromptForLanguage(project, selectedLanguage))
    setEditingPrompt(false)
  }, [project.id, project.name, project.type, project.description, project.prompt_text, project.profile, selectedLanguage])

  async function saveMaterialInput() {
    await onSaveMeta({ name: name.trim() || project.name, type, description: materialNotes })
    setIntro(materialNotes)
  }

  async function saveMetaDraft() {
    const profile = { ...(project.profile || {}) }
    profile.display_game_type = metaDraft.game_type
    profile.display_target_audience = metaDraft.target_audience
    profile.display_content_scope = metaDraft.content_scope
    profile.display_translation_style = metaDraft.translation_style
    profile.game_type = metaDraft.game_type
    profile.target_audience = metaDraft.target_audience
    profile.content_scope = metaDraft.content_scope
    profile.translation_style = metaDraft.translation_style
    profile.language_assets = metaDraft.language_assets
    profile.source_materials = metaDraft.source_materials
    await onSaveMeta({ type, profile })
    setEditingMeta(false)
  }

  async function savePrompt() {
    const profile = { ...(project.profile || {}) }
    const prompts = { ...((profile.prompts_by_language as Record<string, unknown> | undefined) || {}) }
    const displayPrompts = { ...((profile.display_prompts_by_language as Record<string, unknown> | undefined) || {}) }
    prompts[selectedLanguage] = promptDraft
    displayPrompts[selectedLanguage] = promptDraft
    profile.prompts_by_language = prompts
    profile.display_prompts_by_language = displayPrompts
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
          <div className="left icon-title"><Bot size={16} aria-hidden="true" />当前项目翻译提示词（{lang.short}）</div>
          <div className="card-actions">
            <button className="btn btn-ghost btn-sm" disabled={!promptText} onClick={copyPrompt}><Clipboard size={14} aria-hidden="true" />复制</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditingPrompt((value) => !value)}><Pencil size={14} aria-hidden="true" />编辑</button>
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onAnalyze}><RefreshCw size={14} aria-hidden="true" />重新生成</button>
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
      <ProjectMetaTable
        project={project}
        editing={editingMeta}
        draft={metaDraft}
        onDraftChange={(key, value) => setMetaDraft((prev) => ({ ...prev, [key]: value }))}
        onEdit={() => setEditingMeta(true)}
        onCancel={() => { setMetaDraft(metaDraftFromProject(project)); setEditingMeta(false) }}
        onSave={saveMetaDraft}
      />
      <details className="advanced-panel meta-secondary-panel">
        <summary className="icon-title"><FileInput size={15} aria-hidden="true" />资料与重新分析</summary>
        <div className="advanced-body">
          <div className="card material-card">
            <div className="card-title">
              <div className="left">项目资料投放</div>
              <div className="card-actions">
                <button className="btn btn-ghost btn-sm" disabled={busy} onClick={saveMaterialInput}>保存资料说明</button>
                <button className="btn btn-primary btn-sm" disabled={busy} onClick={onAnalyze}>重新分析项目</button>
              </div>
            </div>
            <p className="section-hint">这里放项目 brief、需求文档、语言表、图片或视频素材；重复文件会自动复用，不重复参与分析。</p>
            <div className="meta-grid material-input-grid">
              <label><span>项目名</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
              <label><span>题材/分类</span><input value={type} onChange={(event) => setType(event.target.value)} placeholder="体育 / SLG / 休闲 / RPG" /></label>
              <label className="wide"><span>投进去的信息 / 本次分析补充</span><textarea value={materialNotes} onChange={(event) => { setMaterialNotes(event.target.value); setIntro(event.target.value) }} placeholder="写项目背景、目标用户、风格要求；也可以直接上传 project brief、需求文档、语言表、截图或视频。" /></label>
            </div>
            <div className="material-upload-row">
              <FileBox label="上传项目资料（MD/TXT/DOCX/PDF/XLSX/图片/视频）" onFile={(file) => { void onUploadMaterial(file) }} />
              <div className="material-list">
                <strong>已投资料 {assetArtifacts.length} 个</strong>
                <span className="muted">这些资料会进入下一次项目分析；完整语言表只参与分析和候选扫描，不会直接写入术语库。</span>
                <div className="material-notes">
                  {assetArtifacts.slice(0, 4).map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}
                  {assetArtifacts.length > 4 ? <span className="muted">还有 {assetArtifacts.length - 4} 个资料已归档。</span> : null}
                  {!assetArtifacts.length ? <span className="muted">暂无上传资料。可以先写上方说明，也可以直接上传文件。</span> : null}
                </div>
              </div>
            </div>
          </div>
        </div>
      </details>
      <details className="advanced-panel meta-secondary-panel">
        <summary className="icon-title"><SlidersHorizontal size={15} aria-hidden="true" />高级：项目 Harness / 规则包</summary>
        <div className="advanced-body">
          <div className="card harness-card">
            <div className="card-title">
              <div>
                <div className="left">项目 Harness / 规则包</div>
                <div className="muted-left">只影响当前项目；后续翻译、AI 校对和 QA 都会读取这份规则。</div>
              </div>
            </div>
            <HarnessEditor project={project} onSave={onSaveHarness} compact />
            <ImprovementQueue project={project} onSaveHarness={onSaveHarness} />
          </div>
        </div>
      </details>
    </>
  )
}

export function ProjectMetaTable({
  project,
  editing = false,
  draft,
  onDraftChange,
  onEdit,
  onCancel,
  onSave
}: {
  project: Project
  editing?: boolean
  draft?: MetaDraft
  onDraftChange?: (key: keyof MetaDraft, value: string) => void
  onEdit?: () => void
  onCancel?: () => void
  onSave?: () => void
}) {
  const harness = getProjectHarness(project)
  const forbidden = fieldText(harness.forbidden_translations, '未设置')
  const fixedTerms = fixedTermsSummary(project)
  const rules = ruleSummary(project)
  const ruleUpdated = harness.updated_at ? `保存于 ${formatDate(harness.updated_at)}` : '未单独保存'
  const rowValue = (key: keyof MetaDraft, fallback = '未生成') => draft?.[key] ?? profileText(project, key, fallback)
  return (
    <div className="card reference-card">
      <div className="card-title">
        <div className="left icon-title"><Pin size={15} aria-hidden="true" />项目元信息</div>
        <div className="card-actions">
          {editing ? (
            <>
              <button className="btn btn-ghost btn-sm" onClick={onCancel}>取消</button>
              <button className="btn btn-primary btn-sm" onClick={onSave}>保存元信息</button>
            </>
          ) : (
            <button className="btn btn-ghost btn-sm" onClick={onEdit}><Pencil size={14} aria-hidden="true" />编辑元信息</button>
          )}
        </div>
      </div>
      {editing ? (
        <div className="meta-grid meta-edit-grid">
          {metaFields.map((field) => (
            <label key={field.key} className={field.key === 'content_scope' || field.key === 'translation_style' ? 'wide' : ''}>
              <span>{field.label}</span>
              <textarea
                value={draft?.[field.key] || ''}
                onChange={(event) => onDraftChange?.(field.key, event.target.value)}
                placeholder={field.placeholder}
              />
            </label>
          ))}
        </div>
      ) : (
        <table className="meta-table">
          <tbody>
            <tr><th>游戏类型</th><td>{rowValue('game_type', project.type || '未填写')}</td></tr>
            <tr><th>目标用户</th><td>{rowValue('target_audience')}</td></tr>
            <tr><th>内容构成</th><td>{rowValue('content_scope')}</td></tr>
            <tr><th>翻译风格</th><td>{rowValue('translation_style')}</td></tr>
            <tr><th>语言资产</th><td>{rowValue('language_assets')}</td></tr>
            <tr><th>素材来源</th><td>{rowValue('source_materials')}</td></tr>
            <tr><th>项目规则摘要</th><td>固定译名：{fixedTerms}；禁用译法：{forbidden}；项目规则：{rules}。{ruleUpdated}</td></tr>
            <tr><th>生成日期</th><td>{profileText(project, 'generated_date', formatDate(project.updated_at))}</td></tr>
          </tbody>
        </table>
      )}
    </div>
  )
}

type ImprovementKind = 'style_guidance' | 'fixed_term' | 'forbidden' | 'hard_rule' | 'soft_rule'

function improvementText(item: Record<string, unknown>): string {
  return [item.title, item.detail].map((value) => String(value || '').trim()).filter(Boolean).join('：')
}

function harnessUpdateFromImprovement(project: Project, item: Record<string, unknown>, kind: ImprovementKind): Partial<ProjectHarness> {
  const harness = getProjectHarness(project)
  const title = String(item.title || '').trim()
  const detail = String(item.detail || '').trim()
  const text = improvementText(item)
  if (kind === 'style_guidance') {
    return { style_guidance: [harness.style_guidance, text].filter(Boolean).join('\n') }
  }
  if (kind === 'fixed_term') {
    const [source, target] = text.includes('=>') ? text.split('=>').map((part) => part.trim()) : [title || text, '']
    return { fixed_terms: [...(harness.fixed_terms || []), { source, target, note: detail, severity: 'hard' }] }
  }
  if (kind === 'forbidden') {
    return { forbidden_translations: [...(harness.forbidden_translations || []), text] }
  }
  if (kind === 'hard_rule') {
    return { hard_rules: [...(harness.hard_rules || []), { label: title || '项目规则', description: detail || text, pattern: '', enabled: true }] }
  }
  return { soft_rules: [...(harness.soft_rules || []), { label: title || '项目建议', description: detail || text, pattern: '', enabled: true }] }
}

export function ImprovementQueue({ project, onSaveHarness }: { project: Project; onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void> }) {
  const projectId = project.id
  const [items, setItems] = useState<Record<string, unknown>[]>([])
  const [kind, setKind] = useState<ImprovementKind>('soft_rule')
  const [title, setTitle] = useState('')
  const [detail, setDetail] = useState('')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  async function load() {
    setItems(await api<Record<string, unknown>[]>(`/api/projects/${projectId}/improvements`))
  }
  useEffect(() => {
    load()
  }, [projectId])

  async function addSuggestion(applyNow: boolean) {
    const cleanTitle = title.trim()
    const cleanDetail = detail.trim()
    if (!cleanTitle && !cleanDetail) {
      setMessage('请先填写建议内容。')
      return
    }
    setSaving(true)
    try {
      const item = await api<Record<string, unknown>>(`/api/projects/${projectId}/improvements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: kind, title: cleanTitle || '手动改进建议', detail: cleanDetail })
      }, '记录建议')
      setTitle('')
      setDetail('')
      await load()
      if (applyNow) await applySuggestion(item, kind)
      else setMessage('建议已记录，尚未写入 Harness。')
    } catch (error) {
      setMessage(sanitizeUserFacingError(error instanceof Error ? error.message : String(error), undefined, '记录建议'))
    } finally {
      setSaving(false)
    }
  }

  async function applySuggestion(item: Record<string, unknown>, applyKind: ImprovementKind = 'soft_rule') {
    setSaving(true)
    try {
      await onSaveHarness(harnessUpdateFromImprovement(project, item, applyKind))
      setMessage('已应用到 Harness；后续翻译、AI 校对和 QA 会读取。')
    } catch (error) {
      setMessage(sanitizeUserFacingError(error instanceof Error ? error.message : String(error), undefined, '应用到 Harness'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card improvement-card">
      <div className="card-title">
        <div>
          <div className="left">规则改进建议</div>
          <div className="muted-left">来自 QA/修复流程，也可以手动新增；只有点击“应用到 Harness”后才会持续影响后续任务。</div>
        </div>
        <button className="btn btn-sm" onClick={load}>刷新</button>
      </div>
      <div className="improvement-form">
        <label>
          <span>应用类型</span>
          <select value={kind} onChange={(event) => setKind(event.target.value as ImprovementKind)}>
            <option value="soft_rule">建议规则</option>
            <option value="hard_rule">必须规则</option>
            <option value="fixed_term">固定译名</option>
            <option value="forbidden">禁用译法</option>
            <option value="style_guidance">风格补充</option>
          </select>
        </label>
        <label>
          <span>标题</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：按钮文案用动词开头" />
        </label>
        <label className="wide">
          <span>内容</span>
          <textarea value={detail} onChange={(event) => setDetail(event.target.value)} placeholder="写清楚这条建议如何影响后续翻译或校对。" />
        </label>
        <div className="row-actions align-right wide">
          <button className="btn btn-ghost btn-sm" disabled={saving} onClick={() => { void addSuggestion(false) }}>仅记录建议</button>
          <button className="btn btn-primary btn-sm" disabled={saving} onClick={() => { void addSuggestion(true) }}>新增并应用到 Harness</button>
        </div>
      </div>
      {message ? <div className={message.includes('失败') ? 'warn-line' : 'ok-line'}>{message}</div> : null}
      <table>
        <thead><tr><th>类别</th><th>标题</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={String(item.id)}>
              <td>{String(item.category || '-')}</td>
              <td>{String(item.title || '-')}</td>
              <td><span className="tag tag-new">{improvementStatusLabel(String(item.status || ''))}</span></td>
              <td><button className="btn btn-ghost btn-sm" disabled={saving} onClick={() => { void applySuggestion(item, 'soft_rule') }}>应用到 Harness</button></td>
            </tr>
          ))}
          {!items.length ? <tr><td colSpan={4} className="muted">暂无建议；可从 QA/模型修复生成，也可以在上方手动新增。</td></tr> : null}
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
  const [importMessage, setImportMessage] = useState('')

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

  async function importHarness(file: File) {
    setImportMessage('')
    const text = (await file.text()).trim()
    if (!text) {
      setImportMessage('导入失败：文件内容为空。')
      return
    }
    try {
      let updates: Partial<ProjectHarness>
      if (/\.json$/i.test(file.name)) {
        const parsed = JSON.parse(text) as Record<string, unknown>
        const source = (parsed.project_harness || parsed.harness || parsed) as Record<string, unknown>
        updates = {
          style_guidance: typeof source.style_guidance === 'string' ? source.style_guidance : styleGuidance,
          target_audience: typeof source.target_audience === 'string' ? source.target_audience : targetAudience,
          tone: typeof source.tone === 'string' ? source.tone : tone,
          forbidden_translations: Array.isArray(source.forbidden_translations) ? source.forbidden_translations.map(String) : linesToList(forbidden),
          fixed_terms: Array.isArray(source.fixed_terms) ? source.fixed_terms as ProjectHarness['fixed_terms'] : linesToFixedTerms(fixedTerms),
          hard_rules: Array.isArray(source.hard_rules) ? source.hard_rules as ProjectHarness['hard_rules'] : linesToRules(hardRules),
          soft_rules: Array.isArray(source.soft_rules) ? source.soft_rules as ProjectHarness['soft_rules'] : linesToRules(softRules)
        }
      } else {
        updates = { style_guidance: text }
      }
      await onSave(updates)
      setImportMessage('Harness 已导入并保存。')
    } catch (error) {
      setImportMessage(`导入失败：${sanitizeUserFacingError(error instanceof Error ? error.message : String(error))}`)
    }
  }

  function exportHarness() {
    const blob = new Blob([JSON.stringify(getProjectHarness(project), null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${fileSafeName(project.name)}_project_harness.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={`card ${compact ? 'compact-harness' : ''}`}>
      <div className="card-title">
        <div>
          <div className="left">项目规则编辑</div>
          <div className="muted-left">可以手动维护，也可以导入 JSON / Markdown 规则文本。</div>
        </div>
        <div className="card-actions">
          <label className="btn btn-ghost btn-sm file-button">
            导入 Harness
            <input type="file" hidden accept=".json,.md,.markdown,.txt" onChange={(event) => event.target.files?.[0] ? void importHarness(event.target.files[0]) : null} />
          </label>
          <button className="btn btn-ghost btn-sm" onClick={exportHarness}>导出 JSON</button>
          <button className="btn btn-primary btn-sm" disabled={saving} onClick={submit}>{saving ? '保存中...' : '保存项目规则'}</button>
        </div>
      </div>
      {importMessage ? <div className={importMessage.startsWith('导入失败') ? 'warn-line' : 'ok-line'}>{importMessage}</div> : null}
      <div className="harness-editor">
        <label><span>目标受众</span><input value={targetAudience} onChange={(event) => setTargetAudience(event.target.value)} placeholder="欧美移动端玩家 / 核心策略用户" /></label>
        <label><span>语气</span><input value={tone} onChange={(event) => setTone(event.target.value)} placeholder="冷静、现代、军事化 / 轻松、活泼" /></label>
        <label className="wide"><span>项目风格要求</span><textarea value={styleGuidance} onChange={(event) => setStyleGuidance(event.target.value)} placeholder="只写当前项目特有要求，不写进整体通用规则。" /></label>
        <label><span>禁用译法（一行一个）</span><textarea value={forbidden} onChange={(event) => setForbidden(event.target.value)} placeholder={'例如：\nMachine raw\nraw CN'} /></label>
        <label><span>固定译名（一行一个 source =&gt; target）</span><textarea value={fixedTerms} onChange={(event) => setFixedTerms(event.target.value)} placeholder={'例如：\n最强指挥官 => Strongest Commander'} /></label>
        <label><span>必须规则（一行一个 label | description | regex）</span><textarea value={hardRules} onChange={(event) => setHardRules(event.target.value)} placeholder={'例如：\nNo raw marker | Raw marker must not ship | Machine raw'} /></label>
        <label><span>建议规则（一行一个 label | description）</span><textarea value={softRules} onChange={(event) => setSoftRules(event.target.value)} placeholder="例如：短 UI 文案优先用动词开头" /></label>
      </div>
    </div>
  )
}
