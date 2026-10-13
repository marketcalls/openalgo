import { describe, expect, it } from 'vitest'
import { numberProblem, pickedPrice } from './inputValidation'

describe('typed study numbers', () => {
  const length = { type: 'number', min: 1, max: 500, step: 1 }

  it('accepts a number inside the bounds', () => {
    expect(numberProblem(length, 14)).toBeNull()
    expect(numberProblem({ type: 'number', step: 0.5 }, 2.5)).toBeNull()
    expect(numberProblem({ type: 'price' }, 24567.85)).toBeNull()
  })

  it('names the problem the way a trader reads it', () => {
    expect(numberProblem(length, '')).toBe('Enter a number')
    expect(numberProblem(length, Number.NaN)).toBe('Enter a number')
    expect(numberProblem(length, 0)).toBe('The lowest allowed is 1')
    expect(numberProblem(length, 501)).toBe('The highest allowed is 500')
    expect(numberProblem(length, 14.5)).toBe('Use a whole number')
  })

  it('leaves inputs that are not numbers to their own controls', () => {
    expect(numberProblem({ type: 'text' }, '')).toBeNull()
    expect(numberProblem({ type: 'select' }, 'x')).toBeNull()
  })
})

describe('a picked price', () => {
  it('keeps the digits that mean something at its size', () => {
    expect(pickedPrice(24567.834)).toBe(24567.83)
    expect(pickedPrice(0.000123456789)).toBe(0.000123457)
  })
})
