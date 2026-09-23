import { describe, expect, it } from 'vitest'
import {
  BEFORE_WEB_SERVER_FIELDS,
  BUSY_NOTE,
  DEV_SERVER,
  EVENTLET_ASKS_GTHREAD,
  EVENTLET_DEFAULT,
  EVENTLET_LAUNCHER,
  GTHREAD_BUSY,
  GTHREAD_LAUNCHER,
} from '@/test/runtimeReports'
import type { SystemRuntime } from '@/types/admin'
import {
  formatUptime,
  proxyModeLabel,
  webServerKind,
  webServerNotes,
  webServerRows,
} from './webServerSummary'

const asMap = (runtime: SystemRuntime) =>
  Object.fromEntries(webServerRows(runtime).map((row) => [row.label, row.value]))

const THREAD_ROWS = ['Request threads', 'Request threads busy', 'Requests waiting', 'Threads free']

describe('webServerRows on the default eventlet install', () => {
  const rows = asMap(EVENTLET_DEFAULT)

  it('names eventlet as the default', () => {
    expect(rows['Web server']).toBe('eventlet (the default)')
    expect(rows['Web server in .env']).toBe('eventlet (the default)')
    expect(rows.gunicorn).toBe('25.3.0')
  })

  it('leaves out everything that only a gthread pool has', () => {
    for (const label of THREAD_ROWS) expect(rows).not.toHaveProperty(label)
  })

  it('does not report a launcher it never used as missing', () => {
    expect(rows).not.toHaveProperty('Started by launcher')
  })

  it('still shows what eventlet does have', () => {
    expect(rows['Open streams']).toBe('0')
    expect(rows['Browser sessions']).toBe('1')
    expect(rows['Market data proxy']).toBe('Separate process started by OpenAlgo')
    expect(rows['Broker connections']).toBe('None opened yet')
    expect(rows['Process threads']).toBe('17')
  })

  it('has no notes', () => {
    expect(webServerNotes(EVENTLET_DEFAULT)).toEqual([])
  })
})

describe('webServerRows on gthread through the launcher', () => {
  const rows = asMap(GTHREAD_LAUNCHER)

  it('answers what docs/gthread/README.md tells the operator to check', () => {
    expect(rows['Web server']).toBe('gthread')
    expect(rows['Request threads']).toBe('64')
    expect(rows['Started by launcher']).toBe('Yes')
  })

  it('shows the pool and the time a stop gives open requests', () => {
    expect(rows['Request threads busy']).toBe('0 of 64')
    expect(rows['Requests waiting']).toBe('None')
    expect(rows['Threads free']).toBe('63 of 64')
    expect(rows['Time to finish requests on stop']).toBe('30 seconds')
  })

  it('shows a busy pool and the note written for it', () => {
    const busy = asMap(GTHREAD_BUSY)
    expect(busy['Request threads busy']).toBe('60 of 64')
    expect(busy['Requests waiting']).toBe('3')
    expect(busy['Threads free']).toBe('46 of 64')
    expect(busy['Broker connections']).toBe('4 open, 3 idle, up to 100')
    expect(webServerNotes(GTHREAD_BUSY)).toEqual([BUSY_NOTE])
  })

  it('never shows a negative number of free threads', () => {
    const over = {
      ...GTHREAD_BUSY,
      thread_budget: { threads: 64, streams: 60, socketio: 10, headroom: -6 },
    }
    expect(asMap(over)['Threads free']).toBe('0 of 64')
  })
})

describe('webServerRows while a switch is pending', () => {
  it('shows what .env asks for beside what runs, and says the launcher was not used', () => {
    const rows = asMap(EVENTLET_ASKS_GTHREAD)
    expect(rows['Web server']).toBe('eventlet (the default)')
    expect(rows['Web server in .env']).toBe('gthread')
    expect(rows['Started by launcher']).toBe('No')
    expect(webServerNotes(EVENTLET_ASKS_GTHREAD)[0]).toContain('sudo bash install/switch-worker.sh')
  })

  it('shows the launcher on an install switched back to eventlet', () => {
    const rows = asMap(EVENTLET_LAUNCHER)
    expect(rows['Web server']).toBe('eventlet (the default)')
    expect(rows['Started by launcher']).toBe('Yes')
    for (const label of THREAD_ROWS) expect(rows).not.toHaveProperty(label)
  })
})

describe('webServerRows on the development server', () => {
  const rows = asMap(DEV_SERVER)

  it('names it and says it ignores the .env choice', () => {
    expect(rows['Web server']).toBe('Development server')
    expect(rows['Web server in .env']).toBe(
      'eventlet (the default), not used by the development server'
    )
    expect(rows).not.toHaveProperty('gunicorn')
    expect(rows).not.toHaveProperty('Started by launcher')
    expect(rows['Market data proxy']).toBe('Inside the OpenAlgo process')
  })
})

describe('webServerRows on a server from before these fields', () => {
  it('works out the web server from the older fields and shows nothing else', () => {
    const rows = webServerRows(BEFORE_WEB_SERVER_FIELDS)
    expect(rows).toEqual([{ label: 'Web server', value: 'eventlet (the default)' }])
    expect(webServerNotes(BEFORE_WEB_SERVER_FIELDS)).toEqual([])
  })
})

describe('the market data proxy', () => {
  it.each([
    ['subprocess', 'Separate process started by OpenAlgo'],
    ['thread', 'Inside the OpenAlgo process'],
    ['external', 'Separate service (Docker or standalone mode)'],
    [null, 'Not detected'],
  ])('describes %s', (mode, text) => {
    expect(proxyModeLabel(mode)).toBe(text)
  })

  it('shows the proxy state when the server reports it', () => {
    const rows = asMap({
      ...GTHREAD_LAUNCHER,
      websocket_proxy: {
        mode: 'subprocess',
        pid: 4242,
        alive: true,
        restarts: 2,
        last_exit_code: -9,
        last_restart_at: 1_790_000_000,
      },
    })
    expect(rows['Market data proxy status']).toBe(
      'Running, restarted 2 times since OpenAlgo started'
    )
  })

  it('says a stopped proxy is stopped', () => {
    const rows = asMap({
      ...EVENTLET_DEFAULT,
      websocket_proxy: {
        mode: 'subprocess',
        pid: null,
        alive: false,
        restarts: 0,
        last_exit_code: 1,
        last_restart_at: null,
      },
    })
    expect(rows['Market data proxy status']).toBe('Stopped')
  })

  it('shows no status row when the server does not report one', () => {
    expect(asMap(GTHREAD_LAUNCHER)).not.toHaveProperty('Market data proxy status')
  })
})

describe('webServerKind', () => {
  it('prefers what the worker registered', () => {
    expect(webServerKind({ worker_class: 'gthread', eventlet_active: true })).toBe('gthread')
  })

  it('falls back to the older hints', () => {
    expect(webServerKind({ wsgi_hint: 'gunicorn-sync' })).toBe('sync')
    expect(webServerKind({ wsgi_hint: 'flask-dev' })).toBe('dev')
    expect(webServerKind({})).toBeNull()
  })
})

describe('webServerNotes', () => {
  it('drops blanks and anything that is not text', () => {
    const runtime = { notes: ['', '  ', 'Restart OpenAlgo after 23:30 IST.', 7] } as unknown
    expect(webServerNotes(runtime as SystemRuntime)).toEqual(['Restart OpenAlgo after 23:30 IST.'])
  })
})

describe('formatUptime', () => {
  it.each([
    [null, null],
    [undefined, null],
    [-5, null],
    [30, 'Less than a minute'],
    [17 * 60 + 40, '17 min'],
    [5 * 3600 + 12 * 60, '5 h 12 min'],
    [3 * 86400 + 4 * 3600 + 59 * 60, '3 d 4 h'],
  ])('formats %s seconds', (seconds, text) => {
    expect(formatUptime(seconds)).toBe(text)
  })
})
