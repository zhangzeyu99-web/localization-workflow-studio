import type { QualityIssue, Run } from '../../types'
import { qaPendingIssueCount, qaRunTagClass, qaStatusBadge } from './QaIssuePanel'

export function TaskRunSummary({
  run,
  issues = [],
  projectHardErrors
}: {
  run: Run
  issues?: QualityIssue[]
  projectHardErrors?: number
}) {
  const title = run.kind === 'qa' ? '最近校对任务' : run.kind === 'translation' ? '最近翻译任务' : '最近任务'
  const issueCount = qaPendingIssueCount(run, issues)
  const issueText = run.kind === 'qa'
    ? (run.status === 'passed' ? 'QA 已通过，可交付' : issueCount ? `QA 未通过，待处理 ${issueCount} 条` : qaStatusBadge(run.status))
    : (issueCount ? `待处理问题 ${issueCount} 条` : '无待处理问题')
  const projectGate = typeof projectHardErrors === 'number' ? `，项目规则必须修复 ${projectHardErrors}` : ''
  return (
    <div className="task-summary">
      <div>
        <strong>{title}</strong>
        <span>{new Date(run.created_at).toLocaleString()}</span>
      </div>
      <div>
        <span className={`tag ${qaRunTagClass(run)}`}>{qaStatusBadge(run.status)}</span>
        <span>{issueText}{projectGate}</span>
      </div>
    </div>
  )
}
