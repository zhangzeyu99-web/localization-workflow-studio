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
    setBusy(true)
    setError('')
    try {
      await onCreate(new FormData(event.currentTarget))
    } catch (err) {
      setError(`创建失败：${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-mask show">
      <form className="modal" onSubmit={submit}>
        <h3 className="icon-title"><FolderPlus size={18} aria-hidden="true" />新建本地化项目</h3>
        <p>填写基本信息即可创建，后续可在项目里完善提示词和术语表。</p>
        <label className="field-label">项目名称</label>
        <input name="name" placeholder="例如：星际边境 / 机甲纪元" required disabled={busy} />
        <label className="field-label">项目类型</label>
        <select value={typeMode} disabled={busy} onChange={(event) => setTypeMode(event.target.value)}>
          <option>科幻 SLG</option>
          <option>女性向恋爱</option>
          <option>休闲合成</option>
          <option>武侠 RPG</option>
          <option>其他</option>
        </select>
        {typeMode === '其他' ? (
          <input key="custom-type" name="type" value={customType} onChange={(event) => setCustomType(event.target.value)} placeholder="手动填写项目类型 / 标签" required autoFocus disabled={busy} />
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
