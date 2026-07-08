import { useCallback, useRef, useState } from 'react'

export type ConfirmDialogTone = 'neutral' | 'warn'

export interface ConfirmDialogOptions {
  title?: string
  confirmLabel?: string
  // Passing null hides the cancel button, turning the dialog into a single-button alert.
  cancelLabel?: string | null
  tone?: ConfirmDialogTone
}

interface ConfirmModalProps extends ConfirmDialogOptions {
  message: string
  onConfirm: () => void
  onCancel: () => void
}

// Reuses the existing .modal-mask/.modal/.modal-foot classes (see DeleteProjectModal in
// main.tsx) so this fits the current visual language without new CSS structure.
export function ConfirmModal({
  title = '请确认',
  message,
  confirmLabel = '确认',
  cancelLabel = '取消',
  tone = 'neutral',
  onConfirm,
  onCancel
}: ConfirmModalProps) {
  return (
    <div className="modal-mask show">
      <div className="modal confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-modal-title">
        <h3 id="confirm-modal-title">{title}</h3>
        <p className="confirm-modal-message" data-testid="confirm-modal-message">{message}</p>
        <div className="modal-foot">
          {cancelLabel ? (
            <button type="button" className="btn btn-ghost" data-testid="confirm-modal-cancel" onClick={onCancel}>{cancelLabel}</button>
          ) : null}
          <button
            type="button"
            className={`btn ${tone === 'warn' ? 'btn-danger' : 'btn-primary'}`}
            data-testid="confirm-modal-confirm"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

interface ConfirmDialogState extends ConfirmDialogOptions {
  message: string
}

// Async replacement for window.confirm/window.alert: `confirm()` resolves true/false
// once the user picks a button; `alertDialog()` is a single-button variant that always
// resolves true. Render the returned `dialog` element once near the app root.
export function useConfirmDialog() {
  const [state, setState] = useState<ConfirmDialogState | null>(null)
  const resolverRef = useRef<((value: boolean) => void) | null>(null)

  const settle = useCallback((value: boolean) => {
    resolverRef.current?.(value)
    resolverRef.current = null
    setState(null)
  }, [])

  const confirm = useCallback((message: string, options?: ConfirmDialogOptions) => {
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve
      setState({ message, ...options })
    })
  }, [])

  const alertDialog = useCallback((message: string, options?: Omit<ConfirmDialogOptions, 'cancelLabel'>) => {
    return confirm(message, { confirmLabel: '知道了', ...options, cancelLabel: null })
  }, [confirm])

  const dialog = state ? (
    <ConfirmModal
      title={state.title}
      message={state.message}
      confirmLabel={state.confirmLabel}
      cancelLabel={state.cancelLabel}
      tone={state.tone}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  ) : null

  return { confirm, alertDialog, dialog }
}
