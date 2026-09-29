# Custom Chart Indicators

Drop a `.js` file in this folder and it becomes an indicator in the `/trading`
chart's indicator picker. No build step, no Node.js, no restart of the app.
Refresh the chart and it is there.

Everything you put here is ignored by git, so your indicators stay on your own
machine and survive `git pull`.

## Only add indicators you have read

A file here is not sandboxed. It runs on the OpenAlgo origin with your logged-in
session, so it can place orders and read your account. Treat one copied from a
forum or a chat group exactly as you would any script you are about to run on
your trading machine: read it first, or do not add it.

To have Claude Code write and check one for you, use the `chart-indicator`
skill. It validates against the real charting library and refuses to install a
file that errors.

Minimal example, save as `my_indicator.js`:

```js
export default function ({ registerIndicator, sourceValues }) {
  registerIndicator({
    id: 'my-sma',
    name: 'My SMA',
    category: 'Custom',
    placement: 'onchart',
    inputs: [{ key: 'length', type: 'number', label: 'Length', default: 20, min: 1 }],
    plots: [{ key: 'ma', type: 'line', title: 'MA', style: { color: '#4f8cff', lineWidth: 2 } }],
    calc(bars, settings) {
      const src = sourceValues(bars, 'close')
      const n = Number(settings.length)
      const ma = new Array(bars.length).fill(null)
      let sum = 0
      for (let i = 0; i < src.length; i++) {
        sum += src[i]
        if (i >= n) sum -= src[i - n]
        if (i >= n - 1) ma[i] = sum / n
      }
      return { ma }
    },
  })
}
```

Full guide, including a worked Open Range Breakout example with signal labels:
[docs/custom-indicators.md](../../docs/custom-indicators.md)
