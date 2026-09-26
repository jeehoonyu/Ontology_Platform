/**
 * Browser storage that cannot take the app down (GOAL_FOUNDATIONS A2).
 *
 * A private window, blocked site data or a full quota makes `localStorage` throw:
 * on the property itself in some browsers, on `getItem` and `setItem` in others.
 * And a value written by an older build can be any shape. Nothing kept here is
 * needed to render, so a read that fails gives the fallback and a write that
 * fails is dropped. `paneLayout.ts`, the pipeline's hidden nodes and the ontology
 * layout guard their own calls the same way.
 */
export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* remembering is a convenience; failing to must not break the action */
  }
}

/** A stored JSON value, kept only if it has the shape the caller expects. */
export function readStoredJson<T>(key: string, isShape: (value: unknown) => value is T, fallback: T): T {
  const raw = readStored(key);
  if (raw === null) return fallback;
  try {
    const value: unknown = JSON.parse(raw);
    return isShape(value) ? value : fallback;
  } catch {
    return fallback;
  }
}
