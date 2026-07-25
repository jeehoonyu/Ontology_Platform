export type JsonValue = string | number | boolean | null | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue | undefined };

export interface ActionLink {
  id: string;
  label: string;
  method?: string;
  path?: string;
}

export interface StatusSummary {
  [key: string]: JsonValue | undefined;
}

export interface TableRow {
  [key: string]: JsonValue | undefined;
}

export interface EvidenceLink {
  kind: string;
  id?: string | null;
  href: string;
}

export interface UiWarning {
  id: string;
  message: string;
  severity?: string;
}

export interface UiSection {
  id: string;
  title: string;
  status?: string;
  description?: string;
  metrics?: StatusSummary;
  rows?: TableRow[];
  href?: string;
}

export interface HumanUiState {
  summary: StatusSummary;
  primary_actions: ActionLink[];
  sections: UiSection[];
  evidence_links: EvidenceLink[];
  warnings: UiWarning[];
  last_updated: number;
}

export interface WorkflowStep {
  id: string;
  label: string;
  status: string;
  evidence_id?: string | null;
  href?: string;
  graph_id?: string | null;
}

export interface WorkflowState {
  scenario_id: string;
  asset_id: string;
  current_step: string;
  completed_steps: string[];
  blocked_step?: WorkflowStep | null;
  next_action?: WorkflowStep | null;
  steps: WorkflowStep[];
  evidence_links: EvidenceLink[];
  summary: CommandCenterSummary;
}

export interface CommandCenterSummary {
  scenario_id?: string;
  asset_id?: string;
  kpis?: StatusSummary;
  high_risk_assets?: Array<{ object_id?: string; object?: JsonObject; risk?: JsonObject }>;
  alerts?: TableRow[];
  approvals?: TableRow[];
  latest_report?: JsonObject | null;
}

export interface CommandCenterUiState extends HumanUiState {
  workflow: WorkflowState;
  evaluator_summary: JsonObject;
}

export interface ImportsUiState extends HumanUiState {
  templates: TableRow[];
  jobs: TableRow[];
}

export interface ConnectorAdapterCatalogItem {
  id: string;
  source_types?: string[];
  modes?: string[];
  available: boolean;
  reason?: string;
  config_schema?: JsonObject;
}

export interface ConnectorAdapterCatalog {
  adapters: ConnectorAdapterCatalogItem[];
  plugin_modules: string[];
  runtime: string;
}

export interface ConnectionSource {
  id: string;
  project_id: string;
  display_name: string;
  source_type: string;
  config: JsonObject;
  uses_agent: boolean;
  status: string;
  created_at: number;
}

export interface ConnectorCredentialMetadata {
  id: string;
  source_id: string;
  credential_type: string;
  metadata: JsonObject;
  key_id: string;
  status: string;
  expires_at?: number | null;
  expired: boolean;
  created_by: string;
  created_at: number;
  rotated_at?: number | null;
}

export interface ConnectorFetchAttempt {
  id: string;
  source_id: string;
  adapter_id: string;
  operation: string;
  status: string;
  records_read: number;
  bytes_read: number;
  duration_ms: number;
  cursor_in?: string | null;
  cursor_out?: string | null;
  error?: string | null;
  created_at: number;
}

export interface ConnectorLivePreview {
  source_id: string;
  adapter_id: string;
  status: string;
  record_count: number;
  preview_rows: TableRow[];
  next_cursor?: JsonValue;
  bytes_read: number;
  metadata: JsonObject;
}

export interface ValidationUiState extends HumanUiState {
  rows: TableRow[];
}

export interface ProjectReadiness {
  status: string;
  checked_at: number;
  summary: StatusSummary;
  checks: TableRow[];
  recommended_actions: TableRow[];
  last_updated: number;
}

export interface JobSummary {
  counts: Record<string, number>;
  by_job_type: Record<string, Record<string, number>>;
  active_workers: number;
  active_leases: number;
  oldest_queued_seconds: number;
  reaped_stale_jobs: number;
  last_updated: number;
}

export interface PlatformJobEvent {
  id: number;
  event_type: string;
  status: string;
  payload: JsonObject;
  created_at: number;
}

export interface PlatformJob {
  id: string;
  job_type: string;
  status: string;
  subject_type?: string | null;
  subject_id?: string | null;
  progress: number;
  attempt: number;
  error?: string | null;
  result: JsonObject;
  execution: JsonObject;
  lease?: JsonObject | null;
  events?: PlatformJobEvent[];
  created_at: number;
  updated_at: number;
  completed_at?: number | null;
}

export interface AgentDefinition {
  id: string;
  display_name: string;
  description?: string | null;
  approval_required?: boolean;
  allowed_object_types?: string[];
  allowed_actions?: string[];
}

export interface AgentCitation {
  type: string;
  id: string;
}

export interface AgentToolCall {
  tool: string;
  type: string;
  input: JsonObject;
  output: JsonObject;
  citations: AgentCitation[];
  policy_decision: string;
  approval_gate: boolean;
  duration_ms: number;
}

export interface AgentProposedAction {
  action_type_id: string;
  parameters: JsonObject;
  requires_approval: boolean;
  policy_decision: string;
  approval_request_id?: string | null;
  executed: boolean;
}

export interface AgentRunResult {
  agent_id: string;
  prompt: string;
  retrieval: {
    retrieved_object_count?: number;
    ontology_packs?: JsonObject[];
    documents?: string[];
  };
  tool_calls: AgentToolCall[];
  proposed_actions: AgentProposedAction[];
  policy_summary: {
    decision?: string;
    approval_requests?: number;
    proposed_actions?: number;
    denied_tools?: number;
    direct_mutations?: number;
  };
  answer: string;
  run_id: string;
  execution_job_id?: string | null;
  created_at: number;
}

export interface PipelineGraph {
  id: string;
  display_name: string;
  description?: string | null;
  nodes: PipelineNodeRaw[];
  edges: PipelineEdge[];
  parameters: JsonObject;
  status: string;
  created_at: number;
  updated_at: number;
}

export interface PipelineNodeRaw {
  id?: string;
  type?: string;
  label?: string;
  position?: { x: number; y: number };
  config?: JsonObject;
}

export interface PipelineNode {
  id: string;
  label: string;
  type: string;
  category: string;
  description?: string;
  position: { x: number; y: number };
  config: JsonObject;
  ports: { inputs: string[]; outputs: string[] };
  status: string;
  errors: TableRow[];
  row_count?: number | null;
  schema?: { fields?: TableRow[] };
  sample?: TableRow[];
}

export interface PipelineEdge {
  id?: string;
  source: string;
  target: string;
  source_port?: string;
  target_port?: string;
}

export interface NodeTypeCatalogItem {
  type: string;
  label: string;
  category: string;
  description?: string;
}

export interface PipelineCanvasState {
  graph: PipelineGraph;
  toolbar_groups: Array<{ id: string; label: string; actions: string[] }>;
  node_library: NodeTypeCatalogItem[];
  legend: Array<{ category: string; label: string; color: string }>;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  selected_node?: PipelineNode | null;
  bottom_tabs: string[];
  outputs: JsonObject;
  validation: { status: string; errors: TableRow[]; warnings: TableRow[] };
  lineage: JsonObject;
  metrics: JsonObject;
  actions: ActionLink[];
}

export interface PipelineUiState {
  summary: StatusSummary;
  primary_actions: ActionLink[];
  graphs: PipelineGraph[];
  node_library: NodeTypeCatalogItem[];
  selected_canvas?: PipelineCanvasState | null;
  empty_state?: JsonObject | null;
  last_updated: number;
}

export interface NodePreview {
  graph_id: string;
  node_id: string;
  status: string;
  row_count: number;
  rows: TableRow[];
  schema: { fields?: TableRow[] };
  columns: TableRow[];
}

export interface NodeSuggestions {
  graph_id: string;
  node_id: string;
  suggestions: TableRow[];
  insertable_node_types: NodeTypeCatalogItem[];
  warnings: TableRow[];
  errors: TableRow[];
}

export interface PipelineContextAction {
  id: string;
  label: string;
  node_type: string;
}

export interface PipelineNodeDetails {
  graph_id: string;
  node_id: string;
  node: PipelineNode;
  metadata: JsonObject;
  preview: NodePreview;
  context_actions: PipelineContextAction[];
  suggestions: NodeSuggestions;
}

export interface PipelineOutputsState {
  graph_id: string;
  outputs: JsonObject;
  validation: PipelineCanvasState["validation"];
  legend: PipelineCanvasState["legend"];
  actions: ActionLink[];
  summary: StatusSummary;
}

export interface OntologyObjectSummary {
  id: string;
  display_name: string;
  description?: string | null;
  updated_at: number;
  property_count: number;
}

export interface OntologyManagerState {
  object_type: {
    id: string;
    rid: string;
    display_name: string;
    description?: string | null;
    plural_name: string;
    api_name: string;
    aliases: string[];
    point_of_contact: string;
    contributors: string[];
    ontology: string;
    status: string;
    visibility: string;
    index_status: string;
    edits: string;
    groups: string[];
    created_at: number;
    updated_at: number;
  };
  navigation: string[];
  cards: {
    properties: { count: number; rows: TableRow[] };
    action_types: { count: number; rows: TableRow[] };
    link_types: { count: number; rows: TableRow[] };
    datasources: { count: number; rows: TableRow[] };
    observability: JsonObject;
    dependents: { count: number; rows: TableRow[] };
  };
  primary_actions: ActionLink[];
  last_updated: number;
}

export interface OntologyWalkthrough {
  object_type_id: string;
  title: string;
  current_step_id: string;
  current_resource_id: string;
  steps: Array<{ id: string; title: string; resource: string; status: string }>;
  links: Array<{ label: string; path: string }>;
}

export interface OntologySectionState {
  object_type_id: string;
  section_id: string;
  title: string;
  summary: JsonObject;
  rows: TableRow[];
}

export interface OntologyFieldMapping {
  source_field: string;
  target_property: string;
}

export interface OntologyMappingPreview {
  asset: { id: string; display_name: string; row_count: number };
  object_type: { id: string; display_name: string; primary_key?: string | null };
  source_fields: Array<{ name: string; inferred_type: string; mapped: boolean }>;
  target_properties: Array<{ name: string; base_type?: string; type?: string; required?: boolean; mapped_from?: string | null }>;
  mappings: OntologyFieldMapping[];
  compatibility: Array<{ source_field: string; target_property: string; source_type: string; target_type: string; compatible: boolean }>;
  hydrated_preview: TableRow[];
  status: string;
  errors: TableRow[];
  warnings: TableRow[];
}

export interface OntologyUiState {
  summary: StatusSummary;
  primary_actions: ActionLink[];
  object_types: OntologyObjectSummary[];
  selected_object_type?: OntologyManagerState | null;
  empty_state?: JsonObject | null;
  last_updated: number;
}
