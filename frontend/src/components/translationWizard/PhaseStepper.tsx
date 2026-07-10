import { Check, ChevronRight } from 'lucide-react'

const phases = [
  { label: '准备', detail: '资料、分析、术语', from: 1, to: 3 },
  { label: '输入', detail: '判定、候选、语言', from: 4, to: 6 },
  { label: '处理', detail: '翻译、QA', from: 7, to: 8 },
  { label: '交付', detail: '生成与下载', from: 9, to: 9 }
]

export function PhaseStepper({
  step,
  steps,
  skippedSteps = [],
  onStepChange
}: {
  step: number
  steps: string[]
  skippedSteps?: number[]
  onStepChange: (step: number) => void
}) {
  return (
    <nav className="phase-stepper" aria-label="任务进度">
      <div className="phase-list">
        {phases.map((phase, index) => {
          const active = step >= phase.from && step <= phase.to
          const done = step > phase.to
          return (
            <button
              key={phase.label}
              type="button"
              className={`phase-item ${active ? 'active' : ''} ${done ? 'done' : ''}`}
              onClick={() => onStepChange(active ? step : phase.from)}
              aria-current={active ? 'step' : undefined}
            >
              <span className="phase-index">{done ? <Check size={14} aria-hidden="true" /> : index + 1}</span>
              <span><strong>{phase.label}</strong><small>{phase.detail}</small></span>
              {index < phases.length - 1 ? <ChevronRight className="phase-arrow" size={15} aria-hidden="true" /> : null}
            </button>
          )
        })}
      </div>
      <div className="workflow-substeps" aria-label="全部任务步骤">
        {steps.map((title, index) => {
          const stepNumber = index + 1
          const skipped = skippedSteps.includes(stepNumber) && stepNumber !== step
          return (
            <button
              key={title}
              type="button"
              data-testid={`step-${stepNumber}`}
              className={`substep-item ${stepNumber === step ? 'active' : stepNumber < step ? 'done' : ''} ${skipped ? 'skipped' : ''}`}
              onClick={() => onStepChange(stepNumber)}
              aria-current={stepNumber === step ? 'step' : undefined}
              aria-label={`${stepNumber} ${title}${skipped ? '，已跳过' : ''}`}
            >
              <span>{stepNumber}</span>{title}{skipped ? <em>跳过</em> : null}
            </button>
          )
        })}
      </div>
    </nav>
  )
}
