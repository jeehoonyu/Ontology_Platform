from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any, List

# --- COMMON ---
class ResourceBase(BaseModel):
    id: str
    display_name: str
    description: Optional[str] = None

# --- OBJECT TYPES ---
class ObjectTypeCreate(ResourceBase):
    project_id: str = "default"
    properties: Dict[str, Any]

class ObjectType(ObjectTypeCreate):
    created_at: int
    updated_at: int
    
    model_config = ConfigDict(from_attributes=True)

# --- OBJECT INSTANCES ---
class ObjectInstanceCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    object_type_id: str
    properties: Dict[str, Any]
    source_asset_id: Optional[str] = None
    lineage: Dict[str, Any] = Field(default_factory=dict)

class ObjectInstance(BaseModel):
    id: str
    project_id: str
    object_type_id: str
    properties: Dict[str, Any]
    source_asset_id: Optional[str] = None
    lineage: Dict[str, Any] = Field(default_factory=dict)
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

# --- LINK TYPES ---
class LinkTypeCreate(ResourceBase):
    project_id: str = "default"
    source_object_type_id: str
    target_object_type_id: str
    cardinality: str # ONE_TO_ONE, ONE_TO_MANY, MANY_TO_MANY

class LinkType(LinkTypeCreate):
    model_config = ConfigDict(from_attributes=True)

class LinkTypePatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    source_object_type_id: Optional[str] = None
    target_object_type_id: Optional[str] = None
    cardinality: Optional[str] = None

class LinkInstanceCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    link_type_id: str
    source_object_id: str
    target_object_id: str
    properties: Dict[str, Any] = Field(default_factory=dict)

class LinkInstance(BaseModel):
    id: str
    project_id: str
    link_type_id: str
    source_object_id: str
    target_object_id: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: int

    model_config = ConfigDict(from_attributes=True)

# --- OBJECT SETS AND ONTOLOGY VALIDATION ---
class ObjectSetQuery(BaseModel):
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    limit: int = 100
    offset: int = 0
    cursor: Optional[str] = None
    with_total: bool = True
    include_lineage: bool = True

class ObjectSetResponse(BaseModel):
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    total: Optional[int] = None  # omitted when with_total=false (avoids a full-scan count)
    count: int
    objects: List[Dict[str, Any]] = Field(default_factory=list)
    next_cursor: Optional[str] = None

class ObjectSetAggregateRequest(BaseModel):
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    group_by: Optional[str] = None
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    # How stale a stored count may be and still be served. Omitted means any
    # age is acceptable, which is the existing behaviour: a rollup computed once
    # would otherwise be served forever, and a caller that cannot bound the age
    # cannot tell a current answer from an abandoned one.
    max_rollup_age_seconds: Optional[int] = None


class FacetRollupRefreshRequest(BaseModel):
    object_type_id: str
    field: str


class FacetRollupRefreshResponse(BaseModel):
    object_type_id: str
    field: str
    project_id: str
    computed_at: int
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    refresh_seconds: float

class ObjectSetAggregateResponse(BaseModel):
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    group_by: Optional[str] = None
    total: int
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    # "exact" when the aggregate was computed, "rollup" when served from stored
    # counts. Declared here because a response model silently drops fields it
    # does not name, and a caller cannot tell a fresh count from a stored one
    # without being told which it got.
    source: Optional[str] = None
    computed_at: Optional[int] = None

class ObjectSetSearchAroundRequest(BaseModel):
    object_ids: List[str]
    link_type_id: Optional[str] = None
    direction: str = "both"
    target_object_type_id: Optional[str] = None
    depth: int = 1

class ObjectSetSearchAroundResponse(BaseModel):
    seed_object_ids: List[str]
    depth: int
    direction: str
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)

class SavedObjectSetCreate(ResourceBase):
    project_id: str = "default"
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    owner: str = "system"

class SavedObjectSet(SavedObjectSetCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class ObjectProfileResponse(BaseModel):
    object: Dict[str, Any]
    object_type: Dict[str, Any]
    inbound_links: List[Dict[str, Any]] = Field(default_factory=list)
    outbound_links: List[Dict[str, Any]] = Field(default_factory=list)
    linked_objects: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)

class ValidationIssue(BaseModel):
    severity: str
    code: str
    resource_type: str
    resource_id: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

class OntologyValidationResponse(BaseModel):
    status: str
    summary: Dict[str, Any]
    issues: List[ValidationIssue] = Field(default_factory=list)

# --- GIS AND SPATIAL INTELLIGENCE ---
class GISSpatialQuery(BaseModel):
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    geometry_field: str = "geometry"
    near: Optional[Dict[str, Any]] = None
    radius_meters: Optional[float] = None
    bbox: Optional[List[float]] = None
    polygon: Optional[Dict[str, Any]] = None
    limit: int = 100
    include_lineage: bool = True

class GISSpatialQueryResponse(BaseModel):
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    geometry_field: str
    query: Dict[str, Any] = Field(default_factory=dict)
    total: int
    count: int
    objects: List[Dict[str, Any]] = Field(default_factory=list)

class GISFeatureCollectionRequest(BaseModel):
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    geometry_field: str = "geometry"
    limit: int = 1000
    include_properties: bool = True

class GISFeatureCollectionResponse(BaseModel):
    type: str = "FeatureCollection"
    features: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class GISGeofenceRequest(BaseModel):
    object_type_id: str
    geofence: Optional[Dict[str, Any]] = None
    bbox: Optional[List[float]] = None
    filters: Any = Field(default_factory=dict)
    geometry_field: str = "geometry"
    limit: int = 1000

class GISGeofenceResponse(BaseModel):
    object_type_id: str
    geometry_field: str
    geofence: Dict[str, Any]
    summary: Dict[str, int]
    inside: List[Dict[str, Any]] = Field(default_factory=list)
    outside: List[Dict[str, Any]] = Field(default_factory=list)

class MGRSEncodeRequest(BaseModel):
    latitude: float
    longitude: float
    precision: int = 5

class MGRSDecodeRequest(BaseModel):
    mgrs: str
    center: bool = True

class MGRSCoordinateResponse(BaseModel):
    mgrs: str
    zone: int
    band: str
    latitude: float
    longitude: float
    precision: int
    bbox: Optional[List[float]] = None
    utm: Dict[str, Any] = Field(default_factory=dict)

class MapLayerDefinitionCreate(ResourceBase):
    project_id: str = "default"
    object_type_id: str
    saved_object_set_id: Optional[str] = None
    geometry_field: str = "geometry"
    filters: Any = Field(default_factory=dict)
    style: Dict[str, Any] = Field(default_factory=dict)
    visible: bool = True
    owner: str = "system"

class MapLayerDefinition(MapLayerDefinitionCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class MapLayerFeatureCollectionResponse(GISFeatureCollectionResponse):
    layer: Dict[str, Any] = Field(default_factory=dict)

# --- ACTION TYPES ---
class ActionTypeCreate(ResourceBase):
    project_id: str = "default"
    parameters: Dict[str, Any]
    rules: Dict[str, Any]

class ActionType(ActionTypeCreate):
    model_config = ConfigDict(from_attributes=True)

class ActionTypePatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    rules: Optional[Dict[str, Any]] = None

# --- ACTION EXECUTION ---
class ActionExecutionRequest(BaseModel):
    action_type_id: str
    parameters: Dict[str, Any]
    idempotency_key: str
    actor: str = "system"
    approval_request_id: Optional[str] = None

class ActionExecutionResponse(BaseModel):
    status: str
    message: str
    outbox_event_id: Optional[str] = None
    approval_request_id: Optional[str] = None
    mutated_object_ids: List[str] = Field(default_factory=list)

# --- DATA ASSETS AND PIPELINES ---
class DataAssetCreate(ResourceBase):
    project_id: str = "default"
    kind: str = "dataset"
    asset_schema: Dict[str, Any] = Field(default_factory=dict)
    records: List[Dict[str, Any]] = Field(default_factory=list)

class DataAsset(DataAssetCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class DataExpectationsRequest(BaseModel):
    expectations: Any = Field(default_factory=dict)

class DataExpectationsResponse(BaseModel):
    status: str
    records_checked: int
    summary: Dict[str, Any] = Field(default_factory=dict)
    checks: List[Dict[str, Any]] = Field(default_factory=list)

class PipelineDefinitionCreate(ResourceBase):
    project_id: str = "default"
    input_asset_id: str
    output_asset_id: Optional[str] = None
    mode: str = "batch"
    schedule: Optional[str] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)

class PipelineDefinition(PipelineDefinitionCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class PipelineRun(BaseModel):
    id: str
    project_id: str
    pipeline_id: str
    status: str
    input_asset_id: str
    output_asset_id: Optional[str] = None
    records_in: int
    records_out: int
    lineage: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: int
    completed_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

# --- MODEL ENDPOINTS ---
class ModelEndpointCreate(ResourceBase):
    project_id: str = "default"
    provider: str
    model_name: str
    purpose: str = "general"
    policy: Dict[str, Any] = Field(default_factory=dict)
    status: str = "ACTIVE"

class ModelEndpoint(ModelEndpointCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

# --- GOVERNANCE ---
class ApprovalRequest(BaseModel):
    id: str
    project_id: str
    action_type_id: str
    requester: str
    parameters: Dict[str, Any]
    status: str
    reason: Optional[str] = None
    created_at: int
    decided_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class ApprovalDecisionRequest(BaseModel):
    actor: str
    decision: str
    reason: Optional[str] = None

class AuditLog(BaseModel):
    id: str
    actor: str
    event_type: str
    subject_type: str
    subject_id: str
    payload: Optional[Dict[str, Any]] = None
    created_at: int

    model_config = ConfigDict(from_attributes=True)

# --- AGENTS AND EVALS ---
class AgentDefinitionCreate(ResourceBase):
    project_id: str = "default"
    system_prompt: Optional[str] = None
    allowed_object_types: List[str] = Field(default_factory=list)
    allowed_actions: List[str] = Field(default_factory=list)
    model_endpoint_id: Optional[str] = None
    approval_required: bool = True

class AgentDefinition(AgentDefinitionCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class AgentSessionCreate(BaseModel):
    user_prompt: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    max_context_objects: int = 5

class AgentSession(BaseModel):
    id: str
    agent_id: str
    user_prompt: str
    status: str
    context: Dict[str, Any] = Field(default_factory=dict)
    plan: Dict[str, Any] = Field(default_factory=dict)
    proposed_actions: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: int
    completed_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

# --- AIP TOOLING ---
class AIPTool(BaseModel):
    id: str
    display_name: str
    public_palantir_equivalent: str
    local_endpoint: str
    status: str
    notes: str

class AssistRequest(BaseModel):
    prompt: str
    application_context: Optional[str] = None
    include_mcp_context: bool = True

class AssistResponse(BaseModel):
    answer: str
    referenced_tools: List[str] = Field(default_factory=list)
    suggested_endpoints: List[str] = Field(default_factory=list)
    context_summary: Dict[str, Any] = Field(default_factory=dict)

class PipelineAssistRequest(BaseModel):
    prompt: str
    sample_fields: List[str] = Field(default_factory=list)

class PipelineAssistResponse(BaseModel):
    suggested_name: str
    suggested_description: str
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    rationale: List[str] = Field(default_factory=list)

class DocumentExtractionRequest(BaseModel):
    text: str
    extraction_schema: Dict[str, Any] = Field(default_factory=dict)

class DocumentExtractionResponse(BaseModel):
    fields: Dict[str, Any] = Field(default_factory=dict)
    entities: Dict[str, List[str]] = Field(default_factory=dict)
    summary: str
    confidence: float

class NotepadTransformRequest(BaseModel):
    text: str
    operation: str
    instruction: Optional[str] = None
    target_language: Optional[str] = None

class NotepadTransformResponse(BaseModel):
    operation: str
    text: str
    notes: str

class SchedulerRequest(BaseModel):
    prompt: str

class SchedulerResponse(BaseModel):
    cron: str
    timezone: str = "UTC"
    explanation: str

class DomainBootstrapRequest(BaseModel):
    actor: str = "system"
    run_pipelines: bool = True

class DomainBootstrapResponse(BaseModel):
    domain: str
    resources: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_pipeline_order: List[str] = Field(default_factory=list)
    pipeline_runs: List[Dict[str, Any]] = Field(default_factory=list)
    agent_id: str
    logic_function_id: str
    eval_suite_id: str
    automation_id: str

class MaintenanceSummary(BaseModel):
    domain: str
    object_counts: Dict[str, int]
    open_work_orders: List[Dict[str, Any]] = Field(default_factory=list)
    agent_id: str
    logic_function_id: str
    eval_suite_id: str
    automation_id: str

class SentinelBootstrapRequest(BaseModel):
    actor: str = "system"

class SentinelBootstrapResponse(BaseModel):
    domain: str
    resources: List[Dict[str, Any]] = Field(default_factory=list)
    agent_id: str
    eval_suite_id: str
    object_types: List[str] = Field(default_factory=list)

class SentinelSummary(BaseModel):
    domain: str
    object_counts: Dict[str, int]
    open_cases: List[Dict[str, Any]] = Field(default_factory=list)
    agent_id: str
    eval_suite_id: str

class SentinelCaseCreate(BaseModel):
    id: Optional[str] = None
    title: str
    description: str = ""
    owner: str = "analyst"
    sensitivity: str = "internal"
    status: str = "OPEN"
    actor: str = "analyst"

class SentinelEvidenceIngestRequest(BaseModel):
    id: Optional[str] = None
    title: str
    text: str
    source_uri: Optional[str] = None
    source_type: str = "document"
    sensitivity: str = "internal"
    extraction_schema: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "analyst"

class SentinelTaskCreate(BaseModel):
    id: Optional[str] = None
    title: str
    description: str = ""
    priority: str = "normal"
    status: str = "OPEN"
    assignee: Optional[str] = None
    actor: str = "analyst"

class SentinelFindingCreate(BaseModel):
    id: Optional[str] = None
    title: str
    summary: str
    confidence: float = 0.5
    status: str = "DRAFT"
    actor: str = "analyst"

class SentinelGraphQuery(BaseModel):
    object_id: str
    depth: int = 1

class SentinelPathQuery(BaseModel):
    source_id: str
    target_id: str
    max_depth: int = 6

class SentinelCopilotRequest(BaseModel):
    actor: str = "analyst"
    instruction: Optional[str] = None

class ThreadCreate(BaseModel):
    title: str
    owner: str = "system"
    resources: List[Dict[str, Any]] = Field(default_factory=list)

class ThreadMessageCreate(BaseModel):
    role: str = "user"
    content: str
    attachments: List[Dict[str, Any]] = Field(default_factory=list)

class AIPThread(BaseModel):
    id: str
    title: str
    owner: str
    resources: List[Dict[str, Any]] = Field(default_factory=list)
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class LogicFunctionCreate(ResourceBase):
    project_id: str = "default"
    blocks: List[Dict[str, Any]] = Field(default_factory=list)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = True

class LogicFunction(LogicFunctionCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class LogicRunRequest(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "system"

class LogicRun(BaseModel):
    id: str
    logic_function_id: str
    status: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    trace: List[Dict[str, Any]] = Field(default_factory=list)
    proposed_actions: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: int
    completed_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class AutomationDefinitionCreate(ResourceBase):
    trigger: Dict[str, Any] = Field(default_factory=dict)
    condition: Dict[str, Any] = Field(default_factory=dict)
    effect: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

class AutomationDefinition(AutomationDefinitionCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class AutomationRun(BaseModel):
    id: str
    automation_id: str
    status: str
    condition_result: bool
    effect_result: Dict[str, Any] = Field(default_factory=dict)
    created_at: int
    completed_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class EvalSuiteCreate(ResourceBase):
    project_id: str = "default"
    target_agent_id: str
    cases: List[Dict[str, Any]] = Field(default_factory=list)
    criteria: Dict[str, Any] = Field(default_factory=dict)

class EvalSuite(EvalSuiteCreate):
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)

class EvalRun(BaseModel):
    id: str
    project_id: str
    suite_id: str
    status: str
    score: int
    results: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: int
    completed_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
