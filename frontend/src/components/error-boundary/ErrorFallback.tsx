import React from "react";

interface ErrorFallbackProps {
  error?: Error;
  resetError: () => void;
}

export default function ErrorFallback({ error, resetError }: ErrorFallbackProps) {
  return (
    <div className="flex min-h-[300px] flex-col items-center justify-center rounded-lg border bg-background p-8 text-center shadow-sm">
      <h2 className="text-xl font-semibold text-foreground">
        Something went wrong
      </h2>

      <p className="mt-2 text-sm text-muted-foreground">
        Please try refreshing the page or retry the action.
      </p>

      {error && (
        <p className="mt-2 text-xs text-destructive">
          {error.message}
        </p>
      )}

      <button
        onClick={resetError}
        className="mt-6 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90"
      >
        Try Again
      </button>
    </div>
  );
}