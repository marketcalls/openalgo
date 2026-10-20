import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Simulators } from './Simulators'

describe('Simulators sub-day horizon', () => {
  it('disables time advancement when the strategy is already at expiry', () => {
    render(
      <Simulators
        spotShiftPct={0}
        ivShiftPct={0}
        daysElapsed={0}
        maxDays={0}
        onSpotShiftChange={vi.fn()}
        onIvShiftChange={vi.fn()}
        onDaysElapsedChange={vi.fn()}
        onReset={vi.fn()}
      />
    )

    expect(screen.getByRole('slider', { name: 'Time forward' })).toBeDisabled()
  })

  it('formats very short expiries in minutes instead of rounding both ends to zero hours', () => {
    render(
      <Simulators
        spotShiftPct={0}
        ivShiftPct={0}
        daysElapsed={0}
        maxDays={2 / (24 * 60)}
        onSpotShiftChange={vi.fn()}
        onIvShiftChange={vi.fn()}
        onDaysElapsedChange={vi.fn()}
        onReset={vi.fn()}
      />
    )

    expect(screen.getByText('+2m')).toBeVisible()
    expect(screen.queryAllByText('+0h')).toHaveLength(0)
  })

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
    expect(timeSlider).toHaveAttribute('max', '6')
    expect(timeSlider).toHaveAttribute('step', '1')
    fireEvent.change(timeSlider, { target: { value: '6' } })
    expect(onDaysElapsedChange).toHaveBeenCalledWith(0.25)
  })

  it.each([0.02, 0.23])('partitions a %s-day maximum into reachable sub-hour steps', (maxDays) => {
    const onDaysElapsedChange = vi.fn()
    render(
      <Simulators
        spotShiftPct={0}
        ivShiftPct={0}
        daysElapsed={0}
        maxDays={maxDays}
        onSpotShiftChange={vi.fn()}
        onIvShiftChange={vi.fn()}
        onDaysElapsedChange={onDaysElapsedChange}
        onReset={vi.fn()}
      />
    )

    const timeSlider = screen.getAllByRole('slider')[2]
    const partitions = Math.ceil(maxDays / (1 / 24))

    expect(timeSlider).toHaveAttribute('min', '0')
    expect(timeSlider).toHaveAttribute('max', partitions.toString())
    expect(timeSlider).toHaveAttribute('step', '1')

    fireEvent.change(timeSlider, { target: { value: partitions.toString() } })
    expect(onDaysElapsedChange).toHaveBeenLastCalledWith(maxDays)
  })

  it('preserves quarter-day steps for day-mode horizons', () => {
    const onDaysElapsedChange = vi.fn()
    render(
      <Simulators
        spotShiftPct={0}
        ivShiftPct={0}
        daysElapsed={0}
        maxDays={3.5}
        onSpotShiftChange={vi.fn()}
        onIvShiftChange={vi.fn()}
        onDaysElapsedChange={onDaysElapsedChange}
        onReset={vi.fn()}
      />
    )

    const timeSlider = screen.getAllByRole('slider')[2]
    expect(timeSlider).toHaveAttribute('step', '0.25')
    fireEvent.change(timeSlider, { target: { value: '3.5' } })
    expect(onDaysElapsedChange).toHaveBeenLastCalledWith(3.5)
  })
})
