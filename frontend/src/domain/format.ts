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

export function compactSummary(summary: Record<string, unknown>): string {
  return Object.entries(summary)
    .filter(([, value]) => value !== undefined && value !== null && typeof value !== 'object')
    .slice(0, 4)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' / ')
}
