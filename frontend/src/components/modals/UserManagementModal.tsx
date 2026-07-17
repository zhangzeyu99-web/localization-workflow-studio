import { useEffect, useState } from 'react'
import { KeyRound, UserCog, UserPlus } from 'lucide-react'
import { api } from '../../apiClient'
import { roleBadgeLabel } from '../../auth/roleText'

type UserRole = 'admin' | 'ops' | 'member'
type UserStatus = 'active' | 'disabled'

type ManagedUser = {
  id: string
  username: string
  display_name: string
  role: UserRole
  status: UserStatus
  last_login_at?: string | null
}

const initialCreate = {
  username: '',
  displayName: '',
  role: 'member' as UserRole,
  password: '',
}

function dateText(value?: string | null): string {
  if (!value) return '从未登录'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN')
}

export function UserManagementModal({ currentUserId, onClose }: { currentUserId: string; onClose: () => void }) {
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [createDraft, setCreateDraft] = useState(initialCreate)
  const [resetTarget, setResetTarget] = useState<ManagedUser | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function loadUsers() {
    setUsers(await api<ManagedUser[]>('/api/users', undefined, '加载用户'))
  }

  useEffect(() => {
    void loadUsers().catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function createUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const username = createDraft.username.trim()
    if (!username || username.length > 128 || createDraft.password.length < 8) {
      setError('请填写不超过 128 个字符的用户名，并提供至少 8 位的初始密码。')
      return
    }
    await run(async () => {
      await api<ManagedUser>('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          display_name: createDraft.displayName.trim(),
          role: createDraft.role,
          initial_password: createDraft.password,
        }),
      }, '创建用户')
      setNotice(`账号 ${username} 已创建。初始密码：${createDraft.password}；首次登录需改密，请安全告知用户。`)
      setCreateDraft(initialCreate)
      await loadUsers()
    })
  }

  async function patchUser(user: ManagedUser, updates: Partial<Pick<ManagedUser, 'role' | 'status'>>) {
    await run(async () => {
      await api<ManagedUser>(`/api/users/${user.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      }, '更新用户')
      setNotice(`账号 ${user.username} 已更新。`)
      await loadUsers()
    })
  }

  async function submitReset(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!resetTarget || resetPassword.length < 8) {
      setError('重置密码至少 8 位。')
      return
    }
    await run(async () => {
      await api(`/api/users/${resetTarget.id}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ initial_password: resetPassword }),
      }, '重置密码')
      setNotice(`账号 ${resetTarget.username} 的密码已重置为：${resetPassword}；下次登录需改密，请安全告知用户。`)
      setResetTarget(null)
      setResetPassword('')
      await loadUsers()
    })
  }

  return (
    <div className="modal-mask show">
      <div className="modal management-modal" role="dialog" aria-modal="true" aria-labelledby="user-management-title" data-testid="user-management-modal">
        <div className="settings-head">
          <h3 id="user-management-title" className="icon-title"><UserCog size={18} aria-hidden="true" />用户管理</h3>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
        </div>

        <form className="management-create-form" onSubmit={createUser}>
          <strong className="icon-title"><UserPlus size={16} aria-hidden="true" />新建用户</strong>
          <div className="management-form-grid">
            <label><span>用户名</span><input data-testid="create-user-username" maxLength={128} value={createDraft.username} onChange={(event) => setCreateDraft((draft) => ({ ...draft, username: event.target.value }))} /></label>
            <label><span>显示名</span><input data-testid="create-user-display-name" value={createDraft.displayName} onChange={(event) => setCreateDraft((draft) => ({ ...draft, displayName: event.target.value }))} /></label>
            <label><span>角色</span><select data-testid="create-user-role" value={createDraft.role} onChange={(event) => setCreateDraft((draft) => ({ ...draft, role: event.target.value as UserRole }))}><option value="admin">管理员</option><option value="ops">运营</option><option value="member">成员</option></select></label>
            <label><span>初始密码</span><input data-testid="create-user-password" type="password" value={createDraft.password} onChange={(event) => setCreateDraft((draft) => ({ ...draft, password: event.target.value }))} /></label>
          </div>
          <div className="management-form-foot"><span>创建后首次登录必须修改密码。</span><button className="btn btn-primary btn-sm" disabled={busy} data-testid="create-user-submit">创建用户</button></div>
        </form>

        {notice ? <div className="inline-status success" data-testid="initial-password-reminder">{notice}</div> : null}
        {error ? <div className="inline-status error" data-testid="user-management-error">{error}</div> : null}

        <div className="management-list">
          {users.map((managedUser) => (
            <div className="management-row" key={managedUser.id} data-testid={`user-row-${managedUser.username}`}>
              <div className="management-user-main">
                <strong>{managedUser.display_name || managedUser.username}</strong>
                <span>@{managedUser.username} · 最近登录：{dateText(managedUser.last_login_at)}</span>
              </div>
              <span className="badge">{roleBadgeLabel(managedUser.role)}</span>
              <span className={`badge ${managedUser.status === 'active' ? '' : 'danger'}`}>{managedUser.status === 'active' ? '启用' : '停用'}</span>
              <select
                aria-label={`${managedUser.username} 角色`}
                value={managedUser.role}
                disabled={busy || managedUser.id === currentUserId}
                onChange={(event) => { void patchUser(managedUser, { role: event.target.value as UserRole }) }}
              >
                <option value="admin">管理员</option><option value="ops">运营</option><option value="member">成员</option>
              </select>
              <button className="btn btn-ghost btn-sm" disabled={busy || managedUser.id === currentUserId} onClick={() => { void patchUser(managedUser, { status: managedUser.status === 'active' ? 'disabled' : 'active' }) }}>{managedUser.status === 'active' ? '停用' : '启用'}</button>
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => { setResetTarget(managedUser); setResetPassword(''); setError('') }}><KeyRound size={14} aria-hidden="true" />重置密码</button>
              {managedUser.id === currentUserId ? <span className="management-self">当前账号</span> : null}
            </div>
          ))}
        </div>

        {resetTarget ? (
          <form className="management-reset-form" onSubmit={submitReset}>
            <strong>重置 @{resetTarget.username} 的密码</strong>
            <input data-testid="user-reset-password" type="password" autoFocus value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} placeholder="至少 8 位" />
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setResetTarget(null)}>取消</button>
            <button className="btn btn-primary btn-sm" disabled={busy} data-testid="user-reset-submit">确认重置</button>
          </form>
        ) : null}
      </div>
    </div>
  )
}
