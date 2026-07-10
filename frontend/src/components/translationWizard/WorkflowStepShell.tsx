import React from 'react'

export function WorkflowStepShell({
  stepLabel,
  title,
  description,
  status,
  statusTone = 'neutral',
  nextAction,
  children,
  side
}: {
  stepLabel: string
  title: string
  description: string
  status: string
  statusTone?: 'neutral' | 'info' | 'ready' | 'warn' | 'blocked' | 'running'
  nextAction: string
  children: React.ReactNode
  side: React.ReactNode
}) {
  return (
    <div className="workflow-step-shell">
      <div className="workflow-step-head">
        <div>
          <span className="badge">{stepLabel}</span>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <div className={`workflow-step-status ${statusTone}`}>
          <span>当前状态</span>
          <strong>{status}</strong>
          <em>{nextAction}</em>
        </div>
      </div>
      <div className="workflow-step-grid">
        <div className="workflow-primary">{children}</div>
        <aside className="workflow-side">{side}</aside>
      </div>
    </div>
  )
}

export function WorkflowSideCard({
  title,
  children,
  tone = 'neutral'
}: {
  title: string
  children: React.ReactNode
  tone?: 'neutral' | 'ready' | 'warn' | 'blocked'
}) {
  return (
    <section className={`workflow-side-card ${tone}`}>
      <strong>{title}</strong>
      {children}
    </section>
  )
}

export function WorkflowFactList({ items }: { items: { label: string; value: React.ReactNode }[] }) {
  return (
    <div className="workflow-fact-list">
      {items.map((item) => (
        <div key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  )
}
