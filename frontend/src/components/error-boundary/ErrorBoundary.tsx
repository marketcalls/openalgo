import { Component, type ErrorInfo, type ReactNode } from "react";
import ErrorFallback from "./ErrorFallback";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

/**
 * ErrorBoundary catches rendering errors in its child component tree
 * and displays a fallback UI instead of crashing the entire app.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: undefined };

  // Triggered when a child component throws an error
  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  // Useful for logging errors to monitoring tools (Sentry, etc.)
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info);
  }

  // Reset error state when user clicks "Try Again"
  resetError = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <ErrorFallback error={this.state.error} resetError={this.resetError} />
        )
      );
    }

    return this.props.children;
  }
}