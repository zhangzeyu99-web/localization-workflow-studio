import { aiProviderConfigurationReminder, providerLabel } from '../../domain/providerSettings'
import { translationInputMode, translationReadinessUserMessage } from '../../domain/translationFlow'
import type { AppSettings, Artifact, Project, TranslationReadiness } from '../../types'

export function providerName(settings: AppSettings | null): string {
  return providerLabel(settings)
}

export function formalTranslationBlockReason(settings: AppSettings | null, sourceArtifact: Artifact | null, project?: Project, readiness?: TranslationReadiness | null): string {
  if (!sourceArtifact) return '请先上传或选择待翻译语言表。'
  const readinessBlock = translationReadinessBlockReason(readiness)
  if (readinessBlock) return readinessBlock
  const configurationReminder = aiProviderConfigurationReminder(settings)
  if (configurationReminder) return configurationReminder
  return ''
}

export function translationReadinessBlockReason(readiness?: TranslationReadiness | null): string {
  if (!readiness) return ''
  if (translationInputMode(readiness) === 'invalid') return translationReadinessUserMessage(readiness)
  if (Number(readiness.invalid_id_rows || 0) > 0) {
    const samples = readiness.invalid_id_samples?.length ? ` 示例：${readiness.invalid_id_samples.join(', ')}` : ''
    return `语言表有 ${readiness.invalid_id_rows} 行缺少可回写 ID；请先补齐非空 ID。${samples}`
  }
  if (readiness.reason === 'no_source_rows') return '语言表未检测到原文行。'
  return ''
}
