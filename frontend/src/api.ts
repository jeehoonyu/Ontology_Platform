export type JsonMap = Record<string, unknown>;

export async function api<T = JsonMap>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init.body && !(init.body instanceof FormData) ? { "content-type": "application/json" } : {}),
      ...(init.headers || {})
    }
  });
  if (!response.ok) {
    const text = await response.text();
    if (response.status === 401) window.dispatchEvent(new CustomEvent("ontology:authentication-required"));
    throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 400)}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return (await response.text()) as T;
  }
  return (await response.json()) as T;
}

export function postJson<T = JsonMap>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) });
}
