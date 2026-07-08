import type { AnnouncementTask } from '../../types'

export function CancelAnnouncementTaskModal({ task, busy, onClose, onCancelTask }: { task: AnnouncementTask; busy: boolean; onClose: () => void; onCancelTask: (task: AnnouncementTask) => void }) {
  return (
    <div className="modal-mask show">
      <div className="modal delete-project-modal" role="alertdialog" aria-modal="true" aria-labelledby="cancel-announcement-title">
        <h3 id="cancel-announcement-title">⚠️ 取消公告任务</h3>
        <p>你正在取消 <strong>{task.title || task.id}</strong>。</p>
        <div className="delete-warning">
          <strong>取消后不再显示在活跃公告任务里</strong>
          <span>已生成的过程产物和审计记录会保留；如果要重新处理，请新建公告任务。</span>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>返回</button>
          <button type="button" className="btn btn-danger" disabled={busy} onClick={() => onCancelTask(task)}>确认取消</button>
        </div>
      </div>
    </div>
  )
}
