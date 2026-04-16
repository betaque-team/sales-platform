import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

/**
 * Regression finding 222(action 5): wrap the app in a top-level React
 * error boundary that catches uncaught render errors (e.g. `.map()` on
 * `undefined.items` when data is still loading AND the page forgot to
 * guard). Without this, a single bad render crashes React's root and
 * the user stares at a fully blank <div id="root" />.
 *
 * This is pure backstop UX — the primary fix is `<QueryBoundary>` +
 * `<BackendErrorBanner>` on the useQuery call sites. This class only
 * fires when one of those (or any other synchronous render) throws.
 *
 * Implementation note: class component by necessity. React's error-
 * boundary contract requires `componentDidCatch` / `getDerivedStateFromError`
 * — hooks can't implement it as of React 18.
 */

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  error: Error | null;
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface for bug reports. Dev console is fine — Sentry wiring can
    // come later without touching call sites.
    // eslint-disable-next-line no-console
    console.error("AppErrorBoundary caught:", error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ error: null });
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
        <div className="w-full max-w-md rounded-xl border border-red-200 bg-white p-8 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-100">
              <AlertTriangle className="h-5 w-5 text-red-600" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-gray-900">
                Something went wrong
              </h1>
              <p className="text-xs text-gray-500">
                The app hit an unexpected error
              </p>
            </div>
          </div>
          <div className="mt-4 rounded-lg bg-gray-50 p-3">
            <p className="break-words text-xs text-gray-700">
              {error.message || "Unknown error"}
            </p>
          </div>
          <div className="mt-6 flex gap-2">
            <button
              type="button"
              onClick={this.handleReset}
              className="flex-1 rounded-md bg-white px-3 py-2 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
            >
              Dismiss
            </button>
            <button
              type="button"
              onClick={this.handleReload}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Reload page
            </button>
          </div>
        </div>
      </div>
    );
  }
}
