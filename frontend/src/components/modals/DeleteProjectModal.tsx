import { AlertTriangle } from 'lucide-react'
import type { Project } from '../../types'

export function DeleteProjectModal({ project, busy, onClose, onDelete }: { project: Project; busy: boolean; onClose: () => void; onDelete: (project: Project) => void }) {
  return (
    <div className="modal-mask show">
      <div className="modal delete-project-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-project-title">
        <h3 id="delete-project-title" className="icon-title"><AlertTriangle size={18} aria-hidden="true" />删除项目</h3>
        <p>你正在删除 <strong>{project.icon ? `${project.icon} ` : ''}{project.name}</strong>。</p>
        <div className="delete-warning">
          <strong>此操作不可撤销</strong>
          <span>会删除该项目的任务、术语、译文归档、公告任务、产物记录和本地项目文件。</span>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>取消</button>
          <button type="button" className="btn btn-danger" disabled={busy} onClick={() => onDelete(project)}>确认删除</button>
        </div>
      </div>
    </div>
  )
}
