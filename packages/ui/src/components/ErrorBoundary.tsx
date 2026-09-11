import { Component, type ErrorInfo, type ReactNode } from 'react';

export interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * What to show instead. A function so the caller can offer an action —
   * discarding the page that will not render, say — without this component
   * knowing anything about the domain.
   */
  fallback: (reset: () => void) => ReactNode;
  /** Reported to the console, never to the screen. */
  label?: string;
}

interface State {
  failed: boolean;
}

/**
 * One subtree that can fail without taking its siblings with it.
 *
 * A class component because React has no functional equivalent:
 * `componentDidCatch` and `getDerivedStateFromError` exist only on classes, and
 * every "hook" version in circulation is a wrapper around one of these.
 *
 * It exists because the app had exactly one boundary, at the locale segment, so a
 * single malformed row threw away the entire screen it was on. On the scan review
 * that is thirty pages of a class's corrected work replaced by a generic apology,
 * because one detection had a shape nobody anticipated (G22). Wrapping each page
 * turns "the pile is unreadable" into "this page is unreadable", which is a
 * problem a teacher can work around — they can correct the other twenty-nine and
 * retake the one.
 *
 * It renders no strings of its own. The library ships no copy, and a boundary that
 * hard-coded "Something went wrong" would be the one English sentence in a French
 * product, appearing at the worst possible moment.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // The console is where an exception's own text belongs; a browser reads the
    // fallback, never this.
    console.error(`[${this.props.label ?? 'ErrorBoundary'}]`, error, info.componentStack);
  }

  private readonly reset = (): void => {
    this.setState({ failed: false });
  };

  override render(): ReactNode {
    if (this.state.failed) return this.props.fallback(this.reset);
    return this.props.children;
  }
}
