import { issueCountPhrase, runStatusLabel } from '../../uiText'
import type { Artifact, QualityIssue, Run } from '../../types'

export function qaPendingIssueCount(run: Run | null | undefined, issues: QualityIssue[] = []): number {
  if (!run) return 0
  const summary = (run.metadata?.quality_summary || {}) as { hard_errors?: number }
  const hardFromSummary = Number(summary.hard_errors || 0)
  const visibleHardCount = issues.filter((issue) => issue.severity === 'hard').length
  return hardFromSummary || visibleHardCount
}

export function qaStatusBadge(status: string): string {
  if (status === 'passed') return '已通过'
  if (status === 'failed') return '未通过'
  if (status === 'running' || status === 'queued') return '运行中'
  if (status === 'needs_input') return '需处理'
  return status || '未运行'
}

export function qaRunTagClass(run: Run | null | undefined): string {
  if (!run) return 'tag-doing'
  if (run.status === 'passed') return 'tag-done'
  if (run.status === 'failed') return 'tag-warn'
  return 'tag-doing'
}

export function qaRunSummaryText(run: Run | null | undefined, pendingIssueCount = 0): string {
  if (!run) return '尚未运行 QA。请选择译文表后点击“运行 QA”。'
  if (run.status === 'passed') return 'QA 已通过，可以进入交付页生成最终文件。'
  if (run.status === 'failed') return `QA 未通过：发现${issueCountPhrase(pendingIssueCount)}问题。建议先修复并重跑；急需时可带问题摘要交付。`
  if (run.status === 'queued' || run.status === 'running') return 'QA 正在运行，请等待当前任务完成。'
  if (run.status === 'needs_input') return 'QA 需要补充输入后继续。'
  return `当前状态：${runStatusLabel(run.status)}`
}

export function qaRunActionText(run: Run | null | undefined, pendingIssueCount = 0): string {
  if (!run) return '运行 QA'
  if (run.status === 'passed') return '去交付页生成最终文件'
  if (run.status === 'failed') return pendingIssueCount ? '先修复；急需时交付' : '查看 QA 报告后交付'
  if (run.status === 'queued' || run.status === 'running') return '等待任务完成'
  return '按提示补齐输入'
}

export function runDeliveryState(run: Run, visibleArtifacts: Artifact[]): string {
  if (visibleArtifacts.some((artifact) => artifact.kind === 'qa_final_workbook' || artifact.role === 'translation_workbook')) return '可生成最终交付'
  if (run.status === 'passed') return '已通过，等待生成交付文件'
  if (run.status === 'needs_input') return '需要补充输入'
  if (run.status === 'failed') return 'QA 未通过，可带问题摘要交付'
  return '处理中'
}

export function issueTypeLabel(value: string): string {
  const key = String(value || '').toLowerCase()
  const labels: Record<string, string> = {
    term_missing: '术语未命中',
    term_partial_hit: '术语只命中一部分',
    ui_length_overflow: '界面长度超限',
    title_case_overuse: '大小写风格异常',
    placeholder_mismatch: '变量占位符错误',
    tag_mismatch: '标签不一致',
    newline_mismatch: '换行不一致',
    raw_cn: '译文残留中文',
    global_harness: '通用 QA 规则',
    project_harness: '项目规则',
    semantic_qa: '模型语义校对'
  }
  return labels[key] || value || '质量问题'
}

export function severityLabel(value: string): string {
  return String(value).toLowerCase() === 'hard' ? '必须修复' : '建议修复'
}

export function issueSourceLabel(value: string): string {
  const key = String(value || '').toLowerCase()
  if (key === 'global_harness') return '通用规则'
  if (key === 'project_harness') return '项目规则'
  if (key === 'semantic_qa') return '模型校对'
  return value || 'QA'
}

export function issueHumanMessage(issue: QualityIssue): string {
  const sourceTerm = issue.message.match(/for ['"](.+?)['"]/)?.[1]
  const expected = issue.message.match(/expected one of \[(.+?)\]/)?.[1]?.replace(/['"]/g, '').trim()
  if (issue.check_type === 'term_missing' && sourceTerm && expected) {
    return `原文术语「${sourceTerm}」未按项目术语表翻译，建议使用：${expected}。`
  }
  if (issue.check_type === 'term_partial_hit' && sourceTerm && expected) {
    return `原文术语「${sourceTerm}」只翻出了一部分，建议完整使用：${expected}。`
  }
  if (issue.check_type === 'ui_length_overflow') return '译文可能超出按钮、弹窗或移动端 UI 宽度，需要缩短。'
  if (issue.check_type === 'title_case_overuse') return '译文大小写风格可能过度标题化，需要改成更自然的界面文案。'
  return issue.message || issueTypeLabel(issue.check_type)
}

export function IssueSummary({ issues }: { issues: QualityIssue[] }) {
  return (
    <div className="issue-summary">
      <div className="card-title"><div className="left">QA 问题摘要</div></div>
      <IssueGuide issues={issues} editableCount={0} />
      <IssueChips issues={issues} />
      <div className="muted-left">这些问题缺少可直接编辑的表格行定位；请查看 QA 报告，或重新生成带行号的问题列表后再批量修复。</div>
    </div>
  )
}

export function IssueChips({ issues }: { issues: QualityIssue[] }) {
  const counts = issues.reduce<Record<string, number>>((acc, issue) => {
    const key = issueTypeLabel(issue.check_type || issue.source)
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6)
  return (
    <div className="issue-chips">
      {top.map(([name, count]) => <span key={name}>{name}: {count}</span>)}
    </div>
  )
}

export function IssueGuide({ issues, editableCount }: { issues: QualityIssue[]; editableCount: number }) {
  const hard = issues.filter((issue) => issue.severity === 'hard').length
  const soft = issues.filter((issue) => issue.severity !== 'hard').length
  return (
    <div className="issue-guide">
      <div>
        <strong>当前不能作为最终交付</strong>
        <span>{hard} 个必须修复，{soft} 个建议修复；其中 {editableCount} 个可在网页直接改后重跑 QA。</span>
      </div>
      <p>这些是规则 QA 抓到的问题。模拟翻译通常会产生大量术语缺失；正式接入 GPT / Claude 后会按提示词和术语快照翻译，问题量会下降，但不会承诺自动清零，最终仍以“必须修复问题 = 0”作为交付标准。</p>
    </div>
  )
}
