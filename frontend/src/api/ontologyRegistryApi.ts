import { api, postJson } from "../api";

export interface OntologyRegistryEntry {
  id: string;
  project_id: string;
  channel: string;
  version: string;
  revision_id: string;
  revision_number: number;
  status: string;
  checksum: string;
  published_by: string;
  created_at: number;
  compatibility: {
    against_registry_id?: string | null;
    classification: string;
    summary: { changes: number; breaking: number; non_breaking: number };
    entries: Array<{
      kind: string;
      resource_type: string;
      resource_id: string;
      property_name?: string;
      breaking: boolean;
    }>;
  };
}

export interface OntologyRegistryState {
  summary: { status: string; entries: number; channel: string; current_version?: string | null };
  primary_actions: Array<{ id: string; label: string; method: string; path: string }>;
  sections: { current?: OntologyRegistryEntry | null; entries: OntologyRegistryEntry[] };
  evidence_links: Array<{ label: string; href: string; kind: string }>;
  warnings: Array<{ code: string; message: string }>;
  permissions: string[];
  last_updated: number;
}

export interface OntologyRevisionSummary {
  id: string;
  revision: number;
  status: string;
  checksum: string;
  created_at: number;
  published_at?: number | null;
}

export type RegistryCompatibility = OntologyRegistryEntry["compatibility"] & {
  project_id: string;
  channel: string;
  revision_id: string;
};

export interface OntologySdkPackage {
  language: "typescript" | "python";
  ecosystem: "npm" | "pypi";
  package_name: string;
  module_name?: string;
  filename: string;
  content_type: string;
  sha256: string;
  byte_size: number;
  download_url: string;
}

export interface OntologySdkPackageManifest {
  registry_id: string;
  registry_checksum: string;
  version: string;
  channel: string;
  packages: OntologySdkPackage[];
}

export function getOntologyRegistryState(projectId = "default", channel = "production"): Promise<OntologyRegistryState> {
  return api(`/ui-state/ontology/registry?project_id=${encodeURIComponent(projectId)}&channel=${encodeURIComponent(channel)}`);
}

export function getPublishedOntologyRevisions(projectId = "default"): Promise<OntologyRevisionSummary[]> {
  return api(`/ontology/revisions?project_id=${encodeURIComponent(projectId)}`);
}

export function checkRegistryCompatibility(revisionId: string, projectId = "default", channel = "production"): Promise<RegistryCompatibility> {
  return postJson("/ontology/registry/compatibility", { project_id: projectId, revision_id: revisionId, channel });
}

export function publishOntologyRegistry(revisionId: string, version: string, channel: string, allowBreaking: boolean, projectId = "default"): Promise<OntologyRegistryEntry> {
  return postJson("/ontology/registry/publish", {
    project_id: projectId, revision_id: revisionId, version, channel, allow_breaking: allowBreaking
  });
}

export function getRegistrySchema(entryId: string): Promise<{ registry_id: string; checksum: string; schema: object }> {
  return api(`/ontology/registry/${encodeURIComponent(entryId)}/schema`);
}

export function getRegistrySdk(entryId: string, language: "typescript" | "python"): Promise<{ registry_id: string; checksum: string; files: Record<string, string> }> {
  return api(`/ontology/registry/${encodeURIComponent(entryId)}/sdk/${language}`);
}

export function getRegistryPackages(entryId: string): Promise<OntologySdkPackageManifest> {
  return api(`/ontology/registry/${encodeURIComponent(entryId)}/packages`);
}

export async function downloadRegistryPackage(packageInfo: OntologySdkPackage): Promise<void> {
  const response = await fetch(packageInfo.download_url, { credentials: "same-origin" });
  if (!response.ok) throw new Error(`Package download failed: ${response.status} ${response.statusText}`);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = packageInfo.filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
