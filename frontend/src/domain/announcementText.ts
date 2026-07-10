// Extracted out of components/announcement/AnnouncementWorkflow.tsx so that
// appText.ts/uiText.ts (which are statically imported by main.tsx's hot path)
// don't force-bundle the whole announcement wizard, letting it be code-split
// via React.lazy.
export function announcementStatusLabel(status?: string, parentStatus?: string): string {
  if (parentStatus === 'failed' && ['queued', 'running'].includes(status || '')) return '需继续/修复'
  const labels: Record<string, string> = {
    created: '已创建',
    constraints_ready: '约束已识别',
    languages_ready: '目标语言已确认',
    terms_ready: '术语已提取',
    lookup_ready: '译文已反查',
    prepared: '翻译准备完成',
    queued: '后台排队',
    running: '后台翻译中',
    needs_input: '需要确认/继续',
    translated: '译文已导入',
    applied: '已回填',
    delivered: '已交付',
    canceled: '已取消',
    failed: '失败',
  }
  return labels[status || ''] || status || '未开始'
}
