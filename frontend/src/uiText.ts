// Centralized static UI copy: button/operation names, run/task status labels,
// and small phrasing helpers shared across main.tsx and the wizard components.
// Dynamic backend-event copy stays in appText.ts; this file only holds text
// that does not depend on parsing a backend message.

export { announcementStatusLabel } from './domain/announcementText'

export const OP_UPLOAD = '上传'
export const OP_TRANSLATE = '翻译'
export const OP_QA = 'QA'
export const OP_DELIVER = '交付'
export const OP_TERM_EXTRACT = '术语提取'
export const OP_ANNOUNCEMENT = '公告'
export const OP_AI_INPUT_AUDIT = '查看 AI 输入'

// Full value domain of `run.status` (translation/QA runs), confirmed by
// scanning backend/app/routers/runs.py, backend/app/db.py and
// backend/app/workflow/{translation,multilingual,delivery}.py.
export function runStatusLabel(status?: string): string {
  const value = String(status || '').toLowerCase()
  const labels: Record<string, string> = {
    created: '待启动',
    queued: '排队中',
    running: '处理中',
    passed: '已通过',
    failed: '未通过',
    needs_input: '待处理',
    canceled: '已取消',
    delivered: '已交付',
  }
  return labels[value] || (status ? status : '未知状态')
}

export function runStatusTagClass(status?: string): string {
  const value = String(status || '').toLowerCase()
  if (value === 'passed' || value === 'delivered') return 'tag-done'
  if (value === 'failed') return 'tag-warn'
  return 'tag-doing'
}

// Backend improvement-suggestion status (see backend/app/workflow/qa.py).
export function improvementStatusLabel(status?: string): string {
  const value = String(status || '').toLowerCase()
  const labels: Record<string, string> = {
    pending_review: '待审核',
    needs_model_review: '需要模型复核',
    applied: '已应用',
  }
  return labels[value] || (status || '待审核')
}

// Avoids leaking a bare "若干" placeholder when a hard-error count is not
// yet known; reads naturally either way ("发现 3 个问题" / "发现相关问题").
export function issueCountPhrase(count: number): string {
  return count > 0 ? `${count} 个` : '相关'
}

export function shortIdLabel(id: string, length = 8): string {
  const value = String(id || '')
  return value.length > length ? `${value.slice(0, length)}…` : value || '-'
}

// Line proofread copy shared by StepTranslate and RunDetail.
export const LINE_PROOFREAD_LABEL = '深度校对'
export const LINE_PROOFREAD_HINT = '更严格，耗时更长。'

export function lineProofreadSummaryText(state?: {
  reviewed_rows?: number
  suggested?: number
  rejected_by_audit?: number
  applied?: number
} | null): string {
  if (!state) return '未启用'
  return `审校 ${state.reviewed_rows ?? 0} 行 / 建议 ${state.suggested ?? 0} / 审计回退 ${state.rejected_by_audit ?? 0} / 采纳 ${state.applied ?? 0}`
}

// Job kinds as reported by GET /api/system/active-jobs (job_kind field,
// see backend/app/jobs.py's _JOB_KIND_PREFIXES/describe_job_kind). Both
// multilingual job kinds collapse into one "多语言队列" label here since the
// active-jobs panel shows a workbench-wide glance, not a per-run detail view.
export function activeJobKindLabel(jobKind?: string): string {
  const labels: Record<string, string> = {
    translation: '翻译',
    model_fix: 'QA 修复',
    announcement: '公告翻译',
    multilingual_translate: '多语言队列',
    multilingual_qa: '多语言队列',
  }
  return labels[String(jobKind || '')] || 'AI 任务'
}
