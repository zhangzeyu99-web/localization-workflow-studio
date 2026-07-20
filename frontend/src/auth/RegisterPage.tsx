import React, { useRef, useState } from 'react'
import { Languages, UserPlus } from 'lucide-react'
import { useAuth } from './AuthContext'

export function RegisterPage({ onLogin }: { onLogin: () => void }) {
  const { register } = useAuth()
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submittingRef = useRef(false)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submittingRef.current) return
    const normalizedUsername = username.trim()
    const normalizedDisplayName = displayName.trim()
    const validationError = !normalizedUsername
      ? '请输入用户名。'
      : normalizedUsername.length > 128
        ? '用户名不能超过 128 个字符。'
        : normalizedDisplayName.length > 128
          ? '显示名称不能超过 128 个字符。'
          : password.length < 8 || password.length > 128
            ? '密码长度必须为 8 到 128 个字符。'
            : password !== passwordConfirm
              ? '两次输入的密码不一致。'
              : ''
    if (validationError) {
      setError(validationError)
      return
    }
    submittingRef.current = true
    setBusy(true)
    setError('')
    try {
      const result = await register(normalizedUsername, normalizedDisplayName, password)
      if (!result.ok && !result.stale) setError(result.detail || '注册失败，请重试。')
    } finally {
      submittingRef.current = false
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="brand-lockup auth-brand">
          <span className="brand-mark"><Languages size={22} aria-hidden="true" /></span>
          <div>
            <h1>创建账号</h1>
            <p>注册后以普通成员权限进入，管理员可以调整账号权限。</p>
          </div>
        </div>
        <label className="field-label" htmlFor="register-username">用户名</label>
        <input id="register-username" value={username} onChange={(event) => { setUsername(event.target.value); setError('') }} disabled={busy} autoFocus autoComplete="username" data-testid="register-username" />
        <label className="field-label" htmlFor="register-display-name">显示名称（可选）</label>
        <input id="register-display-name" value={displayName} onChange={(event) => { setDisplayName(event.target.value); setError('') }} disabled={busy} autoComplete="nickname" data-testid="register-display-name" />
        <label className="field-label" htmlFor="register-password">密码</label>
        <input id="register-password" type="password" value={password} onChange={(event) => { setPassword(event.target.value); setError('') }} disabled={busy} autoComplete="new-password" data-testid="register-password" />
        <label className="field-label" htmlFor="register-password-confirm">确认密码</label>
        <input id="register-password-confirm" type="password" value={passwordConfirm} onChange={(event) => { setPasswordConfirm(event.target.value); setError('') }} disabled={busy} autoComplete="new-password" data-testid="register-password-confirm" />
        {error ? <div className="inline-status error" role="alert" data-testid="register-error">{error}</div> : null}
        <button className="btn btn-primary auth-submit" disabled={busy} data-testid="register-submit">
          <UserPlus size={16} aria-hidden="true" />{busy ? '注册中...' : '创建账号'}
        </button>
        <button type="button" className="auth-switch" data-testid="show-login" onClick={onLogin}>
          已有账号？返回登录
        </button>
      </form>
    </div>
  )
}
