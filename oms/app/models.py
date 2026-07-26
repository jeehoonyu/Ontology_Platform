from typing import Optional
from sqlalchemy import String, Integer, JSON, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class ObjectType(Base):
    """
    Semantic definition of a real-world entity or event (e.g., facility, employee)
    """
    __tablename__ = "object_types"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    properties: Mapped[dict] = mapped_column(JSON) # Schema of properties
    
    # Audit fields
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class LinkType(Base):
    """
    Semantic relationship between two object types.
    """
    __tablename__ = "link_types"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_object_type_id: Mapped[str] = mapped_column(String, ForeignKey("object_types.id"))
    target_object_type_id: Mapped[str] = mapped_column(String, ForeignKey("object_types.id"))
    cardinality: Mapped[str] = mapped_column(String) # ONE_TO_ONE, ONE_TO_MANY, MANY_TO_MANY
    
    source_type = relationship("ObjectType", foreign_keys=[source_object_type_id])
    target_type = relationship("ObjectType", foreign_keys=[target_object_type_id])


class ActionType(Base):
    """
    Kinetic 'verbs' of the system to safely mutate objects.
    """
    __tablename__ = "action_types"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    parameters: Mapped[dict] = mapped_column(JSON) # Expected input schema
    rules: Mapped[dict] = mapped_column(JSON) # Validation and execution logic / side-effects


class ObjectInstance(Base):
    """
    Runtime object in the operational twin. Object types define the schema; instances
    hold current state materialized from pipelines, user edits, or agent actions.
    """
    __tablename__ = "object_instances"
    # Composite index for the common type-scoped + ordered/paginated scan.
    __table_args__ = (Index("ix_object_instances_type_created", "object_type_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    object_type_id: Mapped[str] = mapped_column(String, ForeignKey("object_types.id"), index=True)
    properties: Mapped[dict] = mapped_column(JSON)
    source_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    lineage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    object_type = relationship("ObjectType")


class LinkInstance(Base):
    """
    Runtime relationship between two object instances.
    """
    __tablename__ = "link_instances"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    link_type_id: Mapped[str] = mapped_column(String, ForeignKey("link_types.id"), index=True)
    source_object_id: Mapped[str] = mapped_column(String, ForeignKey("object_instances.id"), index=True)
    target_object_id: Mapped[str] = mapped_column(String, ForeignKey("object_instances.id"), index=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)

    link_type = relationship("LinkType")
    source_object = relationship("ObjectInstance", foreign_keys=[source_object_id])
    target_object = relationship("ObjectInstance", foreign_keys=[target_object_id])


class DataAsset(Base):
    """
    Local dataset/file abstraction used by pipelines. Records are kept in JSON for
    this compact reference implementation; production deployments can swap this
    for object storage, Postgres JSONB, ClickHouse, or lakehouse tables.
    """
    __tablename__ = "data_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="dataset")
    asset_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    records: Mapped[list] = mapped_column(JSON, default=list)
    # Storage URI of the raw uploaded file (when ingested via /data-assets/{id}/upload)
    # and the format it was parsed from. Nullable so inline-JSON assets stay valid.
    file_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_format: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # csv|json|jsonl|parquet
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class PipelineDefinition(Base):
    """
    Declarative data pipeline. Steps use a small operation DSL implemented in
    runtime.py so pipelines can clean, enrich, and hydrate ontology objects.
    """
    __tablename__ = "pipeline_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    input_asset_id: Mapped[str] = mapped_column(String, ForeignKey("data_assets.id"), index=True)
    output_asset_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("data_assets.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String, default="batch")
    schedule: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    input_asset = relationship("DataAsset", foreign_keys=[input_asset_id])
    output_asset = relationship("DataAsset", foreign_keys=[output_asset_id])


class PipelineRun(Base):
    """
    Execution record with lineage and step metrics.
    """
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    pipeline_id: Mapped[str] = mapped_column(String, ForeignKey("pipeline_definitions.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    input_asset_id: Mapped[str] = mapped_column(String, index=True)
    output_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    records_in: Mapped[int] = mapped_column(Integer, default=0)
    records_out: Mapped[int] = mapped_column(Integer, default=0)
    lineage: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    pipeline = relationship("PipelineDefinition")


class ModelEndpoint(Base):
    """
    Governed model connection metadata. The local runtime does not call external
    LLMs by default, but agents and pipeline steps can reference registered models.
    """
    __tablename__ = "model_endpoints"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    model_name: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(String, default="general")
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class AgentDefinition(Base):
    """
    Ontology-grounded assistant configuration. Agents get scoped object context and
    action tools instead of unrestricted database access.
    """
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    system_prompt: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    allowed_object_types: Mapped[list] = mapped_column(JSON, default=list)
    allowed_actions: Mapped[list] = mapped_column(JSON, default=list)
    model_endpoint_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_endpoints.id"), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    model_endpoint = relationship("ModelEndpoint")


class AgentSession(Base):
    """
    A single agent run with retrieved context, generated plan, and proposed actions.
    """
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agent_definitions.id"), index=True)
    user_prompt: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="CREATED")
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    proposed_actions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    agent = relationship("AgentDefinition")


class AIPThread(Base):
    """
    Threaded ad-hoc workspace for prompts, document snippets, and referenced
    ontology resources.
    """
    __tablename__ = "aip_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String)
    owner: Mapped[str] = mapped_column(String, default="system")
    resources: Mapped[list] = mapped_column(JSON, default=list)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class SavedObjectSet(Base):
    """
    Persisted object-set definition. This mirrors the Foundry pattern where a
    saved exploration can be reused by applications, map layers, and agents.
    """
    __tablename__ = "saved_object_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    object_type_id: Mapped[str] = mapped_column(String, ForeignKey("object_types.id"), index=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    owner: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    object_type = relationship("ObjectType")


class MapLayerDefinition(Base):
    """
    Map layer configuration over an ontology object type or saved object set.
    Rendering stays local by returning GeoJSON FeatureCollections.
    """
    __tablename__ = "map_layer_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    object_type_id: Mapped[str] = mapped_column(String, ForeignKey("object_types.id"), index=True)
    saved_object_set_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("saved_object_sets.id"), nullable=True)
    geometry_field: Mapped[str] = mapped_column(String, default="geometry")
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    style: Mapped[dict] = mapped_column(JSON, default=dict)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    owner: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    object_type = relationship("ObjectType")
    saved_object_set = relationship("SavedObjectSet")


class LogicFunction(Base):
    """
    Local AIP Logic equivalent: a no-code/pro-code function composed from
    deterministic blocks that can retrieve context, call local helpers, or stage
    actions.
    """
    __tablename__ = "logic_functions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class LogicRun(Base):
    """
    Execution trace for a LogicFunction.
    """
    __tablename__ = "logic_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    logic_function_id: Mapped[str] = mapped_column(String, ForeignKey("logic_functions.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    trace: Mapped[list] = mapped_column(JSON, default=list)
    proposed_actions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    logic_function = relationship("LogicFunction")


class AutomationDefinition(Base):
    """
    Local Automate/Scheduler equivalent. A condition can watch object counts or
    cron-like schedules and an effect can run a pipeline or logic function.
    """
    __tablename__ = "automation_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    trigger: Mapped[dict] = mapped_column(JSON, default=dict)
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    effect: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class AutomationRun(Base):
    """
    Execution record for a local automation evaluation.
    """
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    automation_id: Mapped[str] = mapped_column(String, ForeignKey("automation_definitions.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    condition_result: Mapped[bool] = mapped_column(Boolean, default=False)
    effect_result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    automation = relationship("AutomationDefinition")


class EvalSuite(Base):
    """
    Deterministic eval suite for agent behavior and retrieval/action expectations.
    """
    __tablename__ = "eval_suites"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    target_agent_id: Mapped[str] = mapped_column(String, ForeignKey("agent_definitions.id"), index=True)
    cases: Mapped[list] = mapped_column(JSON, default=list)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    target_agent = relationship("AgentDefinition")


class EvalRun(Base):
    """
    Eval execution result with per-case scoring.
    """
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("eval_suites.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    score: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    suite = relationship("EvalSuite")
