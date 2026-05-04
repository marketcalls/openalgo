import { Component, type ErrorInfo, type ReactNode } from 'react'
import { reportClientError } from '@/utils/errorReporter'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  message: string
}

/**
 * Top-level React ErrorBoundary. Catches render-time errors in the tree,
 * reports them to the backend, and shows a minimal fallback so the app
 * doesn't go fully blank. The reporter itself is best-effort.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message || 'Something went wrong' }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportClientError({
      message: error.message || 'Render error',
      stack: error.stack,
      component_stack: info.componentStack || undefined,
    })
  }

  handleReload = (): void => {
    window.location.reload()
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children
    if (this.props.fallback) return this.props.fallback

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
