import { describe, expect, it } from 'vitest'
import { render, screen } from '@/test/test-utils'
import { MonthlyReturnsHeatmap } from './MonthlyReturnsHeatmap'

describe('MonthlyReturnsHeatmap', () => {
  it('renders fractional returns as percentages and leaves missing cells blank', () => {
    const { container } = render(
      <MonthlyReturnsHeatmap
        years={['2024']}
        columns={['Jan', 'Feb', 'Mar']}
        values={[[0.123, -0.045, null]]}
      />
    )

    expect(screen.getByText('12.3')).toBeInTheDocument()
    expect(screen.getByText('-4.5')).toBeInTheDocument()
    const cells = container.querySelectorAll('.rounded-md')
    expect(cells[2]).toHaveTextContent('')
    expect(cells[2]).toHaveStyle({ background: 'transparent' })
  })
})
