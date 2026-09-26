import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErrorBanner } from "../data/DataDisplay";

/**
 * Keeps the shell standing when a screen throws (GOAL_FOUNDATIONS A2).
 *
 * With no boundary, React unmounts the whole root on an error thrown while
 * rendering or in an effect, so one screen's bad value took the sidebar and every
 * other screen down with it. This catches the error at the screen, says which
 * screen failed and why, and offers to try again. App keys it by view, so
 * navigating away starts the next screen clean.
 */
export class ScreenBoundary extends Component<{ screen: string; children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error(`${this.props.screen} failed`, error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div role="alert">
        <ErrorBanner message={`${this.props.screen} failed. ${error.message}`} />
        <div className="button-row">
          <button onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      </div>
    );
  }
}
