import React, { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { useAuth } from './AuthContext'

const MIN_PASSWORD_LENGTH = 8

export function ChangePasswordPage() {
  const { changePassword, logout, user } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setError(`新密码至少 ${MIN_PASSWORD_LENGTH} 位。`)
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致。')
      return
    }
    setBusy(true)
    setError('')
    try {
      const result = await changePassword(currentPassword, newPassword)
      if (!result.ok) setError(result.detail || '修改密码失败，请重试。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit} noValidate>
        <h3 className="icon-title"><KeyRound size={18} aria-hidden="true" />首次登录请修改密码</h3>
        <p>账号 {user?.username || ''} 需要在首次登录后设置新密码，才能继续使用工作台。</p>
        <label className="field-label">当前密码（管理员分配的初始密码）</label>
        <input
          type="password"
          value={currentPassword}
          onChange={(event) => { setCurrentPassword(event.target.value); setError('') }}
          disabled={busy}
          autoFocus
          autoComplete="current-password"
          data-testid="change-password-current"
        />
        <label className="field-label">新密码（至少 {MIN_PASSWORD_LENGTH} 位）</label>
        <input
          type="password"
          value={newPassword}
          onChange={(event) => { setNewPassword(event.target.value); setError('') }}
          disabled={busy}
          autoComplete="new-password"
          data-testid="change-password-new"
        />
        <label className="field-label">确认新密码</label>
        <input
          type="password"
          value={confirmPassword}
          onChange={(event) => { setConfirmPassword(event.target.value); setError('') }}
          disabled={busy}
          autoComplete="new-password"
          data-testid="change-password-confirm"
        />
        {error ? <div className="inline-status error" data-testid="change-password-error">{error}</div> : null}
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => { void logout() }}>退出登录</button>
          <button className="btn btn-primary" disabled={busy} data-testid="change-password-submit">{busy ? '保存中...' : '保存并继续'}</button>
        </div>
      </form>
    </div>
  )
}
