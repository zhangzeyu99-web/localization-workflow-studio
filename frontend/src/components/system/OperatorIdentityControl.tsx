import { useCallback, useEffect, useRef, useState } from 'react'
import { UserRound } from 'lucide-react'

import { getOperatorName, onOpenOperatorIdentityRequest, onOperatorIdentityChange, setOperatorName } from '../../operator'

export function OperatorIdentityControl() {
  const [operatorName, setCurrentOperatorName] = useState(() => getOperatorName())
  const [draft, setDraft] = useState('')
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const modalRef = useRef<HTMLFormElement | null>(null)
  const lastFocusedRef = useRef<HTMLElement | null>(null)

  const closeDialog = useCallback(() => {
    setOpen(false)
    window.requestAnimationFrame(() => lastFocusedRef.current?.focus())
  }, [])

  const openDialog = useCallback(() => {
    lastFocusedRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setDraft(getOperatorName())
    setError('')
    setOpen(true)
  }, [])

  useEffect(() => onOpenOperatorIdentityRequest(openDialog), [openDialog])
  useEffect(() => onOperatorIdentityChange(() => setCurrentOperatorName(getOperatorName())), [])
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeDialog()
        return
      }
      if (event.key !== 'Tab' || !modalRef.current) return
      const focusable = Array.from(
        modalRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled])')
      )
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [closeDialog, open])

  function save() {
    const trimmed = draft.trim()
    if (!trimmed) {
      setError('请输入昵称。')
      return
    }
    if (!setOperatorName(trimmed)) {
      setError('浏览器无法保存昵称，请检查本地存储权限后重试。')
      return
    }
    closeDialog()
  }

  return (
    <>
      <button
        type="button"
        className="btn btn-ghost operator-identity-trigger"
        data-testid="operator-identity-trigger"
        title={operatorName ? `当前操作人：${operatorName}` : '设置操作人昵称'}
        onClick={openDialog}
      >
        <UserRound size={16} aria-hidden="true" />
        <span className="operator-identity-name">{operatorName || '设置昵称'}</span>
      </button>
      {open ? (
        <div className="modal-mask show" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDialog() }}>
          <form
            ref={modalRef}
            className="modal operator-identity-modal"
            data-testid="operator-identity-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="operator-identity-title"
            aria-describedby="operator-identity-note"
            onSubmit={(event) => { event.preventDefault(); save() }}
          >
            <div className="settings-head">
              <h3 id="operator-identity-title" className="icon-title"><UserRound size={18} aria-hidden="true" />操作人昵称</h3>
              <button type="button" className="btn btn-ghost btn-sm" onClick={closeDialog}>关闭</button>
            </div>
            <label className="operator-identity-field">
              <span>昵称</span>
              <input
                data-testid="operator-name-input"
                value={draft}
                maxLength={40}
                required
                autoFocus
                placeholder="例如：张三"
                aria-invalid={Boolean(error)}
                aria-describedby={error ? 'operator-identity-error' : undefined}
                onChange={(event) => { setDraft(event.target.value); setError('') }}
              />
            </label>
            {error ? <p id="operator-identity-error" className="operator-identity-error" role="alert">{error}</p> : null}
            <p id="operator-identity-note" className="operator-identity-note">线上启动 AI 任务前必须设置。昵称只用于显示任务归属，不是登录账号，也不限制其他操作。</p>
            <div className="settings-actions"><button type="submit" className="btn btn-primary">保存昵称</button></div>
          </form>
        </div>
      ) : null}
    </>
  )
}
