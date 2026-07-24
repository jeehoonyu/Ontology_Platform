import { api, postJson } from "../api";

export interface TenancyProject {
  id: string;
  organization_id: string;
  display_name: string;
  description?: string | null;
  permissions: string[];
}

export interface OntologyPackageVersionSummary {
  id: string;
  package_id: string;
  version: string;
  status: string;
  checksum: string;
  validation: { status?: string; summary?: Record<string, number> };
  created_at: number;
  published_at?: number | null;
}

export interface OntologyPackageSummary {
  id: string;
  organization_id: string;
  owning_project_id: string;
  display_name: string;
  description?: string | null;
  status: string;
  current_version?: string | null;
  version_count: number;
  active_installations: number;
  permissions: string[];
  versions?: OntologyPackageVersionSummary[];
}

export interface OntologyPackageInstallation {
  id: string;
  package_id: string;
  version: string;
  target_project_id: string;
  namespace: string;
  status: string;
  installed_resources: Array<{ resource_type: string; resource_id: string }>;
}

export function listTenancyProjects(): Promise<TenancyProject[]> {
  return api<TenancyProject[]>("/tenancy/projects");
}

export function bootstrapTenancy(): Promise<{ status: string }> {
  return postJson<{ status: string }>("/tenancy/bootstrap", {});
}

export function listOntologyPackages(projectId?: string): Promise<OntologyPackageSummary[]> {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return api<OntologyPackageSummary[]>(`/ontology-packages${query}`);
}

export function getOntologyPackage(packageId: string): Promise<OntologyPackageSummary> {
  return api<OntologyPackageSummary>(`/ontology-packages/${encodeURIComponent(packageId)}`);
}

export function createOntologyPackage(project: TenancyProject, packageId: string, displayName: string): Promise<OntologyPackageSummary> {
  return postJson<OntologyPackageSummary>("/ontology-packages", {
    id: packageId,
    organization_id: project.organization_id,
    owning_project_id: project.id,
    display_name: displayName,
    description: `Governed ontology package for ${displayName}`
  });
}

export function captureOntologyPackageVersion(packageId: string, version: string, objectTypeId: string): Promise<OntologyPackageVersionSummary> {
  return postJson<OntologyPackageVersionSummary>(`/ontology-packages/${encodeURIComponent(packageId)}/versions/capture`, {
    version,
    object_type_ids: [objectTypeId],
    action_type_ids: []
  });
}

export function publishOntologyPackageVersion(packageId: string, version: OntologyPackageVersionSummary): Promise<OntologyPackageVersionSummary> {
  return postJson<OntologyPackageVersionSummary>(`/ontology-packages/${encodeURIComponent(packageId)}/versions/${encodeURIComponent(version.version)}/publish`, {
    expected_checksum: version.checksum
  });
}

export function installOntologyPackageVersion(packageId: string, version: string, targetProjectId: string, namespace: string): Promise<OntologyPackageInstallation> {
  return postJson<OntologyPackageInstallation>(`/ontology-packages/${encodeURIComponent(packageId)}/versions/${encodeURIComponent(version)}/install`, {
    target_project_id: targetProjectId,
    namespace
  });
}
