// frontend/src/lib/exportPng.ts
/**
 * Save a DOM element (a chart and its caption) as a PNG, the way the intraday
 * P&L Tracker does: html2canvas-pro, scale 2, the page's own background.
 *
 * html2canvas-pro clones every canvas and reads each back with getImageData,
 * which logs a performance warning per canvas unless the clone is created with
 * willReadFrequently. The patch is applied for the capture only and only to
 * detached canvases (the clones), so the live chart contexts are never touched.
 */
import html2canvas from 'html2canvas-pro'

export async function exportElementAsPng(element: HTMLElement, filename: string): Promise<void> {
  const original = HTMLCanvasElement.prototype.getContext
  HTMLCanvasElement.prototype.getContext = function patched(
    this: HTMLCanvasElement,
    contextId: string,
    options?: unknown
  ) {
    if (contextId === '2d' && !this.isConnected) {
      return original.call(this, contextId, {
        ...(options as CanvasRenderingContext2DSettings),
        willReadFrequently: true,
      })
    }
    return original.call(this, contextId, options as never)
  } as typeof HTMLCanvasElement.prototype.getContext

  try {
    const background = getComputedStyle(document.body).backgroundColor || '#ffffff'
    const canvas = await html2canvas(element, {
      backgroundColor: background,
      scale: 2,
      logging: false,
      useCORS: true,
    })
    const blob: Blob | null = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!blob) throw new Error('empty image')
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } finally {
    HTMLCanvasElement.prototype.getContext = original
  }
}
