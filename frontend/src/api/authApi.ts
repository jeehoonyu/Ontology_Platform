import { api, postJson } from "../api";

export interface AuthSession {
  authenticated: boolean;
  principal_id: string;
  display_name: string;
  email?: string | null;
  roles: string[];
  permissions: string[];
  auth_mode: "local" | "oidc";
}

export function getAuthSession(): Promise<AuthSession> {
  return api<AuthSession>("/auth/session");
}

export function logout(allSessions = false): Promise<{ authenticated: boolean }> {
  return postJson<{ authenticated: boolean }>("/auth/logout", { all_sessions: allSessions });
}
