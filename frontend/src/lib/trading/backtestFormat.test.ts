import { describe, expect, it } from 'vitest'
import { compactMoney, momentText, moneyText, signedMoney, signedPercent } from './backtestFormat'

describe('backtest money and moments, as a trader reads them', () => {
  it('groups rupees the Indian way and drops paise from whole amounts', () => {
    expect(moneyText(100800)).toBe('₹1,00,800')
    expect(moneyText(-500.5)).toBe('-₹500.50')
    expect(moneyText(12450, 'USD')).toBe('$12,450')
  })

  it('compacts the axis to lakh and crore, and keeps smaller rupee amounts whole', () => {
    expect(compactMoney(100800)).toBe('₹1.01L')
    expect(compactMoney(25000000)).toBe('₹2.5Cr')
    expect(compactMoney(85000)).toBe('₹85,000')
    expect(compactMoney(-150000)).toBe('-₹1.5L')
    expect(compactMoney(12400, 'USD')).toBe('$12.4K')
  })

  it('signs changes and percentages', () => {
    expect(signedMoney(800)).toBe('+₹800')
    expect(signedMoney(-500)).toBe('-₹500')
    expect(signedPercent(0.8)).toBe('+0.80%')
    expect(signedPercent(-12.4)).toBe('-12.40%')
  })

  it('writes a moment in the run zone', () => {
    const at = Date.UTC(2026, 8, 15, 3, 31) / 1000 // 09:01 IST
    expect(momentText(at, 'Asia/Kolkata')).toMatch(/15 Sept? 2026, 09:01/)
  })
})
