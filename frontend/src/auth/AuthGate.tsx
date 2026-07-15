import React from 'react'
import { useAuth } from './AuthContext'
import { LoginPage } from './LoginPage'
import { ChangePasswordPage } from './ChangePasswordPage'

// Sits above <App/> in main.tsx. authEnabled=false (local/off deployments)
// resolves to 'authenticated' as soon as the initial GET /api/auth/me
// response lands (see AuthContext's applyMe), so this gate is a no-op there
// -- the brief 'loading' flash is the only visible change from today.
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  if (status === 'loading') {
    return (
      <div className="auth-screen" data-testid="auth-loading">
        <span className="loading" />
      </div>
    )
  }
  if (status === 'anonymous') return <LoginPage />
  if (status === 'must-change-password') return <ChangePasswordPage />
  return <>{children}</>
}
