import React from 'react'
import { Folder } from 'lucide-react'
import type { Project } from '../../types'
import { projectActiveTaskCount, visibleAnnouncementTaskCount } from '../../domain/projectActivity'

function ProjectListItemImpl({
  project, isActive, isDeleteHold, canDelete, onPointerDown, onPointerUp, onPointerLeave, onPointerCancel, onSelect
}: {
  project: Project,
  isActive: boolean,
  isDeleteHold: boolean,
  canDelete: boolean,
  onPointerDown: (project: Project, event: React.PointerEvent<HTMLButtonElement>) => void,
  onPointerUp: () => void,
  onPointerLeave: () => void,
  onPointerCancel: () => void,
  onSelect: (project: Project, event: React.MouseEvent<HTMLButtonElement>) => void
}) {
  return (
    <button
      className={`project-item ${isActive ? 'active' : ''} ${isDeleteHold ? 'delete-hold' : ''}`}
      title={canDelete ? '点击切换项目；长按删除项目' : '点击切换项目'}
      onPointerDown={canDelete ? (event) => onPointerDown(project, event) : undefined}
      onPointerUp={canDelete ? onPointerUp : undefined}
      onPointerLeave={canDelete ? onPointerLeave : undefined}
      onPointerCancel={canDelete ? onPointerCancel : undefined}
      onContextMenu={(event) => event.preventDefault()}
      onClick={(event) => onSelect(project, event)}
    >
      <span className="pname"><Folder size={15} aria-hidden="true" />{project.name}</span>
      <span className="pmeta">语言包 {project.stats.language_tasks ?? ((project.stats.translation_runs || 0) + (project.stats.qa_runs || 0))} · 公告 {visibleAnnouncementTaskCount(project)} · 归档 {project.stats.archived_rows || 0}</span>
      {projectActiveTaskCount(project) ? <span className="ptag ptag-live">后台 {projectActiveTaskCount(project)}</span> : null}
      {project.type ? <span className="ptag">{project.type}</span> : null}
    </button>
  )
}

export const ProjectListItem = React.memo(ProjectListItemImpl)
