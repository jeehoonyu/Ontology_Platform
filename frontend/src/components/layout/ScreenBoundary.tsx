import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErrorBanner } from "../data/DataDisplay";

/**
 * Keeps the shell standing when a screen throws (GOAL_FOUNDATIONS A2).
 *
 * With no boundary, React unmounts the whole root on an error thrown while
 * rendering or in an effect, so one screen's bad value took the sidebar and every
 * other screen down with it. This catches the error at the screen, says which
 * screen failed and why, and offers to try again. App keys it by view, so
 * navigating away starts the next screen clean. A history step inside the view
 * (A6: a tab or a resource in the query) changes `resetKey`, and clears a caught
 * error without remounting a screen that is working: Back from the tab that threw
 * lands on the tab that did not.
 */
export class ScreenBoundary extends Component<{ screen: string; resetKey?: string; children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error(`${this.props.screen} failed`, error, info.componentStack);
  }

  componentDidUpdate(previous: { resetKey?: string }) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) this.setState({ error: null });
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
