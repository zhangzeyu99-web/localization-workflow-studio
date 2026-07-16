import { useEffect, useState } from 'react'
import { UserMinus, UserPlus, Users } from 'lucide-react'
import { api } from '../../apiClient'
import { roleBadgeLabel } from '../../auth/roleText'
import { useConfirmDialog } from './ConfirmModal'

type ProjectMember = {
  user_id: string
  username: string
  display_name: string
  role: string
}

type AddableUser = {
  id: string
  username: string
  display_name: string
  role: string
}

export function ProjectMembersModal({ projectId, projectName, onClose }: { projectId: string; projectName: string; onClose: () => void }) {
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [addable, setAddable] = useState<AddableUser[]>([])
  const [selectedUserId, setSelectedUserId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { confirm, dialog } = useConfirmDialog()

  async function load() {
    const [nextMembers, nextAddable] = await Promise.all([
      api<ProjectMember[]>(`/api/projects/${projectId}/members`, undefined, '加载项目成员'),
      api<AddableUser[]>(`/api/projects/${projectId}/members/addable`, undefined, '加载可添加用户'),
    ])
    setMembers(nextMembers)
    setAddable(nextAddable)
    setSelectedUserId((value) => nextAddable.some((user) => user.id === value) ? value : (nextAddable[0]?.id || ''))
  }

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [projectId])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError('')
    try {
      await action()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function addMember() {
    if (!selectedUserId) return
    await run(async () => {
      await api(`/api/projects/${projectId}/members`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: selectedUserId }),
      }, '添加成员')
    })
  }

  async function removeMember(member: ProjectMember) {
    const approved = await confirm(`确认从项目“${projectName}”移除 ${member.display_name || member.username}（@${member.username}）？`, {
      title: '移除项目成员',
      confirmLabel: '确认移除',
      tone: 'warn',
    })
    if (!approved) return
    await run(async () => {
      await api(`/api/projects/${projectId}/members/${member.user_id}`, { method: 'DELETE' }, '移除成员')
    })
  }

  return (
    <div className="modal-mask show">
      <div className="modal members-modal" role="dialog" aria-modal="true" aria-labelledby="project-members-title" data-testid="project-members-modal">
        <div className="settings-head">
          <h3 id="project-members-title" className="icon-title"><Users size={18} aria-hidden="true" />项目成员</h3>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
        </div>
        <p>管理“{projectName}”可见成员。管理员默认可访问全部项目，无需加入成员列表。</p>
        <div className="member-add-row">
          <select data-testid="addable-member-select" value={selectedUserId} disabled={busy || !addable.length} onChange={(event) => setSelectedUserId(event.target.value)}>
            {addable.map((user) => <option key={user.id} value={user.id}>{user.display_name || user.username} ({user.username})</option>)}
          </select>
          <button className="btn btn-primary btn-sm" data-testid="add-project-member" disabled={busy || !selectedUserId} onClick={() => { void addMember() }}><UserPlus size={14} aria-hidden="true" />添加成员</button>
        </div>
        {!addable.length ? <div className="muted management-empty">暂无可添加的 active 用户。</div> : null}
        {error ? <div className="inline-status error" data-testid="project-members-error">{error}</div> : null}
        <div className="management-list">
          {members.map((member) => (
            <div className="management-row member-row" key={member.user_id} data-testid={`project-member-${member.username}`}>
              <div className="management-user-main"><strong>{member.display_name || member.username}</strong><span>@{member.username}</span></div>
              <span className="badge">{roleBadgeLabel(member.role)}</span>
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => { void removeMember(member) }}><UserMinus size={14} aria-hidden="true" />移除</button>
            </div>
          ))}
          {!members.length ? <div className="muted management-empty">当前项目还没有成员。</div> : null}
        </div>
      </div>
      {dialog}
    </div>
  )
}
