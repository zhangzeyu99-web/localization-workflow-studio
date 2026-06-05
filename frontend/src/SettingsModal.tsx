import { useEffect, useState } from 'react'

import { api } from './apiClient'

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null)
  const [provider, setProvider] = useState('openai')
  const [preset, setPreset] = useState('balanced')
  const apiKeyPlaceholder = settings?.api_key === 'configured' ? '已配置；留空不修改' : '写入私有 settings.local.json'
  useEffect(() => {
    api<Record<string, unknown>>('/api/settings').then((loaded) => {
      setSettings(loaded)
      setProvider(String(loaded.provider) === 'anthropic' ? 'anthropic' : 'openai')
      setPreset(['fast', 'balanced', 'deep'].includes(String(loaded.preset)) ? String(loaded.preset) : 'balanced')
    })
  }, [])
  async function submit(form: FormData) {
    const saved = await api<Record<string, unknown>>('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: form.get('provider'),
        preset: form.get('preset'),
        api_key: form.get('api_key')
      })
    })
    setSettings(saved)
    onClose()
  }
  return (
    <div className="modal-mask show">
      <form className="modal settings-modal" onSubmit={(event) => { event.preventDefault(); submit(new FormData(event.currentTarget)) }}>
        <div className="settings-head">
          <h3>⚙ 设置</h3>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
        </div>
        <div className="settings-grid">
          <label>
            <span>Provider</span>
            <select name="provider" value={provider} onChange={(event) => setProvider(event.target.value)}>
              <option value="openai">GPT</option>
              <option value="anthropic">Claude</option>
            </select>
          </label>
          <label>
            <span>预设</span>
            <select name="preset" value={preset} onChange={(event) => setPreset(event.target.value)}>
              <option value="fast">快速响应</option>
              <option value="balanced">平衡</option>
              <option value="deep">深度思考</option>
            </select>
          </label>
          <label className="settings-wide">
            <span>API key</span>
            <input name="api_key" type="password" placeholder={apiKeyPlaceholder} />
          </label>
          <p className="settings-wide settings-note">长文本拆批、限流、重试和预算提醒由系统按预设自动管理。</p>
        </div>
        <div className="settings-actions"><button className="btn btn-primary">保存设置</button></div>
      </form>
    </div>
  )
}
