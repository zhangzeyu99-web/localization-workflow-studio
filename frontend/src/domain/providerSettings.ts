import type { AppSettings } from '../types'

const FORMAL_AI_PROVIDERS = ['openai', 'openai-chat', 'anthropic', 'test-fake']

export function providerLabel(settings: AppSettings | null | undefined): string {
  if (!settings) return '未加载'
  if (settings.provider === 'openai') return 'GPT'
  if (settings.provider === 'openai-chat') return 'GPT 中转站'
  if (settings.provider === 'anthropic') return 'Claude'
  if (settings.provider === 'test-fake') return 'Test Fake'
  return settings.provider || '未配置'
}

export function aiProviderConfigurationReminder(settings: AppSettings | null | undefined): string {
  if (!settings) return '模型配置尚未加载，请稍后重试，或打开右上角“设置”确认。'
  if (!FORMAL_AI_PROVIDERS.includes(String(settings.provider))) {
    return '还没有选择可用的 AI 服务商。请先到右上角“设置”选择 GPT、GPT 中转站或 Claude。'
  }
  if (settings.provider !== 'test-fake' && !settings.api_key) {
    return `还没有配置 ${providerLabel(settings)} API 密钥。请先到右上角“设置”填写 API 密钥，否则无法开始 AI 翻译。`
  }
  return ''
}

export function isAiProviderReady(settings: AppSettings | null | undefined): boolean {
  return !aiProviderConfigurationReminder(settings)
}
