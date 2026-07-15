import { apiErrorText, sanitizeUserFacingError } from './apiClient'
import { announcementStatusLabel } from './domain/announcementText'
import type { AnnouncementTask } from './types'

export function errorText(error: unknown): string {
  if (error instanceof Error) return apiErrorText(error.message, error.message)
  return sanitizeUserFacingError(String(error))
}

function issueCountFromPayload(payload: Record<string, unknown>): number {
  if (Array.isArray(payload.issues)) return payload.issues.length
  const counts = payload.issue_counts
  if (counts && typeof counts === 'object') {
    return Object.values(counts as Record<string, unknown>).reduce<number>((sum, value) => sum + Number(value || 0), 0)
  }
  return Number(payload.total_cases || 0)
}

function structuredQaStatusText(payload: Record<string, unknown>): string | null {
  if (!('passed' in payload) && !('issue_counts' in payload) && !('total_cases' in payload)) return null
  if (payload.passed === true) return '\u0051\u0041 \u5df2\u901a\u8fc7\uff0c\u6b63\u5728\u6574\u7406\u4ea4\u4ed8\u6587\u4ef6\u3002'
  const issueCount = issueCountFromPayload(payload)
  return `QA \u672a\u901a\u8fc7\uff1a\u53d1\u73b0 ${issueCount} \u4e2a\u95ee\u9898\uff0c\u8bf7\u8fdb\u5165\u6821\u5bf9\u6b65\u9aa4\u67e5\u770b QA \u6458\u8981\u5e76\u5904\u7406\u3002`
}

function parseStructuredStatusText(text: string): Record<string, unknown> | null {
  let trimmed = text.trim()
  if (!trimmed.startsWith('{')) {
    const start = trimmed.indexOf('{')
    const end = trimmed.lastIndexOf('}')
    if (start < 0 || end <= start) return null
    trimmed = trimmed.slice(start, end + 1)
  }
  try {
    return JSON.parse(trimmed) as Record<string, unknown>
  } catch {
    // Some local Python harnesses print dict-like text with single quotes.
  }
  const normalized = trimmed
    .replace(/'/g, '"')
    .replace(/\bTrue\b/g, 'true')
    .replace(/\bFalse\b/g, 'false')
    .replace(/\bNone\b/g, 'null')
  try {
    return JSON.parse(normalized) as Record<string, unknown>
  } catch {
    return null
  }
}

function eventStatusText(message: unknown): string {
  if (!message) return '任务正在后台处理，请稍候...'
  if (typeof message === 'string') {
    const parsed = parseStructuredStatusText(message)
    const structured = parsed ? structuredQaStatusText(parsed) : null
    return structured || message
  }
  if (typeof message === 'object') {
    const payload = message as Record<string, unknown>
    const structured = structuredQaStatusText(payload)
    if (structured) return structured
    if (payload.status) return String(payload.status)
    if (payload.summary) return String(payload.summary)
  }
  return '\u5904\u7406\u4e2d...'
}

export function humanTaskStatus(status: string): string {
  const value = String(status || '').toLowerCase()
  if (value === 'queued') return '排队中'
  if (value === 'running') return '处理中'
  if (value === 'passed') return '已完成'
  if (value === 'failed') return '失败'
  if (value === 'needs_input') return '已暂停，等待继续'
  if (value === 'canceled') return '已取消'
  return status || '状态未知，正在处理中'
}

export function humanBackendEvent(message: unknown): string {
  if (!message) return '任务正在后台处理，请稍候...'
  if (typeof message !== 'string') return eventStatusText(message)
  const text = message.trim()
  const parsed = parseStructuredStatusText(text)
  const structured = parsed ? structuredQaStatusText(parsed) : null
  if (structured) return structured
  if (/^running local workflow step$/i.test(text)) return '正在执行本地流程。'
  if (/^input=/i.test(text)) return '正在读取输入文件。'
  if (/^glossary backfill strategy:/i.test(text)) return '正在整理术语候选。'
  let match = text.match(/^glossary backfill result:.*?\bunique=(\d+).*?\binserted=(\d+)/i)
  if (match) return `已整理 ${match[1]} 个术语候选，待确认 ${match[2]} 个。`
  match = text.match(/^ai glossary supplement added (\d+) candidates,\s*skipped (\d+)/i)
  if (match) return `AI 已补充 ${match[1]} 个候选，跳过 ${match[2]} 个。`
  if (/^quick TXT translation preflight:/i.test(text)) return '正在检查快速任务输入。'
  if (/^line proofread requested: reviewing QA workbook line by line$/i.test(text)) return '正在开始逐行校对 QA 工作簿。'
  match = text.match(/^line proofread: reviewing batch (\d+)\/(\d+) \((\d+) rows\)$/i)
  if (match) return `逐行校对中：第 ${match[1]}/${match[2]} 批，本批 ${match[3]} 行。`
  match = text.match(/^line proofread finished: reviewed=(\d+), suggested=(\d+), rejected=(\d+), applied=(\d+)$/i)
  if (match) return `逐行校对完成：已检查 ${match[1]} 行，建议 ${match[2]} 项，拒绝 ${match[3]} 项，已应用 ${match[4]} 项。`
  if (/^line proofread applied fixes; re-running machine QA on proofread workbook$/i.test(text)) return '已应用逐行校对修改，正在对校对后的工作簿重新运行 QA。'
  const sanitized = sanitizeUserFacingError(text, '')
  if (sanitized && sanitized !== text) return sanitized
  match = text.match(/^translating batch (\d+)\/(\d+): rows=(\d+), attempt=(\d+)\/(\d+)/i)
  if (match) return `正在翻译：第 ${match[1]}/${match[2]} 批，本批 ${match[3]} 行，第 ${match[4]} 次尝试。`
  match = text.match(/^translation preflight: source_rows=(\d+), translated_rows=(\d+), empty_target_rows=(\d+), .*estimated_batches=(\d+)/i)
  if (match) return `\u7ffb\u8bd1\u524d\u68c0\u67e5\u5b8c\u6210\uff1a${match[1]} \u884c\u6e90\u6587\uff0c\u7a7a\u8bd1\u6587 ${match[3]} \u884c\uff0c\u9884\u8ba1 ${match[4]} \u6279\u3002`
  match = text.match(/^batch (\d+)\/(\d+) completed and persisted: rows=(\d+)/i)
  if (match) return `已完成第 ${match[1]}/${match[2]} 批，已保存 ${match[3]} 行。`
  match = text.match(/^resume: batch (\d+)\/(\d+) already completed; rows=(\d+)/i)
  if (match) return `正在续跑：已跳过第 ${match[1]}/${match[2]} 批，之前已保存 ${match[3]} 行。`
  match = text.match(/^rate limit wait before batch (\d+): ([\d.]+)s/i)
  if (match) return `接口限流等待中：约 ${Math.ceil(Number(match[2]))} 秒后继续第 ${match[1]} 批。`
  if (/background translation job was interrupted/i.test(text)) return '后台翻译被中断，已保留进度，可点击继续翻译。'
  if (/translation run finished: status=failed/i.test(text)) return '翻译已完成，但 QA 未通过，需要进入校对修复。'
  if (/translation run finished: status=passed/i.test(text)) return '翻译和 QA 已通过，正在归档产物。'
  if (/running localization QA gate/i.test(text)) return '正在运行本地 QA 检查。'
  if (/applying translation response/i.test(text)) return '正在回填译文并校验格式。'
  if (/^running:\s/i.test(text)) return '正在执行本地校验流程。'
  if (/^final_workbook=/i.test(text)) return '译文已回填，正在进入 QA。'
  return eventStatusText(text)
}

export function announcementActionLabel(endpoint: string): string {
  const labels: Record<string, string> = {
    'inspect-constraints': '\u7ea6\u675f\u8bc6\u522b',
    'extract-terms': '\u672f\u8bed\u63d0\u53d6',
    'import-terms': '\u672f\u8bed\u5bfc\u5165',
    'lookup-translations': '\u8bd1\u6587\u53cd\u67e5',
    prepare: '\u7ffb\u8bd1\u51c6\u5907',
    translate: 'AI \u7ffb\u8bd1',
    'translate/start': 'AI \u7ffb\u8bd1',
    'translate/resume': '\u7ee7\u7eed AI \u7ffb\u8bd1',
    'import-ai': '\u5bfc\u5165\u5916\u90e8 AI \u7ed3\u679c',
    apply: '\u6821\u5bf9\u56de\u586b',
    'fix-hard-blockers': '\u81ea\u52a8\u4fee\u590d\u95ee\u9898',
    deliver: '\u4ea4\u4ed8'
  }
  return labels[endpoint] || endpoint
}

export function announcementActionSummary(endpoint: string, summary?: Record<string, unknown>): string {
  if (!summary) return ''
  const count = (key: string) => Number(summary[key] || 0)
  if (endpoint === 'inspect-constraints') {
    return '约束来源已识别，请确认目标语言。'
  }
  if (endpoint === 'extract-terms') {
    const terms = count('terms')
    const ai = summary.ai_supplement as Record<string, unknown> | undefined
    const added = Number(ai?.added_to_main || 0)
    return `已提取 ${terms} 条公告术语${added ? `，AI 补充 ${added} 条` : ''}。`
  }
  if (endpoint === 'lookup-translations') {
    return `译文反查完成，缺失术语 ${count('missing_terms')} 条。`
  }
  if (endpoint === 'prepare') {
    return `翻译准备完成，共 ${count('segments')} 段。`
  }
  if (endpoint.startsWith('translate/')) {
    return '后台翻译已启动，完成后会自动进入下一步。'
  }
  if (endpoint === 'import-ai') {
    return '外部 AI 译文已导入。'
  }
  if (endpoint === 'apply') {
    const blockers = count('hard_blockers')
    const fixed = count('auto_fixed_hard_blockers')
    return blockers ? `已回填并自动修复 ${fixed} 个问题，仍有 ${blockers} 个问题会写入 QA 摘要。` : `已回填并完成校验${fixed ? `，自动修复 ${fixed} 个问题` : ''}。`
  }
  if (endpoint === 'deliver') {
    return '已生成公告交付包，可在下方下载。'
  }
  return ''
}

export function announcementTaskStatusText(task: AnnouncementTask | null | undefined): string {
  if (!task) return ''
  const title = task.title || '当前公告任务'
  if (task.status === 'delivered') return `公告任务已交付：${title}。可在下方下载交付包。`
  if (task.status === 'applied') return `公告已校对回填：${title}。可以进入交付步骤生成交付包。`
  if (task.status === 'translated') return `公告 AI 翻译已完成：${title}。请运行校对回填。`
  if (task.status === 'failed') return `公告任务失败：${title}。请查看当前步骤提示后继续。`
  if (task.status === 'needs_input') return `公告任务暂停：${title}。请按当前步骤提示继续。`
  if (['queued', 'running'].includes(task.status)) return `公告任务处理中：${title}（${announcementStatusLabel(task.status)}）。`
  return `公告任务状态：${title}（${announcementStatusLabel(task.status)}）。`
}
