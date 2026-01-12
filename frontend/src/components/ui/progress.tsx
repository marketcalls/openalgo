import type * as React from 'react'

import { cn } from '@/lib/utils'

interface ProgressProps extends React.ComponentProps<'div'> {
  value?: number
  max?: number
}

function Progress({ className, value = 0, max = 100, ...props }: ProgressProps) {
  const percentage = Math.min(Math.max((value / max) * 100, 0), 100)

  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      data-slot="progress"
      className={cn('bg-secondary relative h-4 w-full overflow-hidden rounded-full', className)}
      {...props}
    >
      <div
        data-slot="progress-indicator"
        className={cn(
          'bg-primary h-full transition-all duration-300 ease-in-out',
          percentage >= 80 && 'bg-green-500',
          percentage >= 50 && percentage < 80 && 'bg-yellow-500',
          percentage > 0 && percentage < 50 && 'bg-red-500'
        )}
        style={{ width: `${percentage}%` }}
      />
    </div>
  )
}

export { Progress }
