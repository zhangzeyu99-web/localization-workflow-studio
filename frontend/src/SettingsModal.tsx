import { useEffect, useState } from 'react'

import { api } from './apiClient'
import { getOperatorName, setOperatorName } from './operator'

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null)
  const [provider, setProvider] = useState('openai')
  const [preset, setPreset] = useState('balanced')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState('')
  const [operatorName, setOperatorNameInput] = useState(() => getOperatorName())
  const apiKeyPlaceholder = settings?.api_key === 'configured' ? '已配置；留空不修改' : '首次配置：填写后点击保存'

  useEffect(() => {
    api<Record<string, unknown>>('/api/settings').then((loaded) => {
      setSettings(loaded)
      setProvider(['openai', 'openai-chat', 'anthropic'].includes(String(loaded.provider)) ? String(loaded.provider) : 'openai')
      setPreset(['fast', 'balanced', 'deep', 'critical'].includes(String(loaded.preset)) ? String(loaded.preset) : 'balanced')
      setBaseUrl(String(loaded.base_url || ''))
      setModel(String(loaded.model || ''))
      setReasoningEffort('')
    })
  }, [])

  async function submit(form: FormData) {
    setOperatorName(String(form.get('operator_name') || ''))
    const saved = await api<Record<string, unknown>>('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: form.get('provider'),
        preset: form.get('preset'),
        api_key: form.get('api_key'),
        base_url: form.get('base_url'),
        model: form.get('model'),
        reasoning_effort: form.get('reasoning_effort')
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
            <span>AI 服务商</span>
            <select name="provider" value={provider} onChange={(event) => setProvider(event.target.value)}>
              <option value="openai">GPT</option>
              <option value="openai-chat">GPT 中转站</option>
              <option value="anthropic">Claude</option>
            </select>
          </label>
          <label>
            <span>预设</span>
            <select name="preset" value={preset} onChange={(event) => setPreset(event.target.value)}>
              <option value="fast">快速</option>
              <option value="balanced">平衡</option>
              <option value="deep">深度</option>
              <option value="critical">关键校对</option>
            </select>
          </label>
          <label className="settings-wide">
            <span>接口地址</span>
            <input name="base_url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder={provider === 'openai-chat' ? 'https://your-relay.example.com/api' : '使用官方默认地址'} />
          </label>
          <label>
            <span>模型</span>
            <input name="model" value={model} onChange={(event) => setModel(event.target.value)} placeholder="gpt-5.5" />
          </label>
          <label>
            <span>推理强度</span>
            <select name="reasoning_effort" value={reasoningEffort} onChange={(event) => setReasoningEffort(event.target.value)}>
              <option value="">跟随预设</option>
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
              <option value="xhigh">极高</option>
            </select>
          </label>
          <label className="settings-wide">
            <span>API 密钥</span>
            <input name="api_key" type="password" placeholder={apiKeyPlaceholder} />
          </label>
          <p className="settings-wide settings-note">通常只填 AI 服务商、预设和 API 密钥即可；中转站需要额外填写接口地址。长文本拆批、限流、重试和预算提醒由系统按预设自动管理。</p>
          <label className="settings-wide">
            <span>操作人昵称（可选）</span>
            <input
              name="operator_name"
              value={operatorName}
              onChange={(event) => setOperatorNameInput(event.target.value)}
              placeholder="填写后，创建任务/交付/删除项目会带上你的昵称"
              maxLength={40}
            />
          </label>
          <p className="settings-wide settings-note">仅保存在本机浏览器，用于团队共用同一个工作台时留痕；不做身份校验，也不影响你能看到或操作哪些项目。</p>
        </div>
        <div className="settings-actions"><button className="btn btn-primary">保存设置</button></div>
      </form>
    </div>
  )
}
