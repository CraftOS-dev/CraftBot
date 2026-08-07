/**
 * App shell (spec K4): error boundary + toast portal + theme bridge + console
 * relay + PB error surfacing. `main.tsx` mounts <Shell><App/></Shell>; the
 * agent writes App downward and never touches this file.
 */
import { Component, useEffect, type ReactNode } from 'react';
import { getPbClient } from '../pb/client.ts';
import { ThemeBridge } from '../theme/bridge.ts';
import { ConsoleRelay } from './console-relay.ts';
import { Toaster, toast } from './toast.tsx';

interface BoundaryProps {
  children: ReactNode;
}

interface BoundaryState {
  error: Error | null;
}

class ErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error): void {
    console.error(`ErrorBoundary caught: ${error.message}`);
  }

  override render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-[var(--lui-bg)] p-8 text-[var(--lui-text)]">
          <div className="max-w-md rounded-xl border border-red-500/30 bg-[var(--lui-surface)] p-6">
            <h1 className="mb-2 text-lg font-semibold">Something went wrong</h1>
            <p className="mb-4 text-sm opacity-80">{this.state.error.message}</p>
            <button
              type="button"
              className="rounded-md bg-[var(--lui-accent)] px-3 py-1.5 text-sm text-white"
              onClick={() => window.location.reload()}
            >
              Reload app
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function Shell({ children }: { children: ReactNode }): React.JSX.Element {
  useEffect(() => {
    const bridge = new ThemeBridge();
    const relay = new ConsoleRelay();
    bridge.start();
    relay.start();
    const offError = getPbClient().onError((err) => {
      toast.error(err.status === 0 ? 'Network error — is the backend running?' : err.message);
    });
    return () => {
      offError();
      relay.stop();
      bridge.stop();
    };
  }, []);

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-[var(--lui-bg)] text-[var(--lui-text)] antialiased">
        {children}
      </div>
      <Toaster />
    </ErrorBoundary>
  );
}
