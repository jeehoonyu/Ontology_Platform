import { apiWithTotal, api, postJson } from "../api";
import type {
  ConnectionSource,
  ConnectorAdapterCatalog,
  ConnectorCredentialMetadata,
  ConnectorFetchAttempt,
  ConnectorLivePreview,
  JsonObject
} from "../types";

export function getConnectorAdapters(): Promise<ConnectorAdapterCatalog> {
  return api<ConnectorAdapterCatalog>("/connectors/adapters");
}

export function createConnectionSource(body: {
  id: string;
  display_name: string;
  source_type: "rest" | "jdbc" | "s3" | "sftp" | "kafka";
  config: JsonObject;
}): Promise<ConnectionSource> {
  return postJson<ConnectionSource>("/connections/sources", body);
}

export function getConnectionSource(sourceId: string): Promise<ConnectionSource> {
  return api<ConnectionSource>(`/connections/sources/${encodeURIComponent(sourceId)}`);
}

export function rotateConnectorCredential(sourceId: string, body: {
  credential_type: "bearer" | "api_key" | "basic" | "aws" | "sftp_password" | "sftp_private_key" | "kafka_sasl_plain";
  secret: string;
  metadata: Record<string, string>;
}): Promise<ConnectorCredentialMetadata> {
  return postJson<ConnectorCredentialMetadata>(`/connections/sources/${encodeURIComponent(sourceId)}/runtime-credentials`, body);
}

export function listConnectorCredentials(sourceId: string): Promise<ConnectorCredentialMetadata[]> {
  return api<ConnectorCredentialMetadata[]>(`/connections/sources/${encodeURIComponent(sourceId)}/runtime-credentials`);
}

export function previewLiveConnector(sourceId: string, limit = 25): Promise<ConnectorLivePreview> {
  return postJson<ConnectorLivePreview>(`/connections/sources/${encodeURIComponent(sourceId)}/live-preview`, { limit });
}

// The latest 50 attempts, and how many the source has: the list alone read as all of them.
export function listConnectorFetchAttempts(sourceId: string): Promise<{ attempts: ConnectorFetchAttempt[]; total: number | null }> {
  return apiWithTotal<ConnectorFetchAttempt[]>(`/connections/sources/${encodeURIComponent(sourceId)}/fetch-attempts`)
    .then(({ body, total }) => ({ attempts: body, total }));
}
