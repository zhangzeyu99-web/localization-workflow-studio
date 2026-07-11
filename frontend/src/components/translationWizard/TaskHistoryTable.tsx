import React, { useEffect, useState } from 'react'
import { HISTORY_TABLE_PAGE_SIZE, pagedRows } from '../../assetTableState'
import { artifactDownloadHref, runArtifacts } from '../../domain/artifacts'
import { formatDate } from '../../domain/format'
import { normalizeLanguageCode, languageSpec } from '../../languages'
import { runStatusLabel, runStatusTagClass } from '../../uiText'
import type { HistoryKind, Project } from '../../types'
import { downloadableArtifact, RunDetail, runProcessedLabel, runTaskSummary } from './RunDetail'
import { WideTablePager } from '../assets/ProjectAssetTabs'

function TaskHistoryTableImpl({ project, kind, title }: { project: Project; kind: HistoryKind; title: string }) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const runs = kind === 'all' ? (project.runs || []) : (project.runs || []).filter((run) => run.kind === kind)
  const selectedRun = runs.find((run) => run.id === selectedRunId) || null
  const totalPages = Math.max(1, Math.ceil(runs.length / HISTORY_TABLE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const currentRuns = pagedRows(runs, currentPage, HISTORY_TABLE_PAGE_SIZE)

  useEffect(() => {
    setPage(1)
  }, [kind, runs.length])

  return (
    <div className="card history-card">
      <div className="card-title">
        <div className="left">{title}</div>
      </div>
      <div className="table-scroll history-table-scroll">
        <table className="history-table">
          <thead>
            <tr><th>日期</th><th>任务名称</th><th>目标语言</th><th>处理量</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            {currentRuns.map((run) => {
              const artifacts = runArtifacts(project, run.id)
              const download = downloadableArtifact(artifacts, kind)
              const task = runTaskSummary(project, run)
              return (
                <tr key={run.id}>
                  <td>{formatDate(run.created_at)}</td>
                  <td>{task.taskType} · {task.taskLabel}</td>
                  <td>{run.language ? languageSpec(normalizeLanguageCode(run.language) || 'en').short : '-'}</td>
                  <td>{runProcessedLabel(run)}</td>
                  <td><span className={`tag ${runStatusTagClass(run.status)}`}>{runStatusLabel(run.status)}</span></td>
                  <td>
                    <div className="link-actions">
                      <button className="link-button" onClick={() => setSelectedRunId(selectedRunId === run.id ? null : run.id)}>查看</button>
                      {download ? <a href={artifactDownloadHref(download, project.id)}>{kind === 'qa' ? '下载校对结果' : '下载已译表'}</a> : <span className="muted-inline" title="该任务暂无可下载结果">无下载</span>}
                    </div>
                  </td>
                </tr>
              )
            })}
            {!runs.length ? <tr><td colSpan={6} className="muted">暂无历史记录。</td></tr> : null}
          </tbody>
        </table>
      </div>
      {runs.length > HISTORY_TABLE_PAGE_SIZE ? (
        <WideTablePager testIdPrefix="history" page={currentPage} totalRows={runs.length} onPageChange={setPage} pageSize={HISTORY_TABLE_PAGE_SIZE} />
      ) : null}
      {selectedRun ? <RunDetail project={project} run={selectedRun} kind={kind} /> : null}
    </div>
  )
}

export const TaskHistoryTable = React.memo(TaskHistoryTableImpl)
