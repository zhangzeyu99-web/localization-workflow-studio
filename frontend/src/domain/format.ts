export function formatDate(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toISOString().slice(0, 10)
}

export function formatDateTime(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function shortRunId(runId?: string): string {
  return (runId || '').replace(/^run_/, '').slice(0, 6) || '-'
}

export function relativeTimeFromNow(value?: string | null, now: number = Date.now()): string {
  if (!value) return '刚刚开始'
  const started = Date.parse(value)
  if (Number.isNaN(started)) return '刚刚开始'
  const diffSeconds = Math.max(0, Math.round((now - started) / 1000))
  if (diffSeconds < 60) return '刚刚开始'
  const minutes = Math.floor(diffSeconds / 60)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  return `${days} 天前`
}

export function compactSummary(summary: Record<string, unknown>): string {
  return Object.entries(summary)
    .filter(([, value]) => value !== undefined && value !== null && typeof value !== 'object')
    .slice(0, 4)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' / ')
}
