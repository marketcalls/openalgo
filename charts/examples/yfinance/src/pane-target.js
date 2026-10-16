import { sessionOf } from './session.js';

/** Resolve the selected chart without replacing shared host state. */
export function selectedPane(app) {
  return app.focusPane === 2 && app.chart2 ? 2 : 1;
}

/** Capture an action's owner and request before a menu or async operation. */
export function capturePaneTarget(app, pane = selectedPane(app)) {
  const chartKey = pane === 2 ? 'chart2' : 'chart';
  const requestKey = pane === 2 ? 'p2' : 'req';
  const chart = app[chartKey];
  if (!chart) return null;
  const request = { ...app[requestKey] };
  return {
    pane,
    chart,
    draw: pane === 2 ? app.draw2 : app.draw,
    request,
    current() {
      const context = chart.getDataContext?.();
      return app[chartKey] === chart
        && ['symbol', 'interval', 'period'].every(key => app[requestKey]?.[key] === request[key])
        && sessionOf(app[requestKey]) === sessionOf(request)
        && (!context || ['symbol', 'interval'].every(key => context[key] === request[key]));
    },
  };
}
