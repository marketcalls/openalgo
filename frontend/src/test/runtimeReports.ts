import type { SystemRuntime } from '@/types/admin'

/**
 * Runtime blocks of the admin system report, for the diagnostics page tests.
 *
 * The first four were captured from real gunicorn 25.3.0 workers on Ubuntu
 * 24.04 by calling blueprints.admin._runtime_info() inside the worker a few
 * seconds after it loaded the app, one Socket.IO session open. The others are
 * built from those, changing only what the backend would change.
 */

/** The default: eventlet from the service install.sh writes, no launcher. */
export const EVENTLET_DEFAULT: SystemRuntime = {
  python_version: '3.12.3',
  python_implementation: 'cpython',
  eventlet_active: true,
  wsgi_hint: 'gunicorn-eventlet',
  process_uptime_seconds: 17,
  worker_class: 'eventlet',
  requested_worker_class: 'eventlet',
  gunicorn_version: '25.3.0',
  configured_workers: null,
  configured_threads: null,
  graceful_timeout: null,
  launcher: null,
  started_by_launcher: false,
  thread_pool: null,
  thread_budget: { threads: null, streams: 0, socketio: 1, headroom: null },
  streams: {},
  websocket_proxy_mode: 'subprocess',
  http_pool: null,
  active_threads: 17,
  notes: [],
}

/** .env asks for gthread, but the service still starts raw eventlet. */
export const EVENTLET_ASKS_GTHREAD: SystemRuntime = {
  ...EVENTLET_DEFAULT,
  process_uptime_seconds: 14,
  requested_worker_class: 'gthread',
  notes: [
    'Your .env asks for the gthread web server, but this server still starts the eventlet web server because its service has not been switched. After 23:30 IST run: sudo bash install/switch-worker.sh (Docker: restart the container).',
  ],
}

/** gthread through install/openalgo-gunicorn.sh. */
export const GTHREAD_LAUNCHER: SystemRuntime = {
  python_version: '3.12.3',
  python_implementation: 'cpython',
  eventlet_active: false,
  wsgi_hint: 'gunicorn-gthread',
  process_uptime_seconds: 13,
  worker_class: 'gthread',
  requested_worker_class: 'gthread',
  gunicorn_version: '25.3.0',
  configured_workers: 1,
  configured_threads: 64,
  graceful_timeout: 30,
  launcher: { version: '1', requested: 'gthread', effective: 'gthread', threads: 64 },
  started_by_launcher: true,
  thread_pool: { spawned: 1, busy: 0, waiting: 0, open_connections: 0 },
  thread_budget: { threads: 64, streams: 0, socketio: 1, headroom: 63 },
  streams: {},
  websocket_proxy_mode: 'subprocess',
  http_pool: null,
  active_threads: 19,
  notes: [],
}

/** eventlet through the launcher, after switching back from gthread. */
export const EVENTLET_LAUNCHER: SystemRuntime = {
  ...EVENTLET_DEFAULT,
  process_uptime_seconds: 15,
  configured_workers: 1,
  graceful_timeout: 30,
  launcher: { version: '1', requested: 'eventlet', effective: 'eventlet', threads: null },
  started_by_launcher: true,
}

/** The sentence blueprints/admin.py writes when the request slots run out. */
export const BUSY_NOTE =
  "Almost every request slot is busy (60 of 64), so new requests can wait. Close OpenAlgo tabs you are not using. If this keeps happening during trading, go back to eventlet: set OPENALGO_WORKER_CLASS = 'eventlet' in .env and restart OpenAlgo after 23:30 IST."

/** gthread under load: most threads busy, a queue, broker connections open. */
export const GTHREAD_BUSY: SystemRuntime = {
  ...GTHREAD_LAUNCHER,
  process_uptime_seconds: 5 * 3600 + 12 * 60,
  thread_pool: { spawned: 64, busy: 60, waiting: 3, open_connections: 70 },
  thread_budget: { threads: 64, streams: 6, socketio: 12, headroom: 46 },
  http_pool: { connections: 4, idle: 3, max_connections: 100 },
  active_threads: 88,
  notes: [BUSY_NOTE],
}

/** The development server (uv run app.py): no gunicorn, the proxy in a thread. */
export const DEV_SERVER: SystemRuntime = {
  python_version: '3.12.3',
  python_implementation: 'cpython',
  eventlet_active: false,
  wsgi_hint: 'flask-dev',
  process_uptime_seconds: 42,
  worker_class: 'dev',
  requested_worker_class: 'eventlet',
  gunicorn_version: null,
  configured_workers: null,
  configured_threads: null,
  graceful_timeout: null,
  launcher: null,
  started_by_launcher: null,
  thread_pool: null,
  thread_budget: { threads: null, streams: 0, socketio: 0, headroom: null },
  streams: {},
  websocket_proxy_mode: 'thread',
  http_pool: null,
  active_threads: 12,
  notes: [],
}

/** A server from before the web server fields, which reports only these. */
export const BEFORE_WEB_SERVER_FIELDS: SystemRuntime = {
  python_version: '3.12.3',
  python_implementation: 'cpython',
  eventlet_active: true,
  wsgi_hint: 'gunicorn-eventlet',
  process_uptime_seconds: 3 * 86400 + 4 * 3600,
}
