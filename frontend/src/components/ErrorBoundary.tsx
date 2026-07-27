import { Component, type ErrorInfo, type ReactNode } from 'react'
import { tryAutoReloadOnChunkError } from '@/utils/chunkReload'
import { reportClientError } from '@/utils/errorReporter'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  message: string
  reloading: boolean
}

/**
 * Top-level React ErrorBoundary. Catches render-time errors in the tree,
 * reports them to the backend, and shows a minimal fallback so the app
 * doesn't go fully blank. The reporter itself is best-effort.
 *
 * Stale-chunk handling: when CI commits a new frontend/dist build the old
 * hashed JS chunks vanish, so any browser tab that still has the previous
 * index.html cached gets a "Failed to fetch dynamically imported module"
 * (or similar, depending on browser) when the user navigates to a
 * lazy-loaded route. We recognise that class of error and auto-reload
 * once to pick up the fresh index.html — see #1393.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '', reloading: false }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      message: error.message || 'Something went wrong',
      reloading: false,
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportClientError({
      message: error.message || 'Render error',
      stack: error.stack,
      component_stack: info.componentStack || undefined,
    })

    // Auto-recover from stale-bundle navigation failures by reloading once.
    // tryAutoReloadOnChunkError is a no-op if the error isn't chunk-related
    // or if we've already attempted a reload this session.
    if (tryAutoReloadOnChunkError(error.message)) {
      this.setState({ reloading: true })
    }
  }

  handleReload = (): void => {
    window.location.reload()
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children
    if (this.props.fallback) return this.props.fallback

    // Auto-reload in flight (stale-chunk recovery). Show a neutral loading
    // hint instead of an error so the user doesn't see scary text for the
    // ~50ms before the page actually navigates.
    if (this.state.reloading) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-background">
          <div className="max-w-md w-full text-center space-y-2">
            <h1 className="text-base font-medium">Loading new version…</h1>
            <p className="text-xs text-muted-foreground">A fresh build is available.</p>
          </div>
        </div>
      )
    }

    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-background">
        <div className="max-w-md w-full text-center space-y-4">
          <h1 className="text-xl font-semibold">Something went wrong</h1>
          <p className="text-sm text-muted-foreground break-words">{this.state.message}</p>
          <p className="text-xs text-muted-foreground">
            The error has been logged. You can reload the page or visit{' '}
            <a className="underline" href="/admin/diagnostics">
              Diagnostics
            </a>{' '}
            to view recent errors.
          </p>
          <button
            type="button"
            onClick={this.handleReload}
            className="inline-flex items-center justify-center rounded-md text-sm font-medium h-9 px-4 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}
