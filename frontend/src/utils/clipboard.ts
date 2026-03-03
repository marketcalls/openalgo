/**
 * Copy text to clipboard with fallback for non-HTTPS contexts.
 *
 * navigator.clipboard.writeText() requires a secure context (HTTPS).
 * Many OpenAlgo deployments use plain HTTP (local or IP-based), so
 * this helper falls back to the legacy execCommand('copy') approach.
 */
export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
  } else {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
}
