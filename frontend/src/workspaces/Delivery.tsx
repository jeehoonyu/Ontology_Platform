import { useState } from "react";
import {
  createComputeModule,
  createProduct,
  createRelease,
  createRepository,
  createWorkbook,
  installProduct,
  listComputeModules,
  listInstallations,
  listMarketplace,
  listProducts,
  listRepositories,
  listWorkbooks,
  lockInstallation,
  runComputeModule,
  unlockInstallation,
  upgradeInstallation,
  type ComputeModule,
  type ComputeRunResult,
  type MarketplaceEntry,
  type ProductInstallation
} from "../api/deliveryApi";
import {
  DataTable,
  DeveloperEvidence,
  EmptyState,
  ErrorBanner,
  KeyValueGrid,
  LoadingState,
  Metric,
  Panel,
  StatusBadge
} from "../components/data/DataDisplay";
import { useAsyncState } from "../hooks/useAsyncState";
import { classNames } from "../utils/format";
import type { TableRow } from "../types";

type SectionId = "products" | "marketplace" | "code";

const SECTIONS: Array<{ id: SectionId; label: string; hint: string }> = [
  { id: "products", label: "Products", hint: "Publishable DevOps bundles and releases" },
  { id: "marketplace", label: "Marketplace", hint: "Install products and manage installations" },
  { id: "code", label: "Code", hint: "Repositories, workbooks, compute modules" }
];

const PRODUCT_MODES = ["bootstrap", "production", "singleton"];
const RELEASE_CHANNELS = ["stable", "beta"];

export function Delivery() {
  const [section, setSection] = useState<SectionId>("products");
  const [refreshKey, setRefreshKey] = useState(0);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");

  const products = useAsyncState(listProducts, [refreshKey]);
  const marketplace = useAsyncState(listMarketplace, [refreshKey]);
  const installations = useAsyncState(listInstallations, [refreshKey]);
  const repositories = useAsyncState(listRepositories, [refreshKey]);
  const workbooks = useAsyncState(listWorkbooks, [refreshKey]);
  const computeModules = useAsyncState(listComputeModules, [refreshKey]);

  function reload() {
    setRefreshKey((key) => key + 1);
  }

  async function runAction(label: string, fn: () => Promise<unknown>) {
    setActionError("");
    setNotice("");
    try {
      await fn();
      setNotice(label);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  const anyLoading =
    products.loading ||
    marketplace.loading ||
    installations.loading ||
    repositories.loading ||
    workbooks.loading ||
    computeModules.loading;

  const loadError =
    products.error ||
    marketplace.error ||
    installations.error ||
    repositories.error ||
    workbooks.error ||
    computeModules.error;

  return (
    <section className="workbench-page">
      <header className="manager-topbar">
        <div>
          <strong>Delivery</strong>
          <span>Marketplace, DevOps products, and the developer toolchain</span>
        </div>
        <div className="button-row">
          <button onClick={reload}>Refresh</button>
        </div>
      </header>

      <div className="button-row top-actions">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            className={classNames("nav-item", section === item.id && "active")}
            onClick={() => setSection(item.id)}
          >
            <strong>{item.label}</strong>
            <span>{item.hint}</span>
          </button>
        ))}
      </div>

      <div className="grid metrics">
        <Metric label="Products" value={products.value?.length ?? 0} />
        <Metric label="Marketplace listings" value={marketplace.value?.length ?? 0} />
        <Metric label="Installations" value={installations.value?.length ?? 0} />
        <Metric label="Repositories" value={repositories.value?.length ?? 0} />
        <Metric label="Workbooks" value={workbooks.value?.length ?? 0} />
        <Metric label="Compute modules" value={computeModules.value?.length ?? 0} />
      </div>

      {anyLoading && <LoadingState label="Loading delivery endpoints..." />}
      <ErrorBanner message={loadError} />
      {actionError ? <ErrorBanner message={actionError} /> : null}
      {notice ? <div className="notice">{notice}</div> : null}

      {section === "products" && (
        <ProductsSection
          products={products.value || []}
          onCreateProduct={runAction}
          onCreateRelease={runAction}
        />
      )}
      {section === "marketplace" && (
        <MarketplaceSection
          entries={marketplace.value || []}
          installations={installations.value || []}
          onRun={runAction}
        />
      )}
      {section === "code" && (
        <CodeSection
          repositories={repositories.value || []}
          workbooks={workbooks.value || []}
          computeModules={computeModules.value || []}
          onRun={runAction}
        />
      )}
    </section>
  );
}

type RunAction = (label: string, fn: () => Promise<unknown>) => Promise<void>;

// ---------------------------------------------------------------------------
// Products
// ---------------------------------------------------------------------------

function ProductsSection({
  products,
  onCreateProduct,
  onCreateRelease
}: {
  products: Array<import("../api/deliveryApi").DevopsProduct>;
  onCreateProduct: RunAction;
  onCreateRelease: RunAction;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState("bootstrap");
  const [releaseProductId, setReleaseProductId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [channel, setChannel] = useState("stable");

  const productRows: TableRow[] = products.map((product) => ({
    id: product.id,
    display_name: product.display_name,
    publisher: product.publisher,
    mode: product.mode,
    resources: product.resources.length,
    created_at: product.created_at
  }));

  async function submitProduct() {
    const display_name = name.trim();
    if (!display_name) return;
    await onCreateProduct(`Product "${display_name}" created`, () =>
      createProduct({ display_name, description: description.trim() || undefined, mode })
    );
    setName("");
    setDescription("");
  }

  async function submitRelease() {
    const productId = releaseProductId || products[0]?.id;
    const trimmedVersion = version.trim();
    if (!productId || !trimmedVersion) return;
    await onCreateRelease(`Release ${trimmedVersion} added`, () =>
      createRelease(productId, { version: trimmedVersion, channel })
    );
    setVersion("1.0.0");
  }

  return (
    <>
      <div className="two-col">
        <Panel title="Create Product" action={<button onClick={submitProduct} disabled={!name.trim()}>Create product</button>}>
          <div className="metadata-edit-grid">
            <label>
              <span>Display name</span>
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Reliability Starter Pack" />
            </label>
            <label>
              <span>Description</span>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What this product bundles" />
            </label>
            <label>
              <span>Install mode</span>
              <select value={mode} onChange={(event) => setMode(event.target.value)}>
                {PRODUCT_MODES.map((option) => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>
          </div>
        </Panel>
        <Panel title="Publish Release" action={<button onClick={submitRelease} disabled={!products.length || !version.trim()}>Add release</button>}>
          {products.length ? (
            <div className="metadata-edit-grid">
              <label>
                <span>Product</span>
                <select value={releaseProductId || products[0]?.id} onChange={(event) => setReleaseProductId(event.target.value)}>
                  {products.map((product) => <option key={product.id} value={product.id}>{product.display_name}</option>)}
                </select>
              </label>
              <label>
                <span>Version</span>
                <input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="1.0.0" />
              </label>
              <label>
                <span>Channel</span>
                <select value={channel} onChange={(event) => setChannel(event.target.value)}>
                  {RELEASE_CHANNELS.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </label>
            </div>
          ) : (
            <EmptyState title="No products yet" description="Create a product before publishing a release." />
          )}
        </Panel>
      </div>
      <Panel title={`Products ${products.length}`}>
        <DataTable rows={productRows} empty="No products yet. Create one to publish releases and list it on the marketplace." />
      </Panel>
    </>
  );
}

// ---------------------------------------------------------------------------
// Marketplace + installations
// ---------------------------------------------------------------------------

function MarketplaceSection({
  entries,
  installations,
  onRun
}: {
  entries: MarketplaceEntry[];
  installations: ProductInstallation[];
  onRun: RunAction;
}) {
  const [selectedProductId, setSelectedProductId] = useState("");
  const [targetProject, setTargetProject] = useState("");
  const [installMode, setInstallMode] = useState("");

  const activeProductId = selectedProductId || entries[0]?.id || "";
  const selectedEntry = entries.find((entry) => entry.id === activeProductId) || null;
  const latestByProduct = new Map(entries.map((entry) => [entry.id, entry.latest_release?.id]));

  const listingRows: TableRow[] = entries.map((entry) => ({
    id: entry.id,
    display_name: entry.display_name,
    publisher: entry.publisher,
    latest_version: entry.latest_release?.version ?? "—",
    channel: entry.latest_release?.channel ?? "—",
    resources: entry.resources.length
  }));

  async function install() {
    if (!activeProductId || !targetProject.trim()) return;
    const label = `Installed ${selectedEntry?.display_name || activeProductId} into ${targetProject.trim()}`;
    await onRun(label, () =>
      installProduct(activeProductId, {
        target_project: targetProject.trim(),
        mode: installMode || undefined
      })
    );
    setTargetProject("");
  }

  return (
    <>
      <Panel title={`Marketplace ${entries.length}`}>
        <DataTable rows={listingRows} empty="No marketplace listings. Publish a product release to make it installable." />
      </Panel>
      <Panel title="Install a Product" action={<button onClick={install} disabled={!activeProductId || !targetProject.trim() || !selectedEntry?.latest_release}>Install</button>}>
        {entries.length ? (
          <>
            <div className="metadata-edit-grid">
              <label>
                <span>Product</span>
                <select value={activeProductId} onChange={(event) => setSelectedProductId(event.target.value)}>
                  {entries.map((entry) => <option key={entry.id} value={entry.id}>{entry.display_name}</option>)}
                </select>
              </label>
              <label>
                <span>Target project</span>
                <input value={targetProject} onChange={(event) => setTargetProject(event.target.value)} placeholder="reliability-prod" />
              </label>
              <label>
                <span>Mode (optional)</span>
                <select value={installMode} onChange={(event) => setInstallMode(event.target.value)}>
                  <option value="">Product default</option>
                  {PRODUCT_MODES.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </label>
            </div>
            {selectedEntry && !selectedEntry.latest_release ? (
              <div className="empty">This product has no release yet. Publish a release in the Products tab before installing.</div>
            ) : null}
          </>
        ) : (
          <EmptyState title="Nothing to install" description="Create a product and publish a release first." />
        )}
      </Panel>
      <Panel title={`Installations ${installations.length}`}>
        {installations.length ? (
          <div className="section-card-grid">
            {installations.map((installation) => (
              <InstallationCard
                key={installation.id}
                installation={installation}
                latestReleaseId={latestByProduct.get(installation.product_id)}
                onRun={onRun}
              />
            ))}
          </div>
        ) : (
          <EmptyState title="No installations yet" description="Install a product above to manage its lifecycle here." />
        )}
      </Panel>
    </>
  );
}

function InstallationCard({
  installation,
  latestReleaseId,
  onRun
}: {
  installation: ProductInstallation;
  latestReleaseId: string | undefined;
  onRun: RunAction;
}) {
  const canUpgrade = Boolean(latestReleaseId) && latestReleaseId !== installation.release_id && !installation.locked;

  return (
    <article className="section-card">
      <header>
        <div>
          <strong>{installation.target_project}</strong>
          <span>{installation.product_id}</span>
        </div>
        <StatusBadge value={installation.status} />
      </header>
      <div className="manager-chip-row">
        <StatusBadge value={installation.mode} />
        <StatusBadge value={installation.locked ? "locked" : "unlocked"} />
        <StatusBadge value={`channel: ${installation.release_channel}`} />
        <StatusBadge value={installation.auto_upgrade ? "auto-upgrade" : "manual"} />
      </div>
      <KeyValueGrid data={{
        installation_id: installation.id,
        release_id: installation.release_id,
        updated_at: installation.updated_at
      }} />
      <div className="button-row">
        {installation.locked ? (
          <button onClick={() => onRun(`Unlocked ${installation.target_project}`, () => unlockInstallation(installation.id))}>Unlock</button>
        ) : (
          <button onClick={() => onRun(`Locked ${installation.target_project}`, () => lockInstallation(installation.id))}>Lock</button>
        )}
        <button
          disabled={!canUpgrade}
          title={installation.locked ? "Unlock before upgrading" : latestReleaseId ? "" : "No newer release available"}
          onClick={() => latestReleaseId && onRun(`Upgraded ${installation.target_project}`, () => upgradeInstallation(installation.id, latestReleaseId))}
        >
          Upgrade to latest
        </button>
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Code (repositories, workbooks, compute modules)
// ---------------------------------------------------------------------------

function CodeSection({
  repositories,
  workbooks,
  computeModules,
  onRun
}: {
  repositories: Array<import("../api/deliveryApi").CodeRepository>;
  workbooks: Array<import("../api/deliveryApi").CodeWorkbook>;
  computeModules: ComputeModule[];
  onRun: RunAction;
}) {
  const [repoName, setRepoName] = useState("");
  const [repoLanguage, setRepoLanguage] = useState("python");
  const [workbookName, setWorkbookName] = useState("");
  const [moduleName, setModuleName] = useState("");
  const [moduleImage, setModuleImage] = useState("python:3.11-slim");
  const [moduleEntrypoint, setModuleEntrypoint] = useState("main.py");
  const [selectedModuleId, setSelectedModuleId] = useState("");
  const [runResult, setRunResult] = useState<ComputeRunResult | null>(null);
  const [runError, setRunError] = useState("");

  const activeModuleId = selectedModuleId || computeModules[0]?.id || "";

  const repoRows: TableRow[] = repositories.map((repo) => ({
    id: repo.id,
    display_name: repo.display_name,
    language: repo.language,
    template: repo.template,
    default_branch: repo.default_branch
  }));
  const workbookRows: TableRow[] = workbooks.map((workbook) => ({
    id: workbook.id,
    display_name: workbook.display_name,
    language: workbook.language,
    nodes: workbook.nodes.length
  }));
  const moduleRows: TableRow[] = computeModules.map((module) => ({
    id: module.id,
    display_name: module.display_name,
    image: module.image,
    mode: module.mode,
    status: module.status
  }));

  async function submitRepo() {
    const display_name = repoName.trim();
    if (!display_name) return;
    await onRun(`Repository "${display_name}" created`, () => createRepository({ display_name, language: repoLanguage }));
    setRepoName("");
  }

  async function submitWorkbook() {
    const display_name = workbookName.trim();
    if (!display_name) return;
    await onRun(`Workbook "${display_name}" created`, () => createWorkbook({ display_name }));
    setWorkbookName("");
  }

  async function submitModule() {
    const display_name = moduleName.trim();
    if (!display_name || !moduleImage.trim() || !moduleEntrypoint.trim()) return;
    await onRun(`Compute module "${display_name}" created`, () =>
      createComputeModule({ display_name, image: moduleImage.trim(), entrypoint: moduleEntrypoint.trim() })
    );
    setModuleName("");
  }

  async function runModule() {
    if (!activeModuleId) return;
    setRunError("");
    setRunResult(null);
    try {
      const result = await runComputeModule(activeModuleId, {
        records: [
          { asset_id: "asset_1", status: "running", vibration: 3 },
          { asset_id: "asset_2", status: "degraded", vibration: 9 }
        ],
        spec: [
          { op: "map", source: "status", target: "status_upper", fn: "upper" },
          { op: "aggregate", field: "vibration", agg: "sum" }
        ]
      });
      setRunResult(result);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <div className="two-col">
        <Panel title="Create Repository" action={<button onClick={submitRepo} disabled={!repoName.trim()}>Create repo</button>}>
          <div className="metadata-edit-grid">
            <label>
              <span>Display name</span>
              <input value={repoName} onChange={(event) => setRepoName(event.target.value)} placeholder="asset-transforms" />
            </label>
            <label>
              <span>Language</span>
              <select value={repoLanguage} onChange={(event) => setRepoLanguage(event.target.value)}>
                {["python", "java", "typescript", "sql"].map((option) => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>
          </div>
        </Panel>
        <Panel title="Create Workbook" action={<button onClick={submitWorkbook} disabled={!workbookName.trim()}>Create workbook</button>}>
          <div className="metadata-edit-grid">
            <label>
              <span>Display name</span>
              <input value={workbookName} onChange={(event) => setWorkbookName(event.target.value)} placeholder="exploration-notebook" />
            </label>
          </div>
        </Panel>
      </div>

      <div className="two-col">
        <Panel title={`Repositories ${repositories.length}`}>
          <DataTable rows={repoRows} empty="No repositories yet." />
        </Panel>
        <Panel title={`Workbooks ${workbooks.length}`}>
          <DataTable rows={workbookRows} empty="No workbooks yet." />
        </Panel>
      </div>

      <Panel title="Create Compute Module" action={<button onClick={submitModule} disabled={!moduleName.trim() || !moduleImage.trim() || !moduleEntrypoint.trim()}>Create module</button>}>
        <div className="metadata-edit-grid">
          <label>
            <span>Display name</span>
            <input value={moduleName} onChange={(event) => setModuleName(event.target.value)} placeholder="reliability-transform" />
          </label>
          <label>
            <span>Image</span>
            <input value={moduleImage} onChange={(event) => setModuleImage(event.target.value)} placeholder="python:3.11-slim" />
          </label>
          <label>
            <span>Entrypoint</span>
            <input value={moduleEntrypoint} onChange={(event) => setModuleEntrypoint(event.target.value)} placeholder="main.py" />
          </label>
        </div>
      </Panel>

      <Panel
        title={`Compute Modules ${computeModules.length}`}
        action={
          <div className="button-row">
            {computeModules.length ? (
              <select value={activeModuleId} onChange={(event) => setSelectedModuleId(event.target.value)}>
                {computeModules.map((module) => <option key={module.id} value={module.id}>{module.display_name}</option>)}
              </select>
            ) : null}
            <button onClick={runModule} disabled={!activeModuleId}>Run module</button>
          </div>
        }
      >
        <DataTable rows={moduleRows} empty="No compute modules yet." />
        {runError ? <ErrorBanner message={runError} /> : null}
        {runResult ? (
          <div className="summary-list">
            <KeyValueGrid data={{ module_id: runResult.module_id, mode: runResult.mode }} />
            <DataTable rows={runResult.trace} empty="No trace steps." />
            <DeveloperEvidence title="Developer evidence: run result">
              <pre>{JSON.stringify(runResult.result, null, 2)}</pre>
            </DeveloperEvidence>
          </div>
        ) : null}
      </Panel>
    </>
  );
}
