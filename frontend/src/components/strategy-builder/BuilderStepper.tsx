import { CheckIcon } from 'lucide-react'
import type { BuilderStep } from '@/types/strategy-builder'

interface BuilderStepperProps {
  currentStep: BuilderStep
  onStepClick: (step: BuilderStep) => void
}

const STEPS: { key: BuilderStep; label: string; num: number }[] = [
  { key: 'basics', label: 'Basics', num: 1 },
  { key: 'legs', label: 'Legs', num: 2 },
  { key: 'risk', label: 'Risk', num: 3 },
  { key: 'review', label: 'Review', num: 4 },
]

const STEP_ORDER: BuilderStep[] = ['basics', 'legs', 'risk', 'review']

export function BuilderStepper({ currentStep, onStepClick }: BuilderStepperProps) {
  const currentIdx = STEP_ORDER.indexOf(currentStep)

  return (
    <nav className="flex items-center justify-center gap-2">
      {STEPS.map((step, idx) => {
        const isComplete = idx < currentIdx
        const isCurrent = idx === currentIdx
        const isClickable = idx <= currentIdx

        return (
          <div key={step.key} className="flex items-center">
            <button
              type="button"
              onClick={() => isClickable && onStepClick(step.key)}
              disabled={!isClickable}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                isCurrent
                  ? 'bg-primary text-primary-foreground'
                  : isComplete
                    ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300 cursor-pointer'
                    : 'bg-muted text-muted-foreground'
              }`}
            >
              {isComplete ? (
                <CheckIcon className="h-3 w-3" />
              ) : (
                <span className="w-4 text-center">{step.num}</span>
              )}
              {step.label}
            </button>
            {idx < STEPS.length - 1 && (
              <div
                className={`w-8 h-0.5 mx-1 ${
                  idx < currentIdx ? 'bg-green-400' : 'bg-muted'
                }`}
              />
            )}
          </div>
        )
      })}
    </nav>
  )
}
