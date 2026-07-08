// Split out of AnnouncementWorkflow.tsx: this is the small "live status" card
// shown unconditionally on the project overview page, so it (and the tiny
// helpers it needs) must stay eagerly bundled. Everything else in
// AnnouncementWorkflow.tsx (the full AnnouncementWizard flow) is only reached
// from the "announcement" view and is loaded via React.lazy in main.tsx;
// keeping this panel in its own module lets that lazy chunk actually split
// instead of being pulled back into the main bundle through this import.
import { announcementStatusLabel } from '../../domain/announcementText'
import { normalizeLanguageArray, languageSpec } from '../../languages'
import type { AnnouncementTask } from '../../types'

export function activeAnnouncementTasks(tasks: AnnouncementTask[]): AnnouncementTask[] {
  return tasks.filter((task) => task.status !== 'canceled')
}

export function announcementTaskCanCancel(task: AnnouncementTask): boolean {
  return !['delivered', 'canceled'].includes(task.status || '')
}

export function announcementLanguageSummary(task: AnnouncementTask): string {
  const languages = normalizeLanguageArray(task.selected_languages || [])
  return languages.length ? `目标语言：${languages.map((lang) => languageSpec(lang).short).join(' / ')}` : '目标语言：待识别'
}

export function AnnouncementProjectPanel({
  tasks,
  holdTaskId,
  onStartAnnouncement,
  onStartTask,
  onBeginCancelHold,
  onCancelHold
}: {
  tasks: AnnouncementTask[]
  holdTaskId: string
  onStartAnnouncement: () => void
  onStartTask: (task: AnnouncementTask) => void
  onBeginCancelHold: (task: AnnouncementTask) => void
  onCancelHold: () => void
}) {
  const activeTasks = activeAnnouncementTasks(tasks)
  const latest = activeTasks[0]
  return (
    <div className="card tight announcement-project-panel">
      <div className="card-title">
        <div className="left">📣 公告任务 / 外文本</div>
        <button className="btn btn-ghost btn-sm" onClick={onStartAnnouncement}>进入公告工作流</button>
      </div>
      {!activeTasks.length ? (
        <div className="panel-desc">暂无公告任务。公告翻译归属于当前项目，用项目术语、QA归档和项目提示词约束游戏外文本。</div>
      ) : (
        <div className="announcement-task-list">
          {activeTasks.slice(0, 4).map((task) => {
            const isDelivered = task.status === 'delivered'
            return (
              <div
                key={task.id}
                className={`announcement-task-row ${holdTaskId === task.id ? 'cancel-hold' : ''}`}
                onPointerDown={(event) => { if (event.button === 0 && announcementTaskCanCancel(task)) onBeginCancelHold(task) }}
                onPointerUp={onCancelHold}
                onPointerLeave={onCancelHold}
                onPointerCancel={onCancelHold}
              >
                <div>
                  <strong>{task.title || task.id}</strong>
                  <span>{task.source_format?.toUpperCase() || '-'} · STEP {task.current_step || 1}/9 · {announcementStatusLabel(task.status)}</span>
                  <span>{announcementLanguageSummary(task)}</span>
                </div>
                <button className="btn btn-ghost btn-sm" onPointerDown={(event) => event.stopPropagation()} onClick={() => onStartTask(task)}>{isDelivered ? '查看交付' : '继续'}</button>
              </div>
            )
          })}
          {latest ? <div className="panel-desc">最近任务：{latest.title || latest.id}</div> : null}
        </div>
      )}
    </div>
  )
}
