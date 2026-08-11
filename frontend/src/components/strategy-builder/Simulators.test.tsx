import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Simulators } from './Simulators'

describe('Simulators sub-day horizon', () => {
  it('exposes remaining hours without offering an unreachable +1d value', () => {
    const onDaysElapsedChange = vi.fn()
    render(
      <Simulators
        spotShiftPct={0}
        ivShiftPct={0}
        daysElapsed={0}
        maxDays={0.25}
        onSpotShiftChange={vi.fn()}
        onIvShiftChange={vi.fn()}
        onDaysElapsedChange={onDaysElapsedChange}
        onReset={vi.fn()}
      />
    )

    expect(screen.getByText('Hours Forward')).toBeVisible()
    expect(screen.getByText('+6h')).toBeVisible()
    expect(screen.queryByText('+1d')).not.toBeInTheDocument()

    const timeSlider = screen.getAllByRole('slider')[2]
    expect(timeSlider).toHaveAttribute('max', '0.25')
    expect(timeSlider).toHaveAttribute('step', `${1 / 24}`)
    fireEvent.change(timeSlider, { target: { value: '0.25' } })
    expect(onDaysElapsedChange).toHaveBeenCalledWith(0.25)
  })
})
