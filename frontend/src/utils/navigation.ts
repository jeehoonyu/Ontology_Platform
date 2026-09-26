import { useMemo, useSyncExternalStore } from "react";
import table from "../routes.json";

// GOAL_FOUNDATIONS A6: each workspace place has one URL, /workspace/<view>?<params>. The server
// matches one path segment (main.py serve_workspace_view), so an id always travels in the query.
// routes.json is the one table; oms/app/workspace_routes.py is the server's copy and
// oms/test_workspace_routes.py holds them equal. This rides in the entry chunk because App.tsx
// imports it: a module only lazy screens import gets a chunk of its own and a request on open
// (vite.config.ts: DragKit, graphLayout, Tabs).
interface ViewRoute { params: string[]; defaults?: Record<string, string> }
const VIEWS: Record<string, ViewRoute | undefined> = table.views;
export type RouteParams = Record<string, string | null | undefined>;

export function currentWorkspaceView(allowedViews: Set<string>, fallback = "command-center"): string {
  const match = window.location.pathname.match(/\/workspace\/([^/?#]+)/);
  const view = match?.[1] || fallback;
  return allowedViews.has(view) ? view : fallback;
}

const here = () => window.location.pathname + window.location.search;
const readSearch = () => window.location.search;
function onLocationChange(listener: () => void) {
  window.addEventListener("popstate", listener);
  return () => window.removeEventListener("popstate", listener);
}
function paramsOf(view: string, search: string): Record<string, string> {
  const route = VIEWS[view];
  const query = new URLSearchParams(search);
  return Object.fromEntries((route?.params ?? []).map((name) => [name, query.get(name) || route?.defaults?.[name] || ""]));
}

/**
 * The params `view` declares, each its default or "" when the URL names none. Re-read on every
 * navigate(), Back and Forward, not only at mount: ScreenBoundary is keyed by view, so a history
 * step that changes only the query reaches a screen that stays mounted.
 */
export function useRouteParams(view: string): Readonly<Record<string, string>> {
  const search = useSyncExternalStore(onLocationChange, readSearch);
  return useMemo(() => paramsOf(view, search), [view, search]);
}

/** A place's one spelling: declared params only, in the table's order, empty values and defaults left out, no bare "?". */
function hrefFor(view: string, params: RouteParams = {}): string {
  const route = VIEWS[view];
  const query = new URLSearchParams();
  for (const name of route?.params ?? []) {
    const value = params[name];
    if (value && value !== route?.defaults?.[name]) query.set(name, value);
  }
  const search = query.toString();
  return search ? `/workspace/${view}?${search}` : `/workspace/${view}`;
}

/**
 * Opens a place in this page: pushState, then popstate for App and every reader. The place
 * already open adds no entry, and the last view's query never carries: the href is built from
 * `params` alone. Only event handlers call it, never effects: a default or automatic selection
 * never writes the URL (main.tsx runs StrictMode, which would run an effect's write twice).
 */
export function navigate(view: string, params: RouteParams = {}): void {
  const href = hrefFor(view, params);
  // The place already open, however its URL spells it (?tab=command from an old link, a param
  // no screen reads), is the same place: read back through the table, it is this href.
  const open = window.location.pathname.match(/^\/workspace\/([^/]+)$/)?.[1];
  if (href === here() || (open === view && href === hrefFor(view, paramsOf(view, window.location.search)))) return;
  window.history.pushState({}, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/**
 * A server-written href: opened in this page when it names a workspace view (keeping its
 * declared params), and as a page load otherwise -- always for ?legacy=1, which only the server
 * answers.
 */
export function navigateHref(href: string): void {
  const url = new URL(href, window.location.origin);
  const view = url.origin === window.location.origin ? url.pathname.match(/^\/workspace\/([^/]+)$/)?.[1] : undefined;
  if (!view || url.searchParams.has("legacy")) window.location.assign(href);
  else navigate(view, Object.fromEntries(url.searchParams));
}
