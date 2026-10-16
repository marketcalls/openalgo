// frontend/src/components/pnl/ChartWatermark.tsx
/**
 * The OpenAlgo watermark, as on the intraday P&L Tracker plot (fork-only):
 * faint, centred, and behind the plot. Put it first inside a `relative`
 * wrapper and give the plot itself `relative z-[1]`; the chart canvases are
 * transparent, so it shows through under the lines and bars.
 */
export function ChartWatermark({ isDark }: { isDark: boolean }) {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-0 flex select-none items-center justify-center"
      style={{
        fontFamily: 'Arial, sans-serif',
        fontSize: 48,
        fontWeight: 'bold',
        color: isDark ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.15)',
      }}
    >
      OpenAlgo
    </div>
  )
}

/** Draw the same mark onto a canvas context (for exported images), centred on the box. */
export function drawWatermark(
  ctx: CanvasRenderingContext2D,
  isDark: boolean,
  centerX: number,
  centerY: number
) {
  ctx.save()
  ctx.font = 'bold 48px Arial, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = isDark ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.15)'
  ctx.fillText('OpenAlgo', centerX, centerY)
  ctx.restore()
}
