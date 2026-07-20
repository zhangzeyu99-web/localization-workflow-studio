import React, { useState } from 'react'
import { Languages, LogIn } from 'lucide-react'
import { useAuth } from './AuthContext'

export function LoginPage({ onRegister }: { onRegister: () => void }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入用户名和密码。')
      return
    }
    setBusy(true)
    setError('')
    try {
      const result = await login(username.trim(), password)
      if (!result.ok && !result.stale) setError(result.detail || '登录失败，请重试。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="brand-lockup auth-brand">
          <span className="brand-mark"><Languages size={22} aria-hidden="true" /></span>
          <div>
            <h1>本地化工作台</h1>
            <p>Localization Workflow Studio</p>
          </div>
        </div>
        <label className="field-label" htmlFor="login-username">用户名</label>
        <input
          id="login-username"
          value={username}
          onChange={(event) => { setUsername(event.target.value); setError('') }}
          disabled={busy}
          autoFocus
          autoComplete="username"
          data-testid="login-username"
        />
        <label className="field-label" htmlFor="login-password">密码</label>
        <input
          id="login-password"
          type="password"
          value={password}
          onChange={(event) => { setPassword(event.target.value); setError('') }}
          disabled={busy}
          autoComplete="current-password"
          data-testid="login-password"
        />
        {error ? <div className="inline-status error" role="alert" data-testid="login-error">{error}</div> : null}
        <button className="btn btn-primary auth-submit" disabled={busy} data-testid="login-submit">
          <LogIn size={16} aria-hidden="true" />{busy ? '登录中...' : '登录'}
        </button>
        <button type="button" className="auth-switch" data-testid="show-register" onClick={onRegister} disabled={busy}>
          没有账号？创建账号
        </button>
      </form>
    </div>
  )
}
