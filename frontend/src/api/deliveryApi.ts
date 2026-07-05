import { api, postJson } from "../api";
import type { JsonObject, TableRow } from "../types";

// ---------------------------------------------------------------------------
// Response shapes (mirror the FastAPI response models)
// ---------------------------------------------------------------------------

export interface DevopsProduct {
  id: string;
  display_name: string;
  description?: string | null;
  resources: unknown[];
  publisher: string;
  mode: string;
  created_at: number;
}

export interface ProductRelease {
  id: string;
  product_id: string;
  version: string;
  channel: string;
  notes?: string | null;
  created_at: number;
}

export interface MarketplaceEntry {
  id: string;
  display_name: string;
  description?: string | null;
  publisher: string;
  resources: unknown[];
  created_at: number;
  latest_release?: ProductRelease | null;
}

export interface ProductInstallation {
  id: string;
  product_id: string;
  release_id: string;
  target_project: string;
  status: string;
  input_mappings: JsonObject;
  mode: string;
  release_channel: string;
  auto_upgrade: boolean;
  locked: boolean;
  created_at: number;
  updated_at: number;
}

export interface CodeRepository {
  id: string;
  display_name: string;
  description?: string | null;
  language: string;
  template: string;
  default_branch: string;
  created_at: number;
  updated_at: number;
}

export interface CodeWorkbook {
  id: string;
  display_name: string;
  language: string;
  environment: JsonObject;
  nodes: unknown[];
  created_at: number;
  updated_at: number;
}

export interface ComputeModule {
  id: string;
  display_name: string;
  image: string;
  entrypoint: string;
  mode: string;
  status: string;
  created_at: number;
}

export interface ComputeRunResult {
  module_id: string;
  mode: string;
  result: unknown;
  trace: TableRow[];
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface ProductCreateBody {
  id?: string;
  display_name: string;
  description?: string;
  resources?: Array<{ kind: string; id: string }>;
  publisher?: string;
  mode?: string;
}

export interface ReleaseCreateBody {
  id?: string;
  version: string;
  channel?: string;
  notes?: string;
}

export interface InstallBody {
  target_project: string;
  release_id?: string;
  mode?: string;
  input_mappings?: JsonObject;
}

export interface RepoCreateBody {
  id?: string;
  display_name: string;
  description?: string;
  language?: string;
  template?: string;
  default_branch?: string;
}

export interface WorkbookCreateBody {
  id?: string;
  display_name: string;
  language?: string;
  environment?: JsonObject;
  nodes?: unknown[];
}

export interface ComputeModuleCreateBody {
  id?: string;
  display_name: string;
  image: string;
  entrypoint: string;
  mode?: string;
}

export interface ComputeRunBody {
  records?: JsonObject[];
  spec?: JsonObject[];
}

// ---------------------------------------------------------------------------
// Products / releases (DevOps)
// ---------------------------------------------------------------------------

export function listProducts(): Promise<DevopsProduct[]> {
  return api<DevopsProduct[]>("/devops/products");
}

export function createProduct(body: ProductCreateBody): Promise<DevopsProduct> {
  return postJson<DevopsProduct>("/devops/products", body);
}

export function createRelease(productId: string, body: ReleaseCreateBody): Promise<ProductRelease> {
  return postJson<ProductRelease>(`/devops/products/${encodeURIComponent(productId)}/releases`, body);
}

// ---------------------------------------------------------------------------
// Marketplace / installations
// ---------------------------------------------------------------------------

export function listMarketplace(): Promise<MarketplaceEntry[]> {
  return api<MarketplaceEntry[]>("/marketplace");
}

export function installProduct(productId: string, body: InstallBody): Promise<ProductInstallation> {
  return postJson<ProductInstallation>(`/marketplace/${encodeURIComponent(productId)}/install`, body);
}

export function listInstallations(): Promise<ProductInstallation[]> {
  return api<ProductInstallation[]>("/installations");
}

export function lockInstallation(installationId: string): Promise<ProductInstallation> {
  return postJson<ProductInstallation>(`/installations/${encodeURIComponent(installationId)}/lock`, {});
}

export function unlockInstallation(installationId: string): Promise<ProductInstallation> {
  return postJson<ProductInstallation>(`/installations/${encodeURIComponent(installationId)}/unlock`, {});
}

export function upgradeInstallation(installationId: string, releaseId: string): Promise<ProductInstallation> {
  return postJson<ProductInstallation>(`/installations/${encodeURIComponent(installationId)}/upgrade`, {
    release_id: releaseId
  });
}

// ---------------------------------------------------------------------------
// Code (dev-toolchain + compute modules)
// ---------------------------------------------------------------------------

export function listRepositories(): Promise<CodeRepository[]> {
  return api<CodeRepository[]>("/code-repositories");
}

export function createRepository(body: RepoCreateBody): Promise<CodeRepository> {
  return postJson<CodeRepository>("/code-repositories", body);
}

export function listWorkbooks(): Promise<CodeWorkbook[]> {
  return api<CodeWorkbook[]>("/code-workbooks");
}

export function createWorkbook(body: WorkbookCreateBody): Promise<CodeWorkbook> {
  return postJson<CodeWorkbook>("/code-workbooks", body);
}

export function listComputeModules(): Promise<ComputeModule[]> {
  return api<ComputeModule[]>("/compute-modules");
}

export function createComputeModule(body: ComputeModuleCreateBody): Promise<ComputeModule> {
  return postJson<ComputeModule>("/compute-modules", body);
}

export function runComputeModule(moduleId: string, body: ComputeRunBody): Promise<ComputeRunResult> {
  return postJson<ComputeRunResult>(`/compute-modules/${encodeURIComponent(moduleId)}/run`, body);
}
