import { describe, expect, it } from 'vitest'
import {
  isProfileKind,
  profileDefaults,
  profileValues,
  readProfileSettings,
} from './profileSettings'

describe('profile settings', () => {
  it('reads independent profile preferences from the same pane settings', () => {
    const stored = {
      'profiles.tpo.ticksPerRow': 40,
      'profiles.tpo.showPoc': false,
      'profiles.svp.ticksPerRow': 12,
      'profiles.svp.showPoc': true,
      'symbol.upColor': '#ffffff',
      ticksPerRow: 999,
    }
    expect(readProfileSettings('tpo', stored)).toMatchObject({
      kind: 'tpo',
      ticksPerRow: 40,
      showPoc: false,
      blockMinutes: 30,
    })
    expect(readProfileSettings('session-volume-profile', stored)).toMatchObject({
      kind: 'session-volume-profile',
      ticksPerRow: 12,
      showPoc: true,
      rowCount: 24,
    })
    expect(profileValues('tpo', stored)).toMatchObject({
      'profiles.tpo.ticksPerRow': 40,
      'profiles.tpo.showPoc': false,
    })
    expect(profileValues('tpo', stored)).not.toHaveProperty('profiles.svp.ticksPerRow')
    expect(profileValues('tpo', stored)).not.toHaveProperty('symbol.upColor')
    expect(profileValues('tpo', stored)).not.toHaveProperty('profiles.tpo.kind')
  })

  it('bounds numeric inputs before they can create excessively large profile calculations', () => {
    expect(
      readProfileSettings('tpo', {
        'profiles.tpo.ticksPerRow': 0,
        'profiles.tpo.periodCount': 1000,
        'profiles.tpo.blockMinutes': 999,
        'profiles.tpo.valueAreaPercent': -10,
        'profiles.tpo.outsideVaOpacity': 123,
        'profiles.tpo.initialBalanceBlocks': 2.8,
      })
    ).toMatchObject({
      ticksPerRow: 1,
      periodCount: 12,
      blockMinutes: 30,
      valueAreaPercent: 1,
      outsideVaOpacity: 100,
      initialBalanceBlocks: 3,
    })
    expect(
      readProfileSettings('session-volume-profile', {
        'profiles.svp.rowCount': 1000000,
        'profiles.svp.ticksPerRow': 1000000,
        'profiles.svp.widthPercent': -1,
      })
    ).toMatchObject({ rowCount: 200, ticksPerRow: 10000, widthPercent: 1 })
  })

  it.each([
    undefined,
    null,
    '',
    '  ',
    Number.NaN,
    Number.POSITIVE_INFINITY,
    'Infinity',
    true,
    [],
    {},
  ])('replaces a corrupt numeric preference (%s) with its default', (value) => {
    expect(readProfileSettings('tpo', { 'profiles.tpo.blockMinutes': value }).blockMinutes).toBe(30)
    expect(
      readProfileSettings('session-volume-profile', { 'profiles.svp.rowCount': value }).rowCount
    ).toBe(24)
  })

  it('accepts finite numeric strings while preserving strict booleans and known choices', () => {
    expect(readProfileSettings('tpo', { 'profiles.tpo.blockMinutes': 17 }).blockMinutes).toBe(30)
    expect(
      readProfileSettings('tpo', {
        'profiles.tpo.blockMinutes': ' 45 ',
        'profiles.tpo.periodUnit': 'year',
        'profiles.tpo.split': 'true',
        'profiles.tpo.showPoc': false,
        'profiles.tpo.display': 'letters',
      })
    ).toMatchObject({
      blockMinutes: 45,
      periodUnit: 'day',
      split: false,
      showPoc: false,
      display: 'letters',
    })
    expect(
      readProfileSettings('session-volume-profile', {
        'profiles.svp.volumeMode': 'delta',
        'profiles.svp.placement': 'floating',
        'profiles.svp.rowsLayout': 'pixels',
      })
    ).toMatchObject({ volumeMode: 'delta', placement: 'left', rowsLayout: 'number-of-rows' })
  })

  it('normalizes hex swatches and rejects invalid color payloads', () => {
    expect(
      readProfileSettings('tpo', {
        'profiles.tpo.gradientColor1': ' #ABC ',
        'profiles.tpo.gradientColor2': '#Ff0011',
        'profiles.tpo.pocColor': 'url(https://example.com)',
        'profiles.tpo.vahColor': '#12345678',
      })
    ).toMatchObject({
      gradientColor1: '#aabbcc',
      gradientColor2: '#ff0011',
      pocColor: '#f0a020',
      vahColor: '#8892a6',
    })
  })

  it('accepts custom overnight hours and repairs malformed session times', () => {
    expect(
      readProfileSettings('tpo', {
        'profiles.tpo.sessionMode': 'custom',
        'profiles.tpo.sessionStart': '2300',
        'profiles.tpo.sessionEnd': '6:30',
      })
    ).toMatchObject({ sessionMode: 'custom', sessionStart: '23:00', sessionEnd: '06:30' })
    expect(
      readProfileSettings('session-volume-profile', {
        'profiles.svp.sessionMode': 'custom',
        'profiles.svp.sessionStart': ' 2300 ',
        'profiles.svp.sessionEnd': '6:30',
      })
    ).toMatchObject({ sessionMode: 'custom', sessionStart: '23:00', sessionEnd: '06:30' })
    expect(
      readProfileSettings('session-volume-profile', {
        'profiles.svp.sessionStart': '25:00',
        'profiles.svp.sessionEnd': '15:99',
      })
    ).toMatchObject({ sessionStart: '09:15', sessionEnd: '15:30' })
  })

  it('returns fresh defaults so resetting one pane cannot mutate another', () => {
    const defaults = profileDefaults('session-volume-profile')
    defaults['profiles.svp.rowCount'] = 100
    expect(profileDefaults('session-volume-profile')['profiles.svp.rowCount']).toBe(24)
    expect(profileDefaults('tpo')['profiles.tpo.valueAreaPercent']).toBe(70)
    expect(profileDefaults('session-volume-profile')).not.toHaveProperty(
      'profiles.tpo.valueAreaPercent'
    )
  })

  it('identifies only registered profile chart types', () => {
    expect(isProfileKind('tpo')).toBe(true)
    expect(isProfileKind('session-volume-profile')).toBe(true)
    expect(isProfileKind('volume-profile')).toBe(false)
    expect(isProfileKind('candlestick')).toBe(false)
  })
})
