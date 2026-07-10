import type { DeliverableTask, LineProofreadState, ReferenceAuditState, Run } from '../types'

export type WorkflowTone = 'neutral' | 'info' | 'ready' | 'warn' | 'blocked' | 'running'

export type ArchiveSourcePresentation = {
  label: string
  detail: string
  tone: 'trusted' | 'review' | 'manual' | 'external'
}

export function archiveSourcePresentation(sourceType?: string): ArchiveSourcePresentation {
  const source = String(sourceType || '').trim().toLowerCase()
  if (source === 'qa_passed' || source === 'qa_final') {
    return { label: 'QA 已通过', detail: '通过项目质量规则后自动归档', tone: 'trusted' }
  }
  if (source === 'delivered_with_issues') {
    return { label: '待复核', detail: '随带问题摘要交付后归档', tone: 'review' }
  }
  if (source === 'manual' || source === 'curated') {
    return { label: '人工维护', detail: '由项目成员直接维护', tone: 'manual' }
  }
  if (source === 'imported' || source === 'archive' || source === 'translation_archive') {
    return { label: '外部导入', detail: '从已有译文表导入，未在本任务验证', tone: 'external' }
  }
  return { label: '来源未标记', detail: '当前记录没有可识别的来源标记', tone: 'external' }
}

export type QaOutcomePresentation = {
  label: string
  summary: string
  nextAction: string
  tone: WorkflowTone
  canDeliver: boolean
  deliveredWithIssues: boolean
}

export function qaOutcomePresentation(
  run: Run | null | undefined,
  issueCount = 0,
  hasFinalWorkbook = false
): QaOutcomePresentation {
  if (!run) {
    return {
      label: '尚未运行',
      summary: '选择译文文件后运行 QA。',
      nextAction: '运行 QA',
      tone: 'neutral',
      canDeliver: false,
      deliveredWithIssues: false
    }
  }
  if (run.status === 'queued' || run.status === 'running') {
    return {
      label: '校对中',
      summary: '检查结构、术语、变量和文本质量。',
      nextAction: '等待校对完成',
      tone: 'running',
      canDeliver: false,
      deliveredWithIssues: false
    }
  }
  if (run.status === 'passed') {
    return {
      label: 'QA 已通过',
      summary: '可生成标准交付。',
      nextAction: '进入标准交付',
      tone: 'ready',
      canDeliver: hasFinalWorkbook,
      deliveredWithIssues: false
    }
  }
  if (run.status === 'failed' && hasFinalWorkbook) {
    return {
      label: 'QA 未通过',
      summary: `${issueCount} 个问题待处理；可修复或带问题交付。`,
      nextAction: issueCount > 0 ? '优先修复，或带问题交付' : '复核结果，或带问题交付',
      tone: 'warn',
      canDeliver: true,
      deliveredWithIssues: true
    }
  }
  if (run.status === 'failed') {
    return {
      label: 'QA 未通过',
      summary: '未生成可交付译文，请重跑 QA。',
      nextAction: '返回修复并重跑',
      tone: 'blocked',
      canDeliver: false,
      deliveredWithIssues: false
    }
  }
  return {
    label: '等待处理',
    summary: '尚无 QA 结论。',
    nextAction: '继续当前任务',
    tone: 'neutral',
    canDeliver: false,
    deliveredWithIssues: false
  }
}

export function deliverableOutcomePresentation(task: DeliverableTask): QaOutcomePresentation {
  const deliveredWithIssues = Boolean(
    task.delivered_with_issues
    || task.status === 'failed'
    || task.qa_status === 'failed'
    || Number(task.qa_hard_errors || 0) > 0
  )
  if (deliveredWithIssues) {
    const hasDelivery = Boolean(task.files.final?.download_url || task.files.package?.download_url)
    const hasQaSummary = Boolean(task.files.qa_summary?.download_url)
    if (!hasDelivery) {
      return {
        label: '待生成带问题交付',
        summary: '仍有 QA 问题。生成交付时会附带问题摘要，并将归档标记为待复核；建议先修复。',
        nextAction: '生成交付或先修复',
        tone: 'warn',
        canDeliver: false,
        deliveredWithIssues: true
      }
    }
    return {
      label: hasQaSummary ? '带问题交付' : '交付不完整',
      summary: hasQaSummary
        ? '仍有 QA 问题。交付文件包含问题摘要，归档标记为待复核；建议修复后再作为标准交付。'
        : '历史交付缺少 QA 问题摘要，当前文件不完整。',
      nextAction: hasQaSummary ? '下载并复核' : '重新生成交付',
      tone: 'warn',
      canDeliver: hasQaSummary,
      deliveredWithIssues: true
    }
  }
  return {
    label: '标准交付',
    summary: 'QA 已通过，交付结果可作为项目后续翻译参考。',
    nextAction: '下载交付文件',
    tone: 'ready',
    canDeliver: true,
    deliveredWithIssues: false
  }
}

export function referenceAuditSummary(state?: ReferenceAuditState | null): string {
  if (!state) return '翻译启动后会显示归档参考命中情况。'
  const entries = Number(state.archive_entries || 0)
  const rows = Number(state.reference_hit_rows || 0)
  const hits = Number(state.reference_hits || 0)
  if (!entries) return '项目归档暂无可用于当前语言的参考译文。'
  if (!hits) return `已检索 ${entries} 条项目译文，当前原文没有命中。`
  return `已检索 ${entries} 条项目译文，${rows} 行命中，共采用 ${hits} 条参考。`
}

export function lineProofreadStage(state?: LineProofreadState | null): 'idle' | 'reviewed' | 'applied' {
  if (!state) return 'idle'
  return Number(state.applied || 0) > 0 ? 'applied' : 'reviewed'
}
