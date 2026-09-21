import { beforeEach, describe, expect, it } from 'vitest'
import type { SearchRow } from '@/lib/trading/terminal'
import { useBrokerStore } from '@/stores/brokerStore'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import { SymbolSearchDialog } from './SymbolSearchDialog'

const ROWS: SearchRow[] = [
  { symbol: 'NIFTY100EW', exchange: 'NSE', name: 'KOTAKMAMC - NIFTY100EW' },
  { symbol: 'NIFTY100QUALTY30', exchange: 'NSE_INDEX', name: 'NIFTY100 Quality30' },
  { symbol: 'NIFTY18AUG2622350CE', exchange: 'NFO', name: 'NIFTY' },
]

function renderDialog(onPick: (row: SearchRow) => void = () => {}) {
  return render(
    <SymbolSearchDialog open onOpenChange={() => {}} search={async () => ROWS} onPick={onPick} />
  )
}

/** The dialog focuses and selects its box 30ms after opening; typing before
 *  that races the select() and loses the first character. */
async function focusedBox() {
  const box = screen.getByLabelText('Search symbol') as HTMLInputElement
  await waitFor(() => expect(box).toHaveFocus())
  return box
}

describe('SymbolSearchDialog', () => {
  it('labels comparison search and never submits a typed arithmetic expression', async () => {
    const picked: SearchRow[] = []
    render(
      <SymbolSearchDialog
        open
        mode="comparison"
        title="Add comparison symbol"
        onOpenChange={() => {}}
        search={async () => []}
        onPick={(row) => picked.push(row)}
      />
    )
    const box = screen.getByRole('textbox', { name: 'Search comparison symbol' })
    await waitFor(() => expect(box).toHaveFocus())
    expect(screen.getByRole('heading', { name: 'Add comparison symbol' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
    await userEvent.type(box, 'NSE:INFY+NSE:BHEL{Enter}')
    expect(picked).toEqual([])
    expect(screen.queryByText('Operators build an expression.', { exact: false })).toBeNull()
  })

  beforeEach(() => {
    useBrokerStore.setState({
      capabilities: {
        broker_name: 'test',
        broker_type: 'IN_stock',
        supported_exchanges: ['NSE', 'BSE', 'NFO', 'NSE_INDEX', 'BSE_INDEX'],
        leverage_config: false,
      },
      isLoaded: true,
    })
  })

  it('ranks an index above a same-scoring cash-equity match in ALL results', async () => {
    renderDialog()

    await userEvent.type(screen.getByLabelText('Search symbol'), 'NIFTY')

    await waitFor(() => expect(screen.getByText('NIFTY100QUALTY30')).toBeInTheDocument())

    // Dialog content is portaled to document.body, not the render() container.
    const symbols = Array.from(
      document.body.querySelectorAll('button[data-idx] span:first-child')
    ).map((el) => el.textContent)
    const indexPos = symbols.indexOf('NIFTY100QUALTY30')
    const cashPos = symbols.indexOf('NIFTY100EW')
    expect(indexPos).toBeGreaterThanOrEqual(0)
    expect(indexPos).toBeLessThan(cashPos)
  })

  it('shows an Index chip when the broker supports index exchanges', () => {
    renderDialog()

    expect(screen.getByRole('button', { name: 'Index' })).toBeInTheDocument()
  })

  it('filters to only index rows when the Index chip is selected', async () => {
    renderDialog()

    await userEvent.type(screen.getByLabelText('Search symbol'), 'NIFTY')
    await waitFor(() => expect(screen.getByText('NIFTY100QUALTY30')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Index' }))

    expect(screen.getByText('NIFTY100QUALTY30')).toBeInTheDocument()
    expect(screen.queryByText('NIFTY100EW')).not.toBeInTheDocument()
    expect(screen.queryByText('NIFTY18AUG2622350CE')).not.toBeInTheDocument()
  })

  /**
   * Symbol arithmetic. The operators build an expression in the box, and Enter
   * charts it instead of whatever the result list happens to be showing: those
   * rows match the last leg typed, so loading one would silently discard the
   * expression.
   */
  it('picks the expression on Enter rather than the highlighted row', async () => {
    const picked: SearchRow[] = []
    renderDialog((row) => picked.push(row))

    const box = await focusedBox()
    await userEvent.type(box, 'NIFTY100EW/NIFTY100QUALTY30')
    await waitFor(() => expect(screen.getByText(/Press Enter to chart/)).toBeInTheDocument())
    await userEvent.type(box, '{Enter}')

    expect(picked).toHaveLength(1)
    expect(picked[0].symbol).toBe('NIFTY100EW/NIFTY100QUALTY30')
    expect(picked[0].expression).toBe(true)
  })

  it('still picks an ordinary row when the box holds a plain symbol', async () => {
    const picked: SearchRow[] = []
    renderDialog((row) => picked.push(row))

    const box = await focusedBox()
    await userEvent.type(box, 'NIFTY')
    // Wait for a real result row, not merely for buttons to exist: the chips
    // and the operator keys are buttons too, so counting them passed before the
    // debounced search had returned anything to select.
    await waitFor(() => expect(screen.getByText('NIFTY100EW')).toBeInTheDocument())
    await userEvent.type(box, '{Enter}')

    expect(picked).toHaveLength(1)
    expect(picked[0].expression).toBeUndefined()
    expect(picked[0].exchange).not.toBe('')
  })

  it('the operator keys write into the box and the reciprocal wraps it', async () => {
    renderDialog()
    const box = (await focusedBox()) as HTMLInputElement

    await userEvent.type(box, 'NIFTY100EW')
    await userEvent.click(screen.getByLabelText('Divide'))
    await userEvent.type(box, 'NIFTY100QUALTY30')
    expect(box.value).toBe('NIFTY100EW/NIFTY100QUALTY30')

    await userEvent.click(screen.getByLabelText('Reciprocal'))
    expect(box.value).toBe('1/(NIFTY100EW/NIFTY100QUALTY30)')
  })

  it('offers every operator the engine parses, exponentiation included', () => {
    renderDialog()
    for (const name of ['Divide', 'Subtract', 'Add', 'Multiply', 'Exponentiation', 'Reciprocal']) {
      expect(screen.getByLabelText(name)).toBeInTheDocument()
    }
  })

  it('warns that a computed chart cannot be traded', async () => {
    renderDialog()
    await userEvent.type(screen.getByLabelText('Search symbol'), 'NIFTY100EW/NIFTY100QUALTY30')
    await waitFor(() => expect(screen.getByText(/cannot be traded/)).toBeInTheDocument())
  })

  /**
   * The bug this pins: searching the WHOLE box meant that the moment an
   * operator was typed the query stopped matching any instrument, the list
   * emptied, and there was no way to look up the second leg. You had to already
   * know its exact name, which defeats a search box.
   *
   * It used to assert the whole box was never searched as well, which was one
   * assertion too many: the requirement is that the leg IS searched, not that
   * nothing else is. The whole box is searched beside it now, because a hyphen
   * is an operator and a character instruments are named with, and splitting on
   * it made `BAJAJ-AUTO` unfindable. Searching both costs one request and is
   * the only thing that serves both.
   */
  it('searches the leg being typed, so the second leg can be looked up', async () => {
    const queries: string[] = []
    render(
      <SymbolSearchDialog
        open
        onOpenChange={() => {}}
        search={async (q) => {
          queries.push(q)
          return ROWS
        }}
        onPick={() => {}}
      />
    )

    const box = await focusedBox()
    await userEvent.type(box, 'NIFTY100EW+NIFTY1')
    await waitFor(() => expect(screen.getByText('NIFTY100EW')).toBeInTheDocument())

    // The leg after the operator was asked for. Without it, a second leg could
    // only be reached by already knowing its exact name.
    expect(queries).toContain('NIFTY1')
  })

  it('completing a leg keeps the dialog open and writes the exchange in', async () => {
    const picked: SearchRow[] = []
    renderDialog((row) => picked.push(row))

    const box = (await focusedBox()) as HTMLInputElement
    await userEvent.type(box, 'NIFTY100EW+NIFTY100Q')
    await waitFor(() => expect(screen.getByText('NIFTY100QUALTY30')).toBeInTheDocument())
    await userEvent.click(screen.getByText('NIFTY100QUALTY30'))

    // The leg is completed in place, qualified by its exchange, and nothing is
    // loaded: the user is still building.
    expect(box.value).toBe('NIFTY100EW+NSE_INDEX:NIFTY100QUALTY30')
    expect(picked).toHaveLength(0)
  })
})

/**
 * A hyphen is both an operator and a character instruments are named with.
 *
 * The box splits on operators so that a half-typed expression can still look up
 * its second leg: `NIFTY/` has to search on the empty leg after the slash
 * rather than on `NIFTY/`, which matches nothing. Splitting on `-` as well is
 * what made an instrument with a hyphen in its name unsearchable: typing
 * `BAJAJ-` split the box into `BAJAJ` and an empty leg, the caret sat in the
 * empty one, and the list went blank on the keystroke.
 *
 * The engine's own grammar has the same shape. `SYM_BODY` admits `&` and not
 * `-`, which is exactly why `M&M` is one symbol and `BAJAJ-AUTO` is a
 * subtraction, and why one loads and the other does not.
 */
describe('an instrument whose name contains an operator character', () => {
  const HYPHENATED: SearchRow[] = [
    { symbol: 'BAJAJ-AUTO', exchange: 'NSE', name: 'BAJAJ AUTO LIMITED' },
    { symbol: 'AUTOAXLES', exchange: 'NSE', name: 'AUTOMOTIVE AXLES' },
    { symbol: 'BAJAJHLDNG', exchange: 'NSE', name: 'BAJAJ HOLDINGS' },
  ]

  /**
   * Wait for a result ROW, not for the text anywhere on screen.
   *
   * The footer prints the query back ("Press Enter to chart BAJAJ-AUTO"), so a
   * plain text query is satisfied by the box's own echo before a single row has
   * arrived. A test written that way passes whether or not the instrument was
   * ever found, which is the one thing these are here to prove.
   */
  async function waitForRow(symbol: string) {
    await waitFor(() => {
      const rows = [...document.querySelectorAll('[data-idx]')].map((n) => n.textContent ?? '')
      expect(rows.some((text) => text.includes(symbol))).toBe(true)
    })
  }

  function searchSpy() {
    const asked: string[] = []
    return {
      asked,
      search: async (q: string) => {
        asked.push(q)
        const up = q.toUpperCase()
        return HYPHENATED.filter(
          (r) => r.symbol.includes(up) || String(r.name).toUpperCase().includes(up)
        )
      },
    }
  }

  it('searches the whole box as well as the leg the caret is in', async () => {
    const user = userEvent.setup()
    const spy = searchSpy()
    render(
      <SymbolSearchDialog open onOpenChange={() => {}} search={spy.search} onPick={() => {}} />
    )
    await user.type(await focusedBox(), 'BAJAJ-AUTO')
    // The leg alone would only ever ask for AUTO, and the instrument typed
    // would never be among the answers.
    await waitFor(() => expect(spy.asked).toContain('BAJAJ-AUTO'))
  })

  it('finds the instrument rather than emptying the list on the hyphen', async () => {
    const user = userEvent.setup()
    const spy = searchSpy()
    render(
      <SymbolSearchDialog open onOpenChange={() => {}} search={spy.search} onPick={() => {}} />
    )
    await user.type(await focusedBox(), 'BAJAJ-AUTO')
    await waitForRow('BAJAJ-AUTO')
  })

  it('puts the instrument that was typed above other matches on its leg', async () => {
    // Ranked on the leg, `AUTO` floats AUTOAXLES over the name actually typed.
    const user = userEvent.setup()
    const spy = searchSpy()
    render(
      <SymbolSearchDialog open onOpenChange={() => {}} search={spy.search} onPick={() => {}} />
    )
    await user.type(await focusedBox(), 'BAJAJ-AUTO')
    await waitForRow('BAJAJ-AUTO')
    // Read the rendered row order rather than a text query: the rows are
    // buttons carrying data-idx, and that is the order a trader sees and the
    // order Enter picks from.
    await waitFor(() => {
      const first = document.querySelector('[data-idx="0"]')
      expect(first?.textContent).toContain('BAJAJ-AUTO')
    })
    // AUTOAXLES scores better than BAJAJ-AUTO on a leg of AUTO, because it
    // starts with it. That is what makes this pair worth asserting on.
    expect(document.querySelector('[data-idx="1"]')?.textContent).toContain('AUTOAXLES')
  })

  it('puts an exact match above an index that merely contains the word', async () => {
    // Category outranks match quality, and indices outrank cash, so typing
    // BAJAJ-AUTO listed NIFTY EV, NIFTYAUTO and BSEAUTO first and the
    // instrument that was named fourth. Enter takes the highlighted row, so it
    // charted an index nobody asked for.
    const user = userEvent.setup()
    const ROWS_WITH_INDICES: SearchRow[] = [
      { symbol: 'NIFTYAUTO', exchange: 'NSE_INDEX', name: 'NIFTY AUTO' },
      { symbol: 'BSEAUTO', exchange: 'BSE_INDEX', name: 'BSE INDEX AUTO' },
      { symbol: 'BAJAJ-AUTO', exchange: 'NSE', name: 'BAJAJ AUTO LIMITED' },
    ]
    render(
      <SymbolSearchDialog
        open
        onOpenChange={() => {}}
        search={async () => ROWS_WITH_INDICES}
        onPick={() => {}}
      />
    )
    await user.type(await focusedBox(), 'BAJAJ-AUTO')
    await waitForRow('BAJAJ-AUTO')

    await waitFor(() => {
      expect(document.querySelector('[data-idx="0"]')?.textContent).toContain('BAJAJ-AUTO')
    })
  })

  it('loads the instrument when its row is clicked, rather than splicing it', async () => {
    // Found and not choosable is worse than not found: the instrument is on
    // screen and clicking it does something else. `BAJAJ-AUTO` has a prefix of
    // `BAJAJ-` to the splitter, so the pick used to append `NSE:BAJAJ-AUTO`
    // onto the box and leave the chart where it was.
    const user = userEvent.setup()
    const spy = searchSpy()
    const picked: SearchRow[] = []
    render(
      <SymbolSearchDialog
        open
        onOpenChange={() => {}}
        search={spy.search}
        onPick={(row) => picked.push(row)}
      />
    )
    await user.type(await focusedBox(), 'BAJAJ-AUTO')
    await waitForRow('BAJAJ-AUTO')
    const row = [...document.querySelectorAll('[data-idx]')].find((n) =>
      n.textContent?.includes('BAJAJ-AUTO')
    )
    await user.click(row as HTMLElement)
    expect(picked.map((row) => row.symbol)).toEqual(['BAJAJ-AUTO'])
  })

  it('loads it on Enter rather than charting the subtraction', async () => {
    // The grammar reads the name as arithmetic. Everybody typing it means the
    // instrument, and charting a subtraction is not what they asked for.
    const user = userEvent.setup()
    const spy = searchSpy()
    const picked: SearchRow[] = []
    render(
      <SymbolSearchDialog
        open
        onOpenChange={() => {}}
        search={spy.search}
        onPick={(row) => picked.push(row)}
      />
    )
    await user.type(await focusedBox(), 'BAJAJ-AUTO')
    await waitForRow('BAJAJ-AUTO')
    await user.keyboard('{Enter}')
    expect(picked).toHaveLength(1)
    expect(picked[0]?.symbol).toBe('BAJAJ-AUTO')
    expect(picked[0]?.expression).not.toBe(true)
  })

  it('loads it when the box carries its exchange too', async () => {
    // The form this dialog writes back into the box itself, and the one the
    // reported failure was in: a whole-box check that compared the bare name
    // only, so `NSE:BAJAJ-AUTO` fell through and the click spliced again,
    // leaving `BAJAJ-NSE:BAJAJ-AUTO` in the box with no way back.
    const user = userEvent.setup()
    const spy = searchSpy()
    const picked: SearchRow[] = []
    render(
      <SymbolSearchDialog
        open
        onOpenChange={() => {}}
        search={spy.search}
        onPick={(row) => picked.push(row)}
      />
    )
    await user.type(await focusedBox(), 'NSE:BAJAJ-AUTO')
    await waitForRow('BAJAJ-AUTO')
    const row = [...document.querySelectorAll('[data-idx]')].find((n) =>
      n.textContent?.includes('BAJAJ-AUTO')
    )
    await user.click(row as HTMLElement)
    expect(picked.map((one) => one.symbol)).toEqual(['BAJAJ-AUTO'])
  })

  it('never appends to a box that already names an instrument', async () => {
    // The state the report showed was unrecoverable: once anything had been
    // spliced on, every later click spliced again. Clicking any row while the
    // box names an instrument loads that row instead.
    const user = userEvent.setup()
    const spy = searchSpy()
    const picked: SearchRow[] = []
    render(
      <SymbolSearchDialog
        open
        onOpenChange={() => {}}
        search={spy.search}
        onPick={(row) => picked.push(row)}
      />
    )
    const box = await focusedBox()
    await user.type(box, 'BAJAJ-AUTO')
    await waitForRow('AUTOAXLES')
    const other = [...document.querySelectorAll('[data-idx]')].find((n) =>
      n.textContent?.includes('AUTOAXLES')
    )
    await user.click(other as HTMLElement)
    expect(picked.map((one) => one.symbol)).toEqual(['AUTOAXLES'])
    expect(box.value).not.toContain('BAJAJ-NSE:')
  })

  it('quotes a hyphenated symbol spliced into a real expression', async () => {
    // Unquoted, the chart's grammar reads `NSE:BAJAJ-AUTO` inside an expression
    // as `NSE:BAJAJ` minus `AUTO`: two instruments that do not exist. Quoting
    // is the grammar's own escape and keeps the exchange prefix, so
    // `'NSE:BAJAJ-AUTO'/...` resolves exactly as written.
    const user = userEvent.setup()
    const spy = searchSpy()
    render(
      <SymbolSearchDialog open onOpenChange={() => {}} search={spy.search} onPick={() => {}} />
    )
    const box = await focusedBox()
    await user.type(box, 'BAJAJHLDNG/BAJAJ')
    await waitForRow('BAJAJ-AUTO')
    const row = [...document.querySelectorAll('[data-idx]')].find((n) =>
      n.textContent?.includes('BAJAJ-AUTO')
    )
    await user.click(row as HTMLElement)
    expect(box.value).toBe("BAJAJHLDNG/'NSE:BAJAJ-AUTO'")
  })

  it('leaves a symbol without a hyphen unquoted', async () => {
    // Quoting everything would work and leave a trader reading
    // `'NSE:AUTOAXLES'` and wondering whether they have to type the quotes.
    const user = userEvent.setup()
    const spy = searchSpy()
    render(
      <SymbolSearchDialog open onOpenChange={() => {}} search={spy.search} onPick={() => {}} />
    )
    const box = await focusedBox()
    await user.type(box, 'BAJAJHLDNG/AUTOA')
    await waitForRow('AUTOAXLES')
    const row = [...document.querySelectorAll('[data-idx]')].find((n) =>
      n.textContent?.includes('AUTOAXLES')
    )
    await user.click(row as HTMLElement)
    expect(box.value).toBe('BAJAJHLDNG/NSE:AUTOAXLES')
  })

  it('still builds an expression when the box is not an instrument', async () => {
    // The capability the splitter exists for, and the one this fix must not
    // take away: a real expression still charts as a computed chart.
    const user = userEvent.setup()
    const spy = searchSpy()
    const picked: SearchRow[] = []
    render(
      <SymbolSearchDialog
        open
        onOpenChange={() => {}}
        search={spy.search}
        onPick={(row) => picked.push(row)}
      />
    )
    await user.type(await focusedBox(), 'BAJAJHLDNG/AUTOAXLES')
    await user.keyboard('{Enter}')
    expect(picked[0]?.expression).toBe(true)
    expect(picked[0]?.symbol).toBe('BAJAJHLDNG/AUTOAXLES')
  })

  it('still searches the leg, so a half-typed expression can look one up', async () => {
    // The capability the split exists for, and the one a naive fix removes.
    const user = userEvent.setup()
    const spy = searchSpy()
    render(
      <SymbolSearchDialog open onOpenChange={() => {}} search={spy.search} onPick={() => {}} />
    )
    await user.type(await focusedBox(), 'BAJAJHLDNG/BAJAJ')
    await waitFor(() => expect(spy.asked).toContain('BAJAJ'))
  })
})
