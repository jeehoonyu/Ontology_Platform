import { useEffect, useRef } from "react";

/**
 * Every key the pipeline canvas answers to, in one table.
 *
 * `GOAL_GRAPH_2026-09-23.md`. A hotkey is a row: the keys a person presses, what it
 * does, the button that does the same thing, and the handler. The listener below is
 * driven by the table and nothing else, so a key cannot be wired without being
 * listed, and a row cannot be listed without being wired. X4 renders the same table
 * as the `View hotkeys` reference, so the help cannot disagree with the wiring.
 *
 * Every hotkey names a button. A keyboard-only control is a feature only a keyboard
 * has, and `audit_inert_controls` sees a button, not a key.
 */
export interface Hotkey {
  /** What a person presses, as the reference shows it: `Ctrl+A`, `Delete`. */
  keys: string;
  /** What it does, in the words its button uses. */
  label: string;
  /** The accessible name of the button that does the same thing. */
  button: string;
  matches: (event: KeyboardEvent) => boolean;
  run: () => void;
}

/** Ctrl, or Command on a Mac, with one letter and nothing else held. */
export function ctrl(letter: string) {
  return (event: KeyboardEvent) =>
    (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === letter;
}

/** A key pressed on its own. */
export function bare(key: string) {
  return (event: KeyboardEvent) => !event.ctrlKey && !event.metaKey && !event.altKey && event.key === key;
}

/**
 * Whether a keydown belongs to the canvas: typed while nothing in particular had
 * focus, or inside the scope the screen marks. Anything typed into a field is the
 * field's, and a Ctrl+A in the Outputs pane selects that pane's text as it always did.
 */
export function inScope(event: KeyboardEvent, scope: string): boolean {
  const target = event.target as HTMLElement | null;
  if (!target || target.closest("input, textarea, select, [contenteditable='true']")) return false;
  return target === document.body || target === document.documentElement || Boolean(target.closest(scope));
}

/** Listens for the table's keys while `active`, inside `scope`. */
export function useHotkeys(table: Hotkey[], scope: string, active = true) {
  const current = useRef(table);
  current.current = table;
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || !inScope(event, scope)) return;
      const hotkey = current.current.find((row) => row.matches(event));
      if (!hotkey) return;
      event.preventDefault();
      hotkey.run();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [scope, active]);
}
