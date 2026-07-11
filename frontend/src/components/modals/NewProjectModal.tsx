import React, { useState } from 'react'
import { FolderPlus } from 'lucide-react'
import { errorText } from '../../appText'

export function NewProjectModal({ onClose, onCreate }: { onClose: () => void; onCreate: (form: FormData) => Promise<void> }) {
  const [typeMode, setTypeMode] = useState('科幻 SLG')
  const [customType, setCustomType] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    // Inline validation instead of the native browser bubble, so the hint
    // matches the workbench design system and stays visible.
    if (!String(form.get('name') || '').trim()) {
      setError('请填写项目名称。')
      return
    }
    if (typeMode === '其他' && !customType.trim()) {
      setError('请填写自定义项目类型。')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onCreate(form)
    } catch (err) {
      setError(`创建失败：${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-mask show">
      <form className="modal" noValidate onSubmit={submit}>
        <h3 className="icon-title"><FolderPlus size={18} aria-hidden="true" />新建本地化项目</h3>
        <p>填写基本信息即可创建，后续可在项目里完善提示词和术语表。</p>
        <label className="field-label">项目名称</label>
        <input name="name" placeholder="例如：星际边境 / 机甲纪元" disabled={busy} onChange={() => setError('')} />
        <label className="field-label">项目类型</label>
        <select value={typeMode} disabled={busy} onChange={(event) => setTypeMode(event.target.value)}>
          <option>科幻 SLG</option>
          <option>女性向恋爱</option>
          <option>休闲合成</option>
          <option>武侠 RPG</option>
          <option>其他</option>
        </select>
        {typeMode === '其他' ? (
          <input key="custom-type" name="type" value={customType} onChange={(event) => { setCustomType(event.target.value); setError('') }} placeholder="手动填写项目类型 / 标签" autoFocus disabled={busy} />
        ) : (
          <input key="preset-type" name="type" type="hidden" value={typeMode} />
        )}
        <input name="icon" type="hidden" value="" />
        <label className="field-label">描述</label>
        <input name="description" placeholder="目标用户、题材、语气要求" disabled={busy} />
        {error ? <div className="inline-status error" data-testid="new-project-error">{error}</div> : null}
        <div className="modal-foot"><button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>取消</button><button className="btn btn-primary" disabled={busy}>{busy ? '创建中...' : '创建'}</button></div>
      </form>
    </div>
  )
}
