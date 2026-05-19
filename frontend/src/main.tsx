import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

declare global {
  interface Window {
    __lwsRoot?: ReturnType<typeof createRoot>
  }
}

type Project = {
  id: string
  name: string
  type: string
  icon: string
  description: string
  prompt_text: string
  profile?: Record<string, unknown>
  stats: { tasks: number; words: string; langs: number; glossary: number }
  artifacts?: Artifact[]
  runs?: Run[]
  glossary?: GlossaryTerm[]
}

type Artifact = {
  id: string
  label: string
  kind: string
  path: string
  size: number
  created_at: string
  run_id?: string | null
}

type Run = {
  id: string
  project_id: string
  kind: string
  language: string
  status: string
  created_at: string
  updated_at: string
  metadata?: Record<string, unknown>
  events?: { id: number; level: string; message: string; created_at: string }[]
  artifacts?: Artifact[]
}

type GlossaryTerm = {
  id: string
  source: string
  target: string
  category: string
  note: string
  source_type: string
  confirmed: boolean
}

const API = ''
const steps = ['项目资料', 'AI 分析', '术语表', '语言表', '高频词', '目标语言', '模型翻译', '自动校对', '交付归档']
const langOptions = ['🇺🇸 英语 EN', '🇫🇷 法语 FR', '🇩🇪 德语 DE', '🇧🇷 巴葡 PT-BR', '🇷🇺 俄语 RU', '🇯🇵 日语 JA', '🇰🇷 韩语 KO', '🇪🇸 西语 ES', '🇸🇦 阿语 AR']
type ProjectTab = 'prompt' | 'glossary' | 'history'

function newestArtifact(artifacts: Artifact[] | undefined, kinds: string[]): Artifact | null {
  return [...(artifacts || [])]
    .filter((artifact) => kinds.includes(artifact.kind))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null
}

function runArtifacts(project: Project, runId: string | undefined): Artifact[] {
  if (!runId) return []
  return (project.artifacts || []).filter((artifact) => artifact.run_id === runId)
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || response.statusText)
  }
  return response.json()
}

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [currentId, setCurrentId] = useState<string>('')
  const [view, setView] = useState<'overview' | 'wizard'>('overview')
  const [tab, setTab] = useState<ProjectTab>('prompt')
  const [step, setStep] = useState(1)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [freqOpen, setFreqOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('准备就绪')
  const [intro, setIntro] = useState('')
  const [sourceArtifact, setSourceArtifact] = useState<Artifact | null>(null)
  const [termArtifact, setTermArtifact] = useState<Artifact | null>(null)
  const [assetArtifacts, setAssetArtifacts] = useState<Artifact[]>([])
  const [latestRun, setLatestRun] = useState<Run | null>(null)
  const [selectedLangs, setSelectedLangs] = useState<string[]>(['🇺🇸 英语 EN'])

  useEffect(() => {
    refreshProjects()
  }, [])

  const current = useMemo(() => projects.find((p) => p.id === currentId), [projects, currentId])

  useEffect(() => {
    if (currentId) refreshCurrent()
  }, [currentId])

  useEffect(() => {
    if (!current) return
    setIntro(current.description || '')
  }, [currentId])

  useEffect(() => {
    if (!current) {
      setSourceArtifact(null)
      setTermArtifact(null)
      setAssetArtifacts([])
      setLatestRun(null)
      return
    }
    const artifacts = current.artifacts || []
    const latestTranslation = (current.runs || []).find((run) => run.kind === 'translation') || null
    const hydratedRun = latestTranslation ? { ...latestTranslation, artifacts: runArtifacts(current, latestTranslation.id) } : null
    setSourceArtifact(newestArtifact(artifacts, ['language_table']))
    setTermArtifact(newestArtifact(artifacts, ['glossary_final', 'term_base']))
    setAssetArtifacts(artifacts.filter((artifact) => artifact.kind === 'asset'))
    setLatestRun(hydratedRun)
  }, [current?.id, current?.artifacts?.length, current?.runs?.length])

  async function refreshProjects(selectId?: string) {
    const loaded = await api<Project[]>('/api/projects')
    setProjects(loaded)
    setCurrentId(selectId || currentId || loaded[0]?.id || '')
  }

  async function refreshCurrent() {
    if (!currentId) return
    const loaded = await api<Project>(`/api/projects/${currentId}`)
    setProjects((prev) => prev.map((p) => (p.id === loaded.id ? loaded : p)))
  }

  async function createProject(form: FormData) {
    const created = await api<Project>('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.get('name'),
        type: form.get('type'),
        icon: form.get('icon') || '🎮',
        description: form.get('description') || ''
      })
    })
    setNewProjectOpen(false)
    await refreshProjects(created.id)
  }

  async function upload(file: File, kind: string) {
    if (!current) return null
    const data = new FormData()
    data.append('file', file)
    const artifact = await api<Artifact>(`/api/projects/${current.id}/files?kind=${kind}`, {
      method: 'POST',
      body: data
    })
    await refreshCurrent()
    return artifact
  }

  async function runAnalysis() {
    if (!current) return
    setBusy(true)
    setStatus('正在生成项目 profile 和翻译提示词...')
    try {
      await api(`/api/projects/${current.id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intro: intro.trim() || current.description || `${current.name} ${current.type}`,
          asset_artifact_ids: assetArtifacts.map((artifact) => artifact.id)
        })
      })
      await refreshCurrent()
      setStatus('项目提示词已生成')
    } catch (error) {
      setStatus(`项目分析失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function runGlossaryExtract() {
    if (!current || !sourceArtifact) return
    setBusy(true)
    setStatus('正在提取术语并生成 project brief...')
    try {
      const result = await api<{ run: Run; artifacts: Artifact[] }>(`/api/projects/${current.id}/glossary/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: sourceArtifact.id,
          project_name: current.name,
          source_only: false,
          id_column: 'ID',
          source_column: 'cn',
          target_column: 'en'
        })
      })
      setTermArtifact(result.artifacts.find((a) => a.kind === 'glossary_final') || null)
      setLatestRun(result.run)
      await refreshCurrent()
      setStatus('术语提取完成')
    } catch (error) {
      setStatus(`术语提取失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function runTranslate() {
    if (!current || !sourceArtifact) return
    if (!selectedLangs.some((item) => item.includes('EN'))) {
      setStatus('v1 只支持英语真闭环；其他语言保留为后续 provider 能力')
      return
    }
    setBusy(true)
    setStatus('正在创建 EN run 并调用 provider...')
    try {
      const run = await api<Run>('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: current.id,
          kind: 'translation',
          language: 'en',
          input_artifact_id: sourceArtifact.id,
          term_artifact_id: termArtifact?.id || null,
          batch_size: 90
        })
      })
      const result = await api<{ run: Run; artifacts: Artifact[]; quality?: Record<string, unknown> }>(`/api/runs/${run.id}/translate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      setLatestRun({ ...result.run, artifacts: result.artifacts })
      await refreshCurrent()
      setStatus(result.run.status === 'passed' ? 'EN 闭环通过，产物已归档' : `运行结束：${result.run.status}`)
    } catch (error) {
      setStatus(`翻译失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function uploadAsset(file: File) {
    const artifact = await upload(file, 'asset')
    if (artifact) {
      setAssetArtifacts((prev) => [artifact, ...prev.filter((item) => item.id !== artifact.id)])
      setStatus(`参考素材已归档：${artifact.label}`)
    }
  }

  async function addGlossaryTerm(form: FormData) {
    if (!current) return
    await api(`/api/projects/${current.id}/glossary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: form.get('source'),
        target: form.get('target'),
        category: form.get('category') || 'manual',
        note: form.get('note') || '',
        source_type: 'manual',
        confirmed: true
      })
    })
    await refreshCurrent()
  }

  async function updateGlossaryTerm(term: GlossaryTerm, updates: Partial<GlossaryTerm>) {
    if (!current) return
    await api(`/api/projects/${current.id}/glossary/${term.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshCurrent()
  }

  async function deleteGlossaryTerm(term: GlossaryTerm) {
    if (!current) return
    await api(`/api/projects/${current.id}/glossary/${term.id}`, { method: 'DELETE' })
    await refreshCurrent()
  }

  return (
    <div className="shell">
      <div className="app">
        <header className="header">
          <div>
            <h1>🎮 游戏翻译本地化 · 项目工作台</h1>
            <p>Localization Workflow Studio · 本地 Web 工作流</p>
          </div>
          <div className="header-actions">
            <span className={`status ${busy ? 'running' : ''}`}>{busy ? <span className="loading" /> : null}{status}</span>
            <button className="btn btn-ghost" onClick={() => setSettingsOpen(true)}>⚙ 设置</button>
          </div>
        </header>

        <div className="layout">
          <aside className="sidebar">
            <div className="sidebar-title">📁 我的项目</div>
            <div className="project-list">
              {projects.map((project) => (
                <button key={project.id} className={`project-item ${project.id === currentId ? 'active' : ''}`} onClick={() => { setCurrentId(project.id); setView('overview') }}>
                  <span className="pname">{project.icon} {project.name}</span>
                  <span className="pmeta">{project.stats.tasks} 个任务 · {project.stats.glossary} 条术语</span>
                </button>
              ))}
            </div>
            <button className="new-project-btn" onClick={() => setNewProjectOpen(true)}>+ 新建项目</button>
            <div className="sidebar-title quick">⚡ 快捷入口</div>
            <button className="project-item quick-start" disabled={!current} onClick={() => { setView('wizard'); setStep(1) }}>
              <span className="pname">🚀 开始新翻译任务</span>
              <span className="pmeta">基于当前项目启动工作流</span>
            </button>
          </aside>

          <main className="main">
            {!current ? <EmptyState onCreate={() => setNewProjectOpen(true)} /> : view === 'overview' ? (
              <ProjectOverview
                project={current}
                tab={tab}
                setTab={setTab}
                onStart={() => { setView('wizard'); setStep(1) }}
                onAddTerm={addGlossaryTerm}
                onUpdateTerm={updateGlossaryTerm}
                onDeleteTerm={deleteGlossaryTerm}
              />
            ) : (
              <Wizard
                project={current}
                step={step}
                setStep={setStep}
                intro={intro}
                setIntro={setIntro}
                sourceArtifact={sourceArtifact}
                termArtifact={termArtifact}
                assetArtifacts={assetArtifacts}
                latestRun={latestRun}
                selectedLangs={selectedLangs}
                setSelectedLangs={setSelectedLangs}
                onBack={() => setView('overview')}
                onUploadSource={async (file) => setSourceArtifact(await upload(file, 'language_table'))}
                onUploadTerm={async (file) => setTermArtifact(await upload(file, 'term_base'))}
                onUploadAsset={uploadAsset}
                onAnalyze={runAnalysis}
                onGlossaryExtract={runGlossaryExtract}
                onTranslate={runTranslate}
                onFreq={() => setFreqOpen(true)}
                busy={busy}
              />
            )}
          </main>
        </div>
      </div>

      {newProjectOpen ? <NewProjectModal onClose={() => setNewProjectOpen(false)} onCreate={createProject} /> : null}
      {settingsOpen ? <SettingsModal onClose={() => setSettingsOpen(false)} /> : null}
      {freqOpen ? <FrequencyModal onClose={() => setFreqOpen(false)} /> : null}
    </div>
  )
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return <div className="empty"><h2>还没有项目</h2><p>先创建一个本地化项目，再进入完整工作流。</p><button className="btn btn-primary" onClick={onCreate}>新建项目</button></div>
}

function ProjectOverview({ project, tab, setTab, onStart, onAddTerm, onUpdateTerm, onDeleteTerm }: {
  project: Project
  tab: ProjectTab
  setTab: (tab: ProjectTab) => void
  onStart: () => void
  onAddTerm: (form: FormData) => void
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => void
  onDeleteTerm: (term: GlossaryTerm) => void
}) {
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>{project.icon} {project.name}</h2>
          <div className="desc">{project.description || '未填写项目描述'}</div>
        </div>
        <button className="btn btn-primary" onClick={onStart}>🚀 启动新翻译任务</button>
      </div>
      <div className="stat-grid">
        <div className="stat-card"><div className="num">{project.stats.tasks}</div><div className="lbl">累计任务</div></div>
        <div className="stat-card"><div className="num">{project.stats.words}</div><div className="lbl">已翻译字数</div></div>
        <div className="stat-card"><div className="num">{project.stats.langs}</div><div className="lbl">真闭环语言</div></div>
        <div className="stat-card"><div className="num">{project.stats.glossary}</div><div className="lbl">项目术语</div></div>
      </div>
      <div className="view-tabs">
        <button className={`view-tab ${tab === 'prompt' ? 'active' : ''}`} onClick={() => setTab('prompt')}>📝 翻译提示词</button>
        <button className={`view-tab ${tab === 'glossary' ? 'active' : ''}`} onClick={() => setTab('glossary')}>📚 术语表</button>
        <button className={`view-tab ${tab === 'history' ? 'active' : ''}`} onClick={() => setTab('history')}>🕒 翻译历史</button>
      </div>
      {tab === 'prompt' ? <PromptTab project={project} /> : null}
      {tab === 'glossary' ? <GlossaryTab project={project} onAddTerm={onAddTerm} onUpdateTerm={onUpdateTerm} onDeleteTerm={onDeleteTerm} /> : null}
      {tab === 'history' ? <HistoryTab project={project} /> : null}
    </>
  )
}

function PromptTab({ project }: { project: Project }) {
  return (
    <>
      <div className="card">
        <div className="card-title"><div className="left">🤖 AI 生成的专属翻译提示词</div></div>
        <pre>{project.prompt_text || '尚未生成。进入新任务 Step 2 后生成 project_profile 和 translation_prompt。'}</pre>
      </div>
      <div className="card">
        <div className="card-title"><div className="left">📌 项目元信息</div></div>
        <table>
          <tbody>
            <tr><th>游戏类型</th><td>{project.type || '-'}</td></tr>
            <tr><th>数据目录</th><td>仓库外本地目录</td></tr>
            <tr><th>真实闭环</th><td>英语 EN</td></tr>
            <tr><th>模型协议</th><td>Chat Completions 默认 / Responses 可选</td></tr>
          </tbody>
        </table>
      </div>
    </>
  )
}

function GlossaryTab({
  project,
  onAddTerm,
  onUpdateTerm,
  onDeleteTerm
}: {
  project: Project
  onAddTerm: (form: FormData) => void
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => void
  onDeleteTerm: (term: GlossaryTerm) => void
}) {
  return (
    <div className="card">
      <div className="card-title"><div className="left">📚 项目术语表（{project.glossary?.length || 0} 条）</div></div>
      <form className="inline-form" onSubmit={(event) => { event.preventDefault(); onAddTerm(new FormData(event.currentTarget)); event.currentTarget.reset() }}>
        <input name="source" placeholder="原文术语" required />
        <input name="target" placeholder="译文 EN" />
        <input name="category" placeholder="类型" />
        <input name="note" placeholder="备注" />
        <button className="btn btn-primary btn-sm">+ 新增</button>
      </form>
      <table>
        <thead><tr><th>原文</th><th>译文</th><th>类型</th><th>来源</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          {(project.glossary || []).map((row) => (
            <tr key={row.id}>
              <td>{row.source}</td><td>{row.target}</td><td>{row.category}</td><td>{row.source_type}</td>
              <td><span className={`tag ${row.confirmed ? 'tag-done' : 'tag-new'}`}>{row.confirmed ? '已确认' : '待确认'}</span></td>
              <td>
                <div className="table-actions">
                  <button className="btn btn-sm" onClick={() => onUpdateTerm(row, { confirmed: !row.confirmed })}>{row.confirmed ? '设为待确认' : '确认'}</button>
                  <button className="btn btn-sm btn-danger" onClick={() => onDeleteTerm(row)}>删除</button>
                </div>
              </td>
            </tr>
          ))}
          {!project.glossary?.length ? <tr><td colSpan={6} className="muted">暂无术语，可手工新增或在 Step 5 自动提取。</td></tr> : null}
        </tbody>
      </table>
    </div>
  )
}

function HistoryTab({ project }: { project: Project }) {
  return (
    <div className="card">
      <div className="card-title"><div className="left">🕒 翻译历史记录</div></div>
      <table>
        <thead><tr><th>时间</th><th>类型</th><th>语言</th><th>状态</th><th>产物</th><th>操作</th></tr></thead>
        <tbody>
          {(project.runs || []).map((run) => {
            const artifacts = runArtifacts(project, run.id)
            return (
              <tr key={run.id}>
                <td>{new Date(run.created_at).toLocaleString()}</td>
                <td>{run.kind}</td><td>{run.language}</td><td><span className={`tag ${run.status === 'passed' ? 'tag-done' : 'tag-doing'}`}>{run.status}</span></td>
                <td>
                  <div className="artifact-links">
                    {artifacts.length ? artifacts.map((artifact) => <a key={artifact.id} href={`/api/artifacts/${artifact.id}/download`}>{artifact.kind}</a>) : <span className="muted-left">暂无</span>}
                  </div>
                </td>
                <td><a href={`/api/runs/${run.id}/events`} target="_blank">查看事件</a></td>
              </tr>
            )
          })}
          {!project.runs?.length ? <tr><td colSpan={6} className="muted">暂无运行历史</td></tr> : null}
        </tbody>
      </table>
    </div>
  )
}

function Wizard(props: {
  project: Project
  step: number
  setStep: (step: number) => void
  intro: string
  setIntro: (value: string) => void
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  assetArtifacts: Artifact[]
  latestRun: Run | null
  selectedLangs: string[]
  setSelectedLangs: (langs: string[]) => void
  onBack: () => void
  onUploadSource: (file: File) => void
  onUploadTerm: (file: File) => void
  onUploadAsset: (file: File) => void
  onAnalyze: () => void
  onGlossaryExtract: () => void
  onTranslate: () => void
  onFreq: () => void
  busy: boolean
}) {
  const { project, step, setStep } = props
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>🚀 新翻译任务 · 当前项目：{project.icon} {project.name}</h2>
          <div className="desc">完成 9 个步骤即可输出译文，过程中的术语、提示词和产物将回写到本项目。</div>
        </div>
        <button className="btn btn-ghost" onClick={props.onBack}>← 返回项目概览</button>
      </div>
      <div className="steps-nav">
        {steps.map((title, index) => (
          <button key={title} className={`step-item ${index + 1 === step ? 'active' : index + 1 < step ? 'done' : ''}`} onClick={() => setStep(index + 1)}>
            <span className="num">{index + 1}</span>{title}
          </button>
        ))}
      </div>
      <div className="step-panel active">
        {step === 1 ? <StepIntro {...props} /> : null}
        {step === 2 ? <StepAnalyze {...props} /> : null}
        {step === 3 ? <StepTerm {...props} /> : null}
        {step === 4 ? <StepSource {...props} /> : null}
        {step === 5 ? <StepFreq {...props} /> : null}
        {step === 6 ? <StepLang {...props} /> : null}
        {step === 7 ? <StepTranslate {...props} /> : null}
        {step === 8 ? <StepQA {...props} /> : null}
        {step === 9 ? <StepDone {...props} /> : null}
      </div>
      <div className="actions">
        <button className="btn btn-ghost" disabled={step === 1} onClick={() => setStep(step - 1)}>← 上一步</button>
        <button className="btn btn-primary" disabled={props.busy} onClick={() => setStep(Math.min(9, step + 1))}>{step === 9 ? '🏁 完成' : '下一步 →'}</button>
      </div>
    </>
  )
}

function StepIntro({
  project,
  intro,
  setIntro,
  assetArtifacts,
  onUploadAsset
}: {
  project: Project
  intro: string
  setIntro: (value: string) => void
  assetArtifacts: Artifact[]
  onUploadAsset: (file: File) => void
}) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 1</span>确认项目资料与参考素材</div>
      <div className="panel-desc">已从项目描述带入基础信息；这里只需要补充本次任务特有的风格、玩法、角色或素材。</div>
      <textarea value={intro} onChange={(event) => setIntro(event.target.value)} placeholder={'游戏名：《星际边境》\n类型：科幻 SLG\n目标用户：欧美移动端玩家\n玩法：基地建造 + 英雄养成 + 联盟战争'} />
      <div className="field-foot">
        <span>{intro.trim().length} 字</span>
        <span className={intro.trim().length > 20 || project.description ? 'ok' : 'warn'}>{intro.trim().length > 20 || project.description ? '✓ 信息可用于生成 prompt' : '⚠ 建议补充更多信息'}</span>
      </div>
      <div className="upload-row">
        <FileBox label="上传图片 / PDF / 音视频素材" onFile={onUploadAsset} />
        <div className="asset-list">
          <div className="ai-header">已归档参考素材</div>
          {assetArtifacts.length ? assetArtifacts.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />) : <div className="muted-left">暂无素材；可直接继续，不阻断语言表流程。</div>}
        </div>
      </div>
    </>
  )
}

function StepAnalyze({ onAnalyze, project, busy, assetArtifacts }: { onAnalyze: () => void; project: Project; busy: boolean; assetArtifacts: Artifact[] }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 2</span>AI 分析与专属提示词生成</div>
      <div className="panel-desc">基于文字资料与已归档素材生成 project_profile 和 translation_prompt。当前素材：{assetArtifacts.length} 个。</div>
      <button className="btn btn-primary" disabled={busy} onClick={onAnalyze}>🤖 启动 AI 分析</button>
      <div className="ai-card"><div className="ai-header">当前提示词</div><pre>{project.prompt_text || '尚未生成'}</pre></div>
    </>
  )
}

function StepTerm({ onUploadTerm, termArtifact }: { onUploadTerm: (file: File) => void; termArtifact: Artifact | null }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 3</span>导入游戏术语表</div>
      <div className="panel-desc">支持 .xlsx / .csv；也可跳过，由 Step 5 从语言表提取。</div>
      <FileBox label="上传 glossary.xlsx" onFile={onUploadTerm} />
      {termArtifact ? <ArtifactNote artifact={termArtifact} /> : null}
    </>
  )
}

function StepSource({ onUploadSource, sourceArtifact }: { onUploadSource: (file: File) => void; sourceArtifact: Artifact | null }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 4</span>导入待翻译内容</div>
      <div className="panel-desc">上传 Excel 语言表，默认字段：ID | cn | en。</div>
      <FileBox label="上传 language.xlsx" onFile={onUploadSource} />
      {sourceArtifact ? <ArtifactNote artifact={sourceArtifact} /> : null}
    </>
  )
}

function StepFreq({ onGlossaryExtract, onFreq, sourceArtifact, busy }: { onGlossaryExtract: () => void; onFreq: () => void; sourceArtifact: Artifact | null; busy: boolean }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 5</span>高频词扫描 & 术语表智能补充</div>
      <div className="panel-desc">调用 glossary workflow，输出 details、ID/CN/EN/EN2、project brief 和 prompt。</div>
      <div className="row-actions">
        <button className="btn btn-primary" disabled={!sourceArtifact || busy} onClick={onGlossaryExtract}>🔍 开始扫描</button>
        <button className="btn btn-ghost" onClick={onFreq}>💡 查看补充策略</button>
      </div>
    </>
  )
}

function StepLang({ selectedLangs, setSelectedLangs }: { selectedLangs: string[]; setSelectedLangs: (langs: string[]) => void }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 6</span>选择目标语言</div>
      <div className="panel-desc">v1 只有英语进入真实翻译闭环；其他语言保留配置入口。</div>
      <div className="lang-grid">
        {langOptions.map((lang) => (
          <button key={lang} className={`lang-chip ${selectedLangs.includes(lang) ? 'selected' : ''} ${lang.includes('EN') ? '' : 'disabled'}`} onClick={() => {
            if (lang.includes('EN')) setSelectedLangs(selectedLangs.includes(lang) ? [] : [lang])
          }}>{lang}</button>
        ))}
      </div>
    </>
  )
}

function StepTranslate({ onTranslate, busy, latestRun, sourceArtifact }: { onTranslate: () => void; busy: boolean; latestRun: Run | null; sourceArtifact: Artifact | null }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 7</span>模型翻译进行中</div>
      <div className="panel-desc">后端生成 workpack，调用 Chat Completions / Responses / Mock provider，并统一输出 JSONL。</div>
      <button className="btn btn-primary" disabled={busy || !sourceArtifact} onClick={onTranslate}>⚡ 开始翻译</button>
      {!sourceArtifact ? <div className="warn-line">请先上传或恢复语言表。</div> : null}
      {latestRun ? <RunCard run={latestRun} /> : null}
    </>
  )
}

function StepQA({ latestRun }: { latestRun: Run | null }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 8</span>自动校对与优化</div>
      <div className="panel-desc">翻译接口会自动执行保守 auto-fix、机审和 quality_harness final gate。</div>
      <div className="check-list">
        <CheckItem ok={latestRun?.status === 'passed'} title="quality_harness 最终 gate" detail={latestRun ? `当前状态：${latestRun.status}` : '等待翻译运行'} />
        <CheckItem ok title="结构校验" detail="ID、占位符、标签、换行和输入指纹由后端强校验" />
        <CheckItem ok={false} title="失败行编辑器" detail="v1 尚未接入人工修复与单批重跑；hard error 当前会让 run failed。" />
      </div>
    </>
  )
}

function StepDone({ project, latestRun }: { project: Project; latestRun: Run | null }) {
  const artifacts = latestRun?.artifacts?.length ? latestRun.artifacts : runArtifacts(project, latestRun?.id)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 9</span>输出译文 & 回写项目</div>
      <div className="ai-card">
        <div className="ai-header">🎉 本次任务摘要</div>
        <pre>{`项目：${project.name}\n语言：英语 EN\n状态：${latestRun?.status || '未运行'}\n产物数量：${artifacts.length}\n归档：仓库外数据目录`}</pre>
      </div>
      <div className="artifact-grid">
        {artifacts.map((artifact) => <a key={artifact.id} className="artifact" href={`/api/artifacts/${artifact.id}/download`}>{artifact.label}<span>{artifact.kind}</span></a>)}
      </div>
    </>
  )
}

function FileBox({ label, onFile }: { label: string; onFile: (file: File) => void }) {
  return (
    <label className="upload-box">
      <div className="icon">📄</div>
      <div className="label">{label}</div>
      <input type="file" hidden onChange={(event) => event.target.files?.[0] ? onFile(event.target.files[0]) : null} />
    </label>
  )
}

function ArtifactNote({ artifact, compact = false }: { artifact: Artifact; compact?: boolean }) {
  return <div className={`ai-card ${compact ? 'compact-note' : ''}`}><div className="ai-header">已上传：{artifact.label}</div><pre>{artifact.path}</pre></div>
}

function RunCard({ run }: { run: Run }) {
  return <div className="ai-card"><div className="ai-header">Run {run.id}</div><pre>{`status=${run.status}\nlanguage=${run.language}\nartifacts=${run.artifacts?.length || 0}`}</pre></div>
}

function CheckItem({ ok, title, detail }: { ok: boolean; title: string; detail: string }) {
  return <div className="check-item"><div className={`check-icon ${ok ? 'check-pass' : 'check-warn'}`}>{ok ? '✓' : '!'}</div><div className="check-info"><div className="name">{title}</div><div className="detail">{detail}</div></div></div>
}

function NewProjectModal({ onClose, onCreate }: { onClose: () => void; onCreate: (form: FormData) => void }) {
  return (
    <div className="modal-mask show">
      <form className="modal" onSubmit={(event) => { event.preventDefault(); onCreate(new FormData(event.currentTarget)) }}>
        <h3>🆕 新建本地化项目</h3>
        <p>填写基本信息即可创建，后续可在项目里完善提示词和术语表。</p>
        <label className="field-label">项目名称</label>
        <input name="name" placeholder="例如：星际边境 / 机甲纪元" required />
        <label className="field-label">项目类型</label>
        <select name="type"><option>科幻 SLG</option><option>女性向恋爱</option><option>休闲合成</option><option>武侠 RPG</option><option>其他</option></select>
        <label className="field-label">图标</label>
        <input name="icon" placeholder="🎮" />
        <label className="field-label">描述</label>
        <input name="description" placeholder="目标用户、题材、语气要求" />
        <div className="modal-foot"><button type="button" className="btn btn-ghost" onClick={onClose}>取消</button><button className="btn btn-primary">创建</button></div>
      </form>
    </div>
  )
}

function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null)
  useEffect(() => { api<Record<string, unknown>>('/api/settings').then(setSettings) }, [])
  async function submit(form: FormData) {
    const saved = await api<Record<string, unknown>>('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: form.get('provider'),
        protocol: form.get('protocol'),
        base_url: form.get('base_url'),
        api_key: form.get('api_key'),
        model: form.get('model'),
        batch_size: Number(form.get('batch_size') || 90)
      })
    })
    setSettings(saved)
    onClose()
  }
  return (
    <div className="modal-mask show">
      <form className="modal" onSubmit={(event) => { event.preventDefault(); submit(new FormData(event.currentTarget)) }}>
        <h3>⚙ Provider 设置</h3>
        <p>密钥写入仓库外 `settings.local.json`。默认 mock provider 可直接跑功能测试。</p>
        <label className="field-label">Provider</label>
        <select name="provider" defaultValue={String(settings?.provider || 'mock')}><option value="mock">mock</option><option value="openai-compatible">openai-compatible</option></select>
        <label className="field-label">协议</label>
        <select name="protocol" defaultValue={String(settings?.protocol || 'chat-completions')}><option value="chat-completions">Chat Completions</option><option value="responses">Responses</option></select>
        <label className="field-label">Base URL</label>
        <input name="base_url" defaultValue={String(settings?.base_url || 'https://api.openai.com')} />
        <label className="field-label">API Key</label>
        <input name="api_key" type="password" placeholder={String(settings?.api_key || '')} />
        <label className="field-label">Model</label>
        <input name="model" defaultValue={String(settings?.model || 'gpt-4.1-mini')} />
        <label className="field-label">Batch size</label>
        <input name="batch_size" type="number" defaultValue={Number(settings?.batch_size || 90)} min={1} max={200} />
        <div className="modal-foot"><button type="button" className="btn btn-ghost" onClick={onClose}>取消</button><button className="btn btn-primary">保存</button></div>
      </form>
    </div>
  )
}

function FrequencyModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-mask show">
      <div className="modal">
        <h3>💡 高频词补充策略</h3>
        <p>系统会从完整语言表中提取高频、易混淆和需要统一维护的术语，输出 details、ID/CN/EN/EN2、project brief 和 prompt。术语进入项目后可人工确认并回灌 curated rules。</p>
        <div className="modal-foot"><button className="btn btn-primary" onClick={onClose}>知道了</button></div>
      </div>
    </div>
  )
}

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Missing root element')
}
window.__lwsRoot = window.__lwsRoot ?? createRoot(rootElement)
window.__lwsRoot.render(<App />)
