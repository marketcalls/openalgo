import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useBrokerStore } from '@/stores/brokerStore'
import { useSupportedExchanges } from './useSupportedExchanges'

describe('useSupportedExchanges derivative coverage', () => {
  beforeEach(() => {
    useBrokerStore.setState({ capabilities: null, isLoaded: false })
  })

  it('isolates broker-reported BCD and NCDEX to Strategy Builder', () => {
    useBrokerStore.setState({
      capabilities: {
        broker_name: 'test',
        broker_type: 'IN_stock',
        supported_exchanges: ['NSE', 'NFO', 'CDS', 'BCD', 'NCDEX'],
        leverage_config: false,
      },
      isLoaded: true,
    })

    const { result } = renderHook(() => useSupportedExchanges())

    expect(result.current.strategyBuilderExchanges.map((exchange) => exchange.value)).toEqual([
      'NFO',
      'BCD',
      'NCDEX',
    ])
    expect(result.current.toolsFnoExchanges.map((exchange) => exchange.value)).toEqual(['NFO'])
  })

  it('never adds a derivative venue that the broker did not report', () => {
    useBrokerStore.setState({
      capabilities: {
        broker_name: 'test',
        broker_type: 'IN_stock',
        supported_exchanges: ['NSE', 'NFO', 'BCD'],
        leverage_config: false,
      },
      isLoaded: true,
    })

    const { result } = renderHook(() => useSupportedExchanges())
    const exchanges = result.current.strategyBuilderExchanges.map((exchange) => exchange.value)

    expect(exchanges).toContain('BCD')
    expect(exchanges).not.toContain('NCDEX')
    expect(exchanges).not.toContain('MCX')
  })
})
