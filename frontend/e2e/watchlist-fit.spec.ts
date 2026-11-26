import { expect, type Locator, type Page, test } from '@playwright/test'

/**
 * How the charting terminal's watchlist is laid out, measured in a browser.
 *
 * The panel's unit tests run in jsdom, which has no layout: a name cut to two
 * letters, a figure spilling out of its column and a label sitting beside the
 * wrong number all pass there. Three such things are pinned here instead.
 *
 * - The name outranks the exchange tag. With the tag fixed in place the name
 *   paid for every column added, and NIFTY read "NI..." beside a complete
 *   NSE_INDEX.
 * - A label stays over its figures on a list long enough to scroll. The header
 *   used to sit outside the scrolling box, so the rows lost the scrollbar's
 *   width and the labels did not.
 * - A figure fits its column to the paisa.
 *
 * Every assertion is a relation between elements rather than a pixel count,
 * so it holds whatever system font the runner draws with.
 *
 * These run against the Vite dev server with no Flask backend. Everything the
 * page asks a backend for is answered here, and nothing is let through to one.
 */

const SESSION_STATUS = {
  status: 'success',
  logged_in: true,
  authenticated: true,
  broker: 'angel',
  user: 'e2e',
  // The price hook reads its key from here. Without one it asks for no quotes
  // at all, and every figure in the panel stays a dash.
  api_key: 'e2e',
  active_sessions: 1,
}

interface Instrument {
  symbol: string
  exchange: string
  ltp: number
  prevClose: number
}

const MIXED: Instrument[] = [
  { symbol: 'NIFTY', exchange: 'NSE_INDEX', ltp: 25349.65, prevClose: 25800.6 },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', ltp: 62585.35, prevClose: 64635.2 },
  { symbol: 'RELIANCE', exchange: 'NSE', ltp: 1351, prevClose: 1377.5 },
  { symbol: 'INFY', exchange: 'NSE', ltp: 1594.3, prevClose: 1601.15 },
  { symbol: 'NIFTY26NOV2625500CE', exchange: 'NFO', ltp: 142.35, prevClose: 201.8 },
  { symbol: 'BANKNIFTY26NOV26FUT', exchange: 'NFO', ltp: 62710, prevClose: 64801.4 },
]

/** Enough rows to scroll in any viewport these tests use. */
const LONG: Instrument[] = Array.from({ length: 60 }, (_, i) => ({
  symbol: `STOCK${String(i + 1).padStart(2, '0')}`,
  exchange: 'NSE',
  ltp: 1000.05 + i * 37.35,
  prevClose: 1012.4 + i * 36.9,
}))

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

async function openWatchlist(page: Page, instruments: Instrument[]): Promise<Locator> {
  // Registered first, so it is asked last: any request for data that is not
  // answered below ends here and never reaches a server. Vite's own modules
  // are left alone.
  await page.route('**/*', (route) => {
    const request = route.request()
    const kind = request.resourceType()
    const path = new URL(request.url()).pathname
    const fromVite = /^\/(src|node_modules|@)/.test(path)
    if ((kind !== 'fetch' && kind !== 'xhr') || fromVite) return route.fallback()
    return route.fulfill(json({ status: 'error', message: 'Not available in this test' }, 404))
  })
  await page.routeWebSocket(/socket\.io|127\.0\.0\.1:9/, (socket) => socket.close())

  await page.route('**/auth/session-status', (route) => route.fulfill(json(SESSION_STATUS)))
  await page.route('**/auth/csrf-token', (route) => route.fulfill(json({ csrf_token: 'e2e' })))
  await page.route('**/api/websocket/apikey', (route) =>
    route.fulfill(json({ status: 'success', api_key: 'e2e' }))
  )
  await page.route('**/api/websocket/config', (route) =>
    route.fulfill(json({ status: 'success', websocket_url: 'ws://127.0.0.1:9' }))
  )
  await page.route('**/watchlist/api/lists', (route) =>
    route.fulfill(
      json({
        status: 'success',
        data: [
          {
            id: 1,
            name: 'Fit',
            position: 0,
            items: instruments.map((item, i) => ({
              id: i + 1,
              symbol: item.symbol,
              exchange: item.exchange,
              position: i,
            })),
          },
        ],
      })
    )
  )
  await page.route('**/api/v1/multiquotes', (route) =>
    route.fulfill(
      json({
        status: 'success',
        results: instruments.map((item) => ({
          symbol: item.symbol,
          exchange: item.exchange,
          data: {
            ltp: item.ltp,
            prev_close: item.prevClose,
            open: item.ltp,
            high: item.ltp,
            low: item.ltp,
            volume: 0,
            bid: item.ltp,
            ask: item.ltp,
            oi: 0,
          },
        })),
      })
    )
  )

  // A browser that has the watchlist open and has never changed it.
  await page.addInitScript(() => localStorage.setItem('oa-trading-panel', 'watchlist'))
  await page.goto('/trading')

  const panel = page.locator('#oa-panel-watchlist')
  await expect(panel).toBeVisible({ timeout: 60_000 })
  // The figures arrive after the list does, and every test here measures them.
  const firstPercent = panel.locator('[data-column="changePercent"][data-direction]').first()
  await expect(firstPercent).not.toHaveText('-', { timeout: 30_000 })
  return panel
}

/** Each row's name and tag, and whether either is cut or dropped. */
function symbolCells(panel: Locator) {
  return panel.getByTestId('watchlist-row').evaluateAll((rows) =>
    rows.map((row) => {
      const name = row.querySelector<HTMLElement>('[data-testid="watchlist-name"]')
      const tag = row.querySelector<HTMLElement>('[data-testid="watchlist-exchange"]')
      if (!name || !tag) throw new Error('a row is missing its name or its exchange tag')
      const line = name.getBoundingClientRect()
      const tagBox = tag.getBoundingClientRect()
      return {
        symbol: name.textContent ?? '',
        cut: name.scrollWidth > name.clientWidth,
        // A tag with no room is on a second line, below the one the row
        // shows. Half a line of slack, so a fraction of a pixel decides nothing.
        tagShown: tagBox.top < line.bottom - line.height / 2,
      }
    })
  )
}

/** Right edge of every label, and of the same column's figure in one row. */
function columnEdges(panel: Locator, rowIndex: number) {
  return panel.evaluate((el, index) => {
    const header = el.querySelector('[data-testid="watchlist-columns"]')
    const row = el.querySelectorAll('[data-testid="watchlist-row"]')[index]
    if (!header || !row) throw new Error('the header or the row is missing')
    return [...header.querySelectorAll<HTMLElement>('[data-column]')].map((label) => {
      const cell = row.querySelector<HTMLElement>(`[data-column="${label.dataset.column}"]`)
      if (!cell) throw new Error(`no ${label.dataset.column} figure in the row`)
      return {
        column: label.dataset.column,
        label: label.getBoundingClientRect().right,
        figure: cell.getBoundingClientRect().right,
      }
    })
  }, rowIndex)
}

test.describe('Trading watchlist layout', () => {
  // The terminal is the heaviest page in the app, and the dev server compiles
  // it on the first request. The default thirty seconds is for a warm one.
  test.describe.configure({ timeout: 120_000 })

  test('opens on symbol, last, change and change percent', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 })
    const panel = await openWatchlist(page, MIXED)

    await expect(panel.getByTestId('watchlist-columns').locator('span')).toHaveText([
      'Symbol',
      'Last',
      'Chg',
      'Chg%',
      '',
    ])

    const row = panel.getByTestId('watchlist-row').nth(1)
    await expect(row.locator('[data-column="last"]')).toHaveText('62,585.35')
    await expect(row.locator('[data-column="change"]')).toHaveText('-2,049.85')
    await expect(row.locator('[data-column="changePercent"]')).toHaveText('-3.17%')
  })

  test('gives the name the room before the exchange tag', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 })
    const panel = await openWatchlist(page, MIXED)
    const cells = await symbolCells(panel)
    const find = (symbol: string) => cells.find((cell) => cell.symbol === symbol)

    // The rule, for every row: a name is cut only once its tag has gone.
    for (const cell of cells) {
      expect(cell.cut && cell.tagShown, `${cell.symbol} is cut beside a whole exchange tag`).toBe(
        false
      )
    }

    // Both sides of the rule are on screen, or the loop above proved nothing.
    expect(find('INFY'), 'a short name keeps its tag').toMatchObject({ cut: false, tagShown: true })
    expect(find('NIFTY26NOV2625500CE'), 'a long contract gives its tag up').toMatchObject({
      tagShown: false,
    })
    // The names a list usually starts with are whole at the opening width.
    expect(find('NIFTY')?.cut).toBe(false)
    expect(find('BANKNIFTY')?.cut).toBe(false)
  })

  test('keeps each label over its figures on a list that scrolls', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 640 })
    const panel = await openWatchlist(page, LONG)

    const header = panel.getByTestId('watchlist-columns')
    const list = header.locator('xpath=..')
    const scrolls = await list.evaluate((el) => el.scrollHeight > el.clientHeight)
    expect(scrolls, 'the list has to scroll for this test to mean anything').toBe(true)

    for (const edge of await columnEdges(panel, 0)) {
      expect(Math.abs(edge.label - edge.figure), `${edge.column} label and figure`).toBeLessThan(1)
    }

    // The header stays where it is while the rows move under it.
    const before = await header.boundingBox()
    await list.evaluate((el) => {
      el.scrollTop = el.scrollHeight
    })
    const after = await header.boundingBox()
    expect(after?.y).toBe(before?.y)
    await expect(panel.getByTestId('watchlist-row').last()).toBeInViewport()

    for (const edge of await columnEdges(panel, LONG.length - 1)) {
      expect(Math.abs(edge.label - edge.figure), `${edge.column} label and figure`).toBeLessThan(1)
    }
  })

  test('fits every figure in its column', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 })
    const panel = await openWatchlist(page, MIXED)

    const spills = await panel.locator('[data-testid="watchlist-row"] [data-column]').evaluateAll(
      (cells) =>
        cells
          .filter((cell) => cell.scrollWidth > cell.clientWidth)
          .map((cell) => `${(cell as HTMLElement).dataset.column}: ${cell.textContent}`)
    )
    expect(spills).toEqual([])

    // And the row itself is no wider than the list it sits in.
    const list = panel.getByTestId('watchlist-columns').locator('xpath=..')
    const sideways = await list.evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(sideways).toBeLessThanOrEqual(0)
  })
})
