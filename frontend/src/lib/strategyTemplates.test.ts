import { describe, expect, it } from 'vitest'
import { previewValue, STRATEGY_TEMPLATES, templatePreviewPath } from './strategyTemplates'

function template(id: string) {
  const found = STRATEGY_TEMPLATES.find((candidate) => candidate.id === id)
  if (!found) throw new Error(`Missing strategy template: ${id}`)
  return found
}

describe('strategy template previews', () => {
  it('SB-20 shows the Jade Lizard left-tail loss implied by its short put', () => {
    const jadeLizard = template('jade_lizard')

    expect(previewValue(jadeLizard, 0)).toBeLessThan(
      previewValue(jadeLizard, jadeLizard.referenceSpot)
    )
  })

  it('derives same-expiry preview topology from the normalized legs', () => {
    const longCall = template('long_call')
    const shortCall = {
      ...longCall,
      legs: longCall.legs.map((leg) => ({ ...leg, side: 'SELL' as const })),
    }

    expect(templatePreviewPath(shortCall)).not.toBe(templatePreviewPath(longCall))
    expect(longCall.payoffPath).toBe(templatePreviewPath(longCall))
  })

  it('marks multi-expiry previews as illustrative and keeps same-expiry previews computed', () => {
    for (const candidate of STRATEGY_TEMPLATES) {
      const isMultiExpiry = candidate.legs.some((leg) => (leg.expiryOffset ?? 0) > 0)
      expect(candidate.illustrativePreview).toBe(isMultiExpiry)
    }
  })
})

describe('strategy template copy', () => {
  it('keeps downside claims physically bounded at an underlying price of zero', () => {
    const allTemplateCopy = STRATEGY_TEMPLATES.map((candidate) => candidate.description).join(' ')

    expect(allTemplateCopy).not.toMatch(/unlimited downside/i)
  })

  it('does not guarantee a credit or debit before live premiums are known', () => {
    const allTemplateCopy = STRATEGY_TEMPLATES.map((candidate) => candidate.description).join(' ')

    expect(allTemplateCopy).not.toMatch(/\bnet (?:credit|debit) trade\b/i)
    expect(allTemplateCopy).not.toMatch(/\bsmall (?:credit|debit)\b/i)
  })

  it('describes calendar previews as illustrative because the far leg retains time value', () => {
    for (const id of ['call_calendar', 'put_calendar', 'diagonal_calendar']) {
      const candidate = template(id)
      expect(candidate.description).toMatch(/residual time value/i)
      expect(candidate.illustrativePreview).toBe(true)
    }
  })
})
