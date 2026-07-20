import React, { useState } from 'react'
import { useAuth } from './AuthContext'
import { LoginPage } from './LoginPage'
import { RegisterPage } from './RegisterPage'
import { ChangePasswordPage } from './ChangePasswordPage'

// Sits above <App/> in main.tsx. authEnabled=false (local/off deployments)
// resolves to 'authenticated' as soon as the initial GET /api/auth/me
// response lands (see AuthContext's applyMe), so this gate is a no-op there
// -- the brief 'loading' flash is the only visible change from today.
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { status, refresh } = useAuth()
  const [anonymousView, setAnonymousView] = useState<'login' | 'register'>('login')
  if (status === 'loading') {
    return (
      <div className="auth-screen" data-testid="auth-loading">
        <span className="loading" />
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className="auth-screen" data-testid="auth-bootstrap-error">
        <section className="auth-card auth-bootstrap-error-card">
          <div className="auth-brand">
            <div>
              <h1>暂时无法连接工作台</h1>
              <p>请确认后端服务已启动，然后重试。</p>
            </div>
          </div>
          <button className="btn btn-primary auth-submit" data-testid="auth-retry" onClick={() => void refresh()}>
            重新连接
          </button>
        </section>
      </div>
    )
  }
  if (status === 'anonymous') {
    return anonymousView === 'register'
      ? <RegisterPage onLogin={() => setAnonymousView('login')} />
      : <LoginPage onRegister={() => setAnonymousView('register')} />
  }
  if (status === 'must-change-password') return <ChangePasswordPage />
  return <>{children}</>
}
