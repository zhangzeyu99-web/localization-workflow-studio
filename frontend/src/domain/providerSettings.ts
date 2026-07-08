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
  if (!settings) return '模型配置尚未加载，请稍后重试；如果反复出现，请打开「设置」确认 API 配置是否已保存。'
  if (!FORMAL_AI_PROVIDERS.includes(String(settings.provider))) {
    return '还没有选择可用的 AI 服务商。请先配置 GPT、GPT 中转站或 Claude。'
  }
  if (settings.provider !== 'test-fake' && !settings.api_key) {
    return `还没有配置 ${providerLabel(settings)} API 密钥。请打开「设置」填写并保存；如果这是团队共用的线上部署，请联系管理员完成 API 配置后再试。`
  }
  return ''
}

export function isAiProviderReady(settings: AppSettings | null | undefined): boolean {
  return !aiProviderConfigurationReminder(settings)
}
