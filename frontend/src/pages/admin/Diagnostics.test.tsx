import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  BUSY_NOTE,
  EVENTLET_ASKS_GTHREAD,
  EVENTLET_DEFAULT,
  GTHREAD_BUSY,
} from '@/test/runtimeReports'
import type { SystemInfo, SystemRuntime } from '@/types/admin'

const api = vi.hoisted(() => ({
  getSystemInfo: vi.fn(),
  getErrors: vi.fn(),
  getErrorStats: vi.fn(),
  getErrorGroups: vi.fn(),
  runDiagnostics: vi.fn(),
  downloadReport: vi.fn(),
}))

vi.mock('@/api/admin', () => ({ adminApi: api }))
vi.mock('@/utils/toast', () => ({
  showToast: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import Diagnostics from './Diagnostics'

function systemInfo(runtime: SystemRuntime): SystemInfo {
  return {
    mode: { analyze_mode: false, label: 'Live' },
    host: { system: 'Linux', in_docker: false },
    runtime,
    hardware: { cpu_count: 4 },
    build: { openalgo_version: '2.0.0' },
    config: {
      valid_brokers: ['zerodha'],
      log_level: 'INFO',
      log_to_file: true,
      log_dir: 'log',
      websocket_host: '127.0.0.1',
      websocket_port: '8765',
      max_symbols_per_websocket: '1000',
      max_websocket_connections: '3',
      api_rate_limit: '50 per second',
      flask_debug: false,
      secrets_present: {},
    },
    brokers: { configured_brokers: ['zerodha'], active_broker: null, user_logged_in: false },
    databases: [],
    time: { server_time: '2026-09-23 23:45:00', server_tz: 'IST', ist_time: '2026-09-23 23:45:00' },
  }
}

async function renderWith(runtime: SystemRuntime) {
  api.getSystemInfo.mockResolvedValue(systemInfo(runtime))
  render(
    <MemoryRouter>
      <Diagnostics />
    </MemoryRouter>
  )
  const title = await screen.findByText('Web server', { selector: '[data-slot="card-title"]' })
  const card = title.closest<HTMLElement>('[data-slot="card"]')
  if (!card) throw new Error('Web server card not found')
  return within(card)
}

/** The value shown beside a label in the card. */
function shownFor(card: ReturnType<typeof within>, label: string): string | null {
  const labelEl = card.queryByText(label, { selector: 'span' })
  return labelEl?.nextElementSibling?.textContent ?? null
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getErrors.mockResolvedValue({
    status: 'success',
    data: [],
    count: 0,
    scanned: 0,
    total_in_window: 0,
  })
  api.getErrorStats.mockResolvedValue({
    status: 'success',
    total: 0,
    by_level: {},
    last_24h: 0,
    last_1h: 0,
  })
  api.getErrorGroups.mockResolvedValue({
    status: 'success',
    groups: [],
    total_entries: 0,
    total_groups: 0,
  })
})

describe('Diagnostics web server card', () => {
  it('shows a default eventlet install plainly, with nothing about threads', async () => {
    const card = await renderWith(EVENTLET_DEFAULT)
    expect(shownFor(card, 'Web server')).toBe('eventlet (the default)')
    expect(shownFor(card, 'Market data proxy')).toBe('Separate process started by OpenAlgo')
    expect(card.queryByText('Request threads')).toBeNull()
    expect(card.queryByText('Started by launcher')).toBeNull()
    expect(card.queryByRole('note')).toBeNull()
    // The raw fields the card replaces are gone from the page.
    expect(screen.queryByText('Eventlet active')).toBeNull()
    expect(screen.queryByText('WSGI')).toBeNull()
  })

  it('shows a busy gthread server with its note first', async () => {
    const card = await renderWith(GTHREAD_BUSY)
    expect(shownFor(card, 'Web server')).toBe('gthread')
    expect(shownFor(card, 'Request threads')).toBe('64')
    expect(shownFor(card, 'Request threads busy')).toBe('60 of 64')
    expect(shownFor(card, 'Started by launcher')).toBe('Yes')
    expect(shownFor(card, 'Broker connections')).toBe('4 open, 3 idle, up to 100')
    expect(card.getByRole('note')).toHaveTextContent(BUSY_NOTE)
  })

  it('explains a switch that has not been applied', async () => {
    const card = await renderWith(EVENTLET_ASKS_GTHREAD)
    expect(shownFor(card, 'Web server in .env')).toBe('gthread')
    expect(card.getByRole('note')).toHaveTextContent('sudo bash install/switch-worker.sh')
  })

  it('formats the uptime in hours and minutes', async () => {
    await renderWith(GTHREAD_BUSY)
    const label = screen.getByText('Process uptime', { selector: 'span' })
    expect(label.nextElementSibling?.textContent).toBe('5 h 12 min')
  })
})
