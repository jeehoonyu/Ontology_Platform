export function currentWorkspaceView(allowedViews: Set<string>, fallback = "command-center"): string {
  const match = window.location.pathname.match(/\/workspace\/([^/?#]+)/);
  const view = match?.[1] || fallback;
  return allowedViews.has(view) ? view : fallback;
}

export function navigate(view: string) {
  window.history.pushState({}, "", `/workspace/${view}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
