import { describe, expect, it } from 'vitest'
import { chartMotionOptions } from './chartMotion'

const media = (matches: boolean) => ({
  matchMedia: (query: string) =>
    ({ matches: matches && query.includes('reduce') }) as MediaQueryList,
})

describe('chart motion options', () => {
  it('turns off the zoom glide and the autoscale easing when the system asks for less motion', () => {
    expect(chartMotionOptions(media(true))).toEqual({ animZoom: false, animAutoscale: false })
  })

  it('leaves the engine defaults alone otherwise', () => {
    expect(chartMotionOptions(media(false))).toEqual({})
    expect(chartMotionOptions(undefined)).toEqual({})
    expect(
      chartMotionOptions({
        matchMedia: () => {
          throw new Error('unsupported')
        },
      })
    ).toEqual({})
  })
})
