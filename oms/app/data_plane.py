"""Immutable dataset snapshots and portable pipeline execution plans.

Metadata stays transactional in Postgres/SQLite. Bulk rows are written through a
storage adapter so production can use S3-compatible object storage while local and
test deployments keep a deterministic filesystem backend.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, pipeline_builder_ops, platform_runtime, semantic_scope, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission
from .runtime import create_audit_log


router = APIRouter(prefix="/api/v1", tags=["data-plane-v1"])


class DataAssetSnapshot(Base):
    __tablename__ = "data_asset_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", "snapshot_number", name="uq_data_snapshot_project_asset_number"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    snapshot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    storage_format: Mapped[str] = mapped_column(String, nullable=False)
    storage_uri: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    partition_spec: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lineage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class PipelineExecutionPlan(Base):
    __tablename__ = "pipeline_execution_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    graph_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    graph_updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    executor: Mapped[str] = mapped_column(String, nullable=False, index=True)
    plan_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    logical_plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    field_lineage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class SnapshotCreate(BaseModel):
    storage_format: str = Field(default="auto", pattern="^(auto|jsonl|parquet)$")
    partition_spec: Dict[str, Any] = Field(default_factory=dict)
    lineage: Dict[str, Any] = Field(default_factory=dict)


class SnapshotRegister(BaseModel):
    storage_uri: str = Field(min_length=1, max_length=4000)
    storage_format: str = Field(default="parquet", pattern="^parquet$")
    partition_spec: Dict[str, Any] = Field(default_factory=dict)
    lineage: Dict[str, Any] = Field(default_factory=dict)


class PlanCompileRequest(BaseModel):
    executor: str = Field(default="local", pattern="^(local|duckdb)$")


class PlanExecuteRequest(BaseModel):
    mode: str = Field(default="preview", pattern="^(preview|deliver)$")
    execution_strategy: str = Field(default="single", pattern="^(single|auto|partitioned)$")
    max_partitions: int = Field(default=16, ge=2, le=100)
    output_asset_id: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=500)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class SnapshotFilter(BaseModel):
    field: str = Field(min_length=1, max_length=200)
    operator: str = Field(default="eq", pattern="^(eq|ne|gt|gte|lt|lte|contains|in|is_null)$")
    value: Any = None


class SnapshotQueryRequest(BaseModel):
    fields: List[str] = Field(default_factory=list, max_length=200)
    filters: List[SnapshotFilter] = Field(default_factory=list, max_length=100)
    order_by: Optional[str] = Field(default=None, max_length=200)
    descending: bool = False
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0, le=10_000_000)


class SnapshotCachePruneRequest(BaseModel):
    target_bytes: Optional[int] = Field(default=None, ge=0)


class SnapshotStorage(Protocol):
    def put(self, key: str, payload: bytes, content_type: str) -> str: ...
    def get(self, uri: str) -> bytes: ...


class PipelineExecutor(Protocol):
    name: str

    def enqueue(
        self,
        plan: PipelineExecutionPlan,
        graph: pipeline_builder_ops.PipelineBuilderGraph,
        request: PlanExecuteRequest,
        principal: Principal,
        db: Session,
    ) -> Dict[str, Any]: ...


class LocalSnapshotStorage:
    def __init__(self, root: Optional[str] = None):
        configured = root or os.getenv("DATA_SNAPSHOT_ROOT")
        self.root = Path(configured) if configured else Path(tempfile.gettempdir()) / "ontology-platform-snapshots"
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, payload: bytes, content_type: str) -> str:
        safe_parts = [part for part in Path(key).parts if part not in {"", ".", ".."}]
        target = self.root.joinpath(*safe_parts).resolve()
        root = self.root.resolve()
        if root not in target.parents:
            raise ValueError("Snapshot path escapes configured storage root")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return target.as_uri()

    def get(self, uri: str) -> bytes:
        if not uri.startswith("file:"):
            raise ValueError("Local snapshot storage only reads file URIs")
        path = Path(uri.removeprefix("file:///").replace("/", os.sep) if os.name == "nt" else uri.removeprefix("file://"))
        target = path.resolve()
        root = self.root.resolve()
        if root not in target.parents:
            raise ValueError("Snapshot URI is outside configured storage root")
        return target.read_bytes()


class S3CompatibleSnapshotStorage:
    def __init__(self):
        try:
            import boto3  # type: ignore
            from botocore.config import Config  # type: ignore
            from botocore.exceptions import ClientError  # type: ignore
        except ImportError as exc:
            raise RuntimeError("boto3 is required when DATA_SNAPSHOT_BACKEND=s3") from exc
        self.bucket = os.environ["DATA_SNAPSHOT_BUCKET"]
        endpoint = os.getenv("DATA_SNAPSHOT_S3_ENDPOINT")
        addressing_style = os.getenv(
            "DATA_SNAPSHOT_S3_ADDRESSING_STYLE", "path" if endpoint else "auto"
        )
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=os.getenv("DATA_SNAPSHOT_S3_REGION", "us-east-1"),
            config=Config(s3={"addressing_style": addressing_style}),
        )
        if os.getenv("DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET", "false").strip().lower() in {"1", "true", "yes"}:
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except ClientError as exc:
                code = str((exc.response.get("Error") or {}).get("Code") or "")
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
                region = os.getenv("DATA_SNAPSHOT_S3_REGION", "us-east-1")
                kwargs = {"Bucket": self.bucket}
                if region != "us-east-1" and not endpoint:
                    kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
                self.client.create_bucket(**kwargs)

    def put(self, key: str, payload: bytes, content_type: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType=content_type)
        return f"s3://{self.bucket}/{key}"

    def get(self, uri: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("Snapshot URI belongs to another bucket")
        return self.client.get_object(Bucket=self.bucket, Key=uri.removeprefix(prefix))["Body"].read()

    def list_parquet(self, uri: str, maximum: int) -> List[Dict[str, Any]]:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("Snapshot URI belongs to another bucket")
        key = uri.removeprefix(prefix).strip("/")
        if not key:
            raise ValueError("S3 snapshot URI requires an object key or bounded prefix")
        if key.lower().endswith((".parquet", ".pq")):
            response = self.client.head_object(Bucket=self.bucket, Key=key)
            return [{"key": key, "byte_size": int(response["ContentLength"])}]
        object_prefix = key.rstrip("/") + "/"
        scanned = 0
        matches = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=object_prefix):
            for item in page.get("Contents") or []:
                scanned += 1
                if scanned > min(1_000_000, maximum * 10):
                    raise ValueError("S3 snapshot prefix exceeds its bounded object scan limit")
                object_key = str(item.get("Key") or "")
                if object_key.lower().endswith((".parquet", ".pq")):
                    matches.append({"key": object_key, "byte_size": int(item.get("Size") or 0)})
                    if len(matches) > maximum:
                        raise ValueError(f"S3 snapshot prefix exceeds the {maximum}-file manifest limit")
        if not matches:
            raise ValueError("S3 snapshot prefix contains no Parquet objects")
        return sorted(matches, key=lambda item: item["key"])


def _storage() -> SnapshotStorage:
    if os.getenv("DATA_SNAPSHOT_BACKEND", "local").lower() == "s3":
        return S3CompatibleSnapshotStorage()
    return LocalSnapshotStorage()


def _storage_for_uri(uri: str) -> SnapshotStorage:
    if uri.startswith("s3://"):
        return S3CompatibleSnapshotStorage()
    if uri.startswith("file:"):
        return LocalSnapshotStorage()
    raise ValueError("Unsupported snapshot storage URI")


def _infer_schema(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    def type_name(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        return "string"

    names = sorted({str(key) for record in records for key in record})
    fields = []
    for name in names:
        observed = sorted({type_name(record.get(name)) for record in records})
        fields.append({"name": name, "types": observed, "nullable": "null" in observed or any(name not in record for record in records)})
    return {"type": "record", "fields": fields}


def _serialize(records: List[Dict[str, Any]], requested_format: str) -> tuple[bytes, str, str]:
    use_parquet = requested_format == "parquet"
    if requested_format == "auto":
        try:
            import pyarrow  # noqa: F401
            use_parquet = True
        except ImportError:
            use_parquet = False
    if use_parquet:
        try:
            import pyarrow as pa  # type: ignore
            import pyarrow.parquet as parquet  # type: ignore
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="Parquet snapshots require the optional pyarrow dependency") from exc
        sink = io.BytesIO()
        parquet.write_table(pa.Table.from_pylist(records), sink, compression="zstd")
        return sink.getvalue(), "parquet", "application/vnd.apache.parquet"
    payload = b"".join(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8") + b"\n" for record in records)
    return payload, "jsonl", "application/x-ndjson"


def _deserialize(payload: bytes, storage_format: str) -> List[Dict[str, Any]]:
    if storage_format == "parquet":
        try:
            import pyarrow.parquet as parquet  # type: ignore
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="Reading Parquet snapshots requires pyarrow") from exc
        return [dict(row) for row in parquet.read_table(io.BytesIO(payload)).to_pylist()]
    return [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _query_snapshot(payload: bytes, storage_format: str, body: SnapshotQueryRequest) -> Dict[str, Any]:
    try:
        import duckdb  # type: ignore
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as parquet  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Snapshot query requires duckdb and pyarrow") from exc

    table = parquet.read_table(io.BytesIO(payload)) if storage_format == "parquet" else pa.Table.from_pylist(_deserialize(payload, storage_format))
    available = set(table.column_names)
    requested = body.fields or list(table.column_names)
    invalid = sorted(set(requested) - available)
    if body.order_by and body.order_by not in available:
        invalid.append(body.order_by)
    invalid.extend(sorted({item.field for item in body.filters if item.field not in available}))
    if invalid:
        raise HTTPException(status_code=422, detail={"message": "Snapshot query references unknown fields", "fields": sorted(set(invalid))})

    predicates: List[str] = []
    parameters: List[Any] = []
    sql_operators = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    for item in body.filters:
        field = _quoted_identifier(item.field)
        if item.operator in sql_operators:
            predicates.append(f"{field} {sql_operators[item.operator]} ?")
            parameters.append(item.value)
        elif item.operator == "contains":
            predicates.append(f"CAST({field} AS VARCHAR) ILIKE ?")
            parameters.append(f"%{item.value}%")
        elif item.operator == "is_null":
            predicates.append(f"{field} IS {'NOT ' if item.value is False else ''}NULL")
        elif item.operator == "in":
            values = item.value if isinstance(item.value, list) else [item.value]
            if not values:
                predicates.append("FALSE")
            else:
                predicates.append(f"{field} IN ({', '.join('?' for _ in values)})")
                parameters.extend(values)

    projection = ", ".join(_quoted_identifier(field) for field in requested)
    where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
    order = f" ORDER BY {_quoted_identifier(body.order_by)} {'DESC' if body.descending else 'ASC'}" if body.order_by else ""
    sql = f"SELECT {projection} FROM snapshot_rows{where}{order} LIMIT ? OFFSET ?"
    parameters.extend([body.limit, body.offset])
    started = time.perf_counter()
    connection = duckdb.connect(database=":memory:")
    try:
        connection.register("snapshot_rows", table)
        result = connection.execute(sql, parameters)
        names = [column[0] for column in result.description]
        rows = [dict(zip(names, values)) for values in result.fetchall()]
    except (duckdb.BinderException, duckdb.ConversionException, duckdb.InvalidInputException) as exc:
        raise HTTPException(status_code=422, detail=f"DuckDB execution rejected plan: {exc}") from exc
    finally:
        connection.close()
    return {
        "rows": rows,
        "count": len(rows),
        "schema": {"fields": [{"name": field, "type": str(table.schema.field(field).type)} for field in requested]},
        "execution": {"engine": "duckdb", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "limit": body.limit, "offset": body.offset},
    }


def _query_local_parquet_snapshot(row: DataAssetSnapshot, body: SnapshotQueryRequest) -> Dict[str, Any]:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Snapshot query requires duckdb") from exc
    relation = _duckdb_parquet_relation(row)
    connection = duckdb.connect(database=":memory:")
    started = time.perf_counter()
    try:
        description = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
        available_types = {str(item[0]): str(item[1]) for item in description}
        available = set(available_types)
        requested = body.fields or list(available_types)
        invalid = sorted(set(requested) - available)
        if body.order_by and body.order_by not in available:
            invalid.append(body.order_by)
        invalid.extend(sorted({item.field for item in body.filters if item.field not in available}))
        if invalid:
            raise HTTPException(status_code=422, detail={
                "message": "Snapshot query references unknown fields", "fields": sorted(set(invalid)),
            })
        predicates: List[str] = []
        parameters: List[Any] = []
        sql_operators = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
        for item in body.filters:
            field = _quoted_identifier(item.field)
            if item.operator in sql_operators:
                predicates.append(f"{field} {sql_operators[item.operator]} ?")
                parameters.append(item.value)
            elif item.operator == "contains":
                predicates.append(f"CAST({field} AS VARCHAR) ILIKE ?")
                parameters.append(f"%{item.value}%")
            elif item.operator == "is_null":
                predicates.append(f"{field} IS {'NOT ' if item.value is False else ''}NULL")
            elif item.operator == "in":
                values = item.value if isinstance(item.value, list) else [item.value]
                predicates.append("FALSE" if not values else f"{field} IN ({', '.join('?' for _ in values)})")
                parameters.extend(values)
        projection = ", ".join(_quoted_identifier(field) for field in requested)
        where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
        order = f" ORDER BY {_quoted_identifier(body.order_by)} {'DESC' if body.descending else 'ASC'}" if body.order_by else ""
        parameters.extend([body.limit, body.offset])
        result = connection.execute(
            f"SELECT {projection} FROM {relation}{where}{order} LIMIT ? OFFSET ?", parameters,
        )
        names = [column[0] for column in result.description]
        rows = [dict(zip(names, values)) for values in result.fetchall()]
    except HTTPException:
        raise
    except (duckdb.BinderException, duckdb.ConversionException, duckdb.InvalidInputException) as exc:
        raise HTTPException(status_code=422, detail=f"DuckDB execution rejected snapshot query: {exc}") from exc
    finally:
        connection.close()
    return {
        "rows": rows, "count": len(rows),
        "schema": {"fields": [{"name": field, "type": available_types[field]} for field in requested]},
        "execution": {
            "engine": "duckdb-parquet", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "limit": body.limit, "offset": body.offset,
            "file_count": len(_snapshot_local_paths(row)),
        },
    }


class LocalDurablePipelineExecutor:
    def __init__(self, name: str):
        self.name = name

    def enqueue(
        self,
        plan: PipelineExecutionPlan,
        graph: pipeline_builder_ops.PipelineBuilderGraph,
        request: PlanExecuteRequest,
        principal: Principal,
        db: Session,
    ) -> Dict[str, Any]:
        if self.name == "duckdb":
            if request.execution_strategy == "partitioned" and request.mode != "deliver":
                raise HTTPException(
                    status_code=422,
                    detail="Partitioned execution is supported only for durable delivery",
                )
            distribution = None
            if request.execution_strategy in {"auto", "partitioned"} and request.mode == "deliver":
                distribution = _partition_execution_spec(
                    db, plan, graph, request.max_partitions, request.parameters,
                )
                if distribution["eligible"]:
                    return _enqueue_partitioned_duckdb_execution(
                        db, plan, graph, request, principal, distribution,
                    )
                if request.execution_strategy == "partitioned":
                    raise HTTPException(status_code=422, detail={
                        "message": "Pipeline is not safe for independent partition execution",
                        "blocking_operations": distribution["blocking_operations"],
                        "reasons": distribution["reasons"],
                    })
            job_type = "pipeline.duckdb.deliver" if request.mode == "deliver" else "pipeline.duckdb.preview"
            result = platform_runtime.create_job(platform_runtime.JobCreate(
                project_id=plan.project_id,
                job_type=job_type,
                subject_type="pipeline_execution_plan",
                subject_id=plan.id,
                payload={
                    "plan_id": plan.id,
                    "graph_id": graph.id,
                    "mode": request.mode,
                    "output_asset_id": request.output_asset_id,
                    "limit": request.limit,
                    "parameters": request.parameters,
                    "execution_strategy": "single",
                    **({"strategy_fallback": distribution} if request.execution_strategy == "auto" and distribution is not None else {}),
                },
                priority=50,
                max_attempts=3,
                timeout_seconds=3600,
                idempotency_key=request.idempotency_key,
            ), principal, db)
            result["execution_strategy"] = "single"
            if request.execution_strategy == "auto" and distribution is not None:
                result["strategy_fallback"] = distribution
            return result
        if request.mode == "deliver":
            return pipeline_builder_ops.enqueue_graph_delivery(
                graph.id,
                pipeline_builder_ops.PipelineAsyncDeliverRequest(
                    output_asset_id=request.output_asset_id,
                    parameters=request.parameters,
                    idempotency_key=request.idempotency_key,
                ),
                principal,
                db,
            )
        return pipeline_builder_ops.enqueue_graph_preview(
            graph.id,
            pipeline_builder_ops.PipelineAsyncPreviewRequest(
                limit=request.limit,
                parameters=request.parameters,
                idempotency_key=request.idempotency_key,
            ),
            principal,
            db,
        )


def _executor(name: str) -> PipelineExecutor:
    if name not in {"local", "duckdb"}:
        raise HTTPException(status_code=422, detail=f"Unsupported pipeline executor '{name}'")
    return LocalDurablePipelineExecutor(name)


_DUCKDB_SNAPSHOT_OPERATIONS = {
    "input_dataset", "dataset_input", "filter", "project", "select", "rename",
    "cast", "derive", "fill_nulls", "normalize", "deduplicate", "aggregate",
    "join", "union", "sort", "limit", "unique_id", "pivot", "unpivot",
    "window", "validate", "derive_geo_point", "derive_mgrs", "spatial_filter", "spatial_join",
    "dataset_output", "output_dataset",
}

_PARTITION_SAFE_DUCKDB_OPERATIONS = {
    "input_dataset", "dataset_input", "filter", "project", "select", "rename",
    "cast", "derive", "fill_nulls", "normalize", "validate",
    "derive_geo_point", "derive_mgrs", "spatial_filter",
    "dataset_output", "output_dataset",
}


def _partition_execution_spec(
    db: Session,
    plan: PipelineExecutionPlan,
    graph: pipeline_builder_ops.PipelineBuilderGraph,
    max_partitions: int,
    parameters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    parameters = parameters or {}
    ordered = pipeline_builder_ops._topological_nodes(graph)
    operations = [pipeline_builder_ops._node_type(node) for _node_id, node in ordered]
    blocking = sorted(set(operations) - _PARTITION_SAFE_DUCKDB_OPERATIONS)
    input_nodes = [
        (node_id, node) for node_id, node in ordered
        if pipeline_builder_ops._node_type(node) in {"input_dataset", "dataset_input"}
    ]
    reasons: List[str] = []
    source_snapshot = None
    files: List[str] = []
    if len(input_nodes) != 1:
        reasons.append("Partition execution requires exactly one dataset input")
    else:
        _node_id, input_node = input_nodes[0]
        config = {
            **pipeline_builder_ops._config(input_node),
            **(parameters.get(_node_id, {}) if isinstance(parameters.get(_node_id), dict) else {}),
        }
        snapshot_id = str(config.get("snapshot_id") or "")
        asset_id = str(config.get("asset_id") or config.get("dataset_id") or "")
        source_snapshot = db.get(DataAssetSnapshot, snapshot_id) if snapshot_id else None
        if source_snapshot is None and asset_id:
            source_snapshot = db.query(DataAssetSnapshot).filter(
                DataAssetSnapshot.project_id == plan.project_id,
                DataAssetSnapshot.asset_id == asset_id,
                DataAssetSnapshot.status == "AVAILABLE",
            ).order_by(DataAssetSnapshot.snapshot_number.desc()).first()
        if not source_snapshot or source_snapshot.project_id != plan.project_id:
            reasons.append("The input has no project-owned immutable snapshot")
        else:
            manifest = (source_snapshot.partition_spec or {}).get("_manifest") or {}
            files = list(manifest.get("files") or []) if isinstance(manifest, dict) else []
            if len(files) < 2:
                reasons.append("The input snapshot must contain at least two immutable files")
    if blocking:
        reasons.append("The plan contains operations that require global or multi-input state")
    if ordered:
        final_node_id, final_node = ordered[-1]
        final_config = {
            **pipeline_builder_ops._config(final_node),
            **(parameters.get(final_node_id, {}) if isinstance(parameters.get(final_node_id), dict) else {}),
            **(parameters.get("__output__", {}) if isinstance(parameters.get("__output__"), dict) else {}),
        }
    else:
        final_config = {}
    if _output_partition_fields(final_config):
        reasons.append("Field-partitioned outputs require a global final repartition step")
    shard_count = min(max(2, int(max_partitions)), len(files)) if files else 0
    groups = [files[index::shard_count] for index in range(shard_count)] if shard_count else []
    eligible = not reasons and not blocking and bool(source_snapshot) and len(groups) >= 2
    return {
        "eligible": eligible,
        "strategy": "partitioned" if eligible else "single",
        "source_snapshot_id": source_snapshot.id if source_snapshot else None,
        "source_file_count": len(files),
        "partition_count": len(groups),
        "partitions": groups if eligible else [],
        "blocking_operations": blocking,
        "reasons": reasons,
    }


def _partition_idempotency_key(base: Optional[str], plan_id: str, group_id: str, index: int) -> Optional[str]:
    if not base:
        return None
    digest = hashlib.sha256(f"{base}:{plan_id}:{group_id}:{index}".encode("utf-8")).hexdigest()
    return f"partition-{digest}"


def _enqueue_partitioned_duckdb_execution(
    db: Session,
    plan: PipelineExecutionPlan,
    graph: pipeline_builder_ops.PipelineBuilderGraph,
    request: PlanExecuteRequest,
    principal: Principal,
    distribution: Dict[str, Any],
) -> Dict[str, Any]:
    seed = request.idempotency_key or uuid.uuid4().hex
    group_id = hashlib.sha256(f"{plan.project_id}:{plan.id}:{seed}".encode("utf-8")).hexdigest()[:32]
    child_jobs = []
    for index, source_files in enumerate(distribution["partitions"]):
        child_jobs.append(platform_runtime.create_job(platform_runtime.JobCreate(
            project_id=plan.project_id,
            job_type="pipeline.duckdb.partition",
            subject_type="pipeline_execution_plan",
            subject_id=plan.id,
            payload={
                "plan_id": plan.id,
                "graph_id": graph.id,
                "execution_group_id": group_id,
                "partition_index": index,
                "partition_count": distribution["partition_count"],
                "source_snapshot_id": distribution["source_snapshot_id"],
                "source_files": source_files,
                "parameters": request.parameters,
            },
            priority=50,
            max_attempts=3,
            timeout_seconds=3600,
            idempotency_key=_partition_idempotency_key(
                request.idempotency_key, plan.id, group_id, index,
            ),
        ), principal, db))
    child_ids = [str(job["id"]) for job in child_jobs]
    partition_execution = {
        "group_id": group_id,
        "partition_count": len(child_jobs),
        "partition_job_ids": child_ids,
        "source_snapshot_id": distribution["source_snapshot_id"],
        "source_file_count": distribution["source_file_count"],
    }
    finalizer_key = None
    if request.idempotency_key:
        finalizer_key = "finalize-" + hashlib.sha256(
            f"{request.idempotency_key}:{plan.id}:{group_id}".encode("utf-8")
        ).hexdigest()
    finalizer = platform_runtime.create_job(platform_runtime.JobCreate(
        project_id=plan.project_id,
        job_type="pipeline.duckdb.finalize",
        subject_type="pipeline_execution_plan",
        subject_id=plan.id,
        payload={
            "plan_id": plan.id,
            "graph_id": graph.id,
            "execution_group_id": group_id,
            "partition_job_ids": child_ids,
            "source_snapshot_id": distribution["source_snapshot_id"],
            "output_asset_id": request.output_asset_id,
            "parameters": request.parameters,
            "execution_strategy": "partitioned",
            "partition_execution": partition_execution,
        },
        priority=50,
        max_attempts=3,
        timeout_seconds=3600,
        idempotency_key=finalizer_key,
        depends_on=child_ids,
    ), principal, db)
    finalizer["execution_strategy"] = "partitioned"
    finalizer["partition_execution"] = partition_execution
    return finalizer


def _file_uri_path(storage_uri: str) -> Path:
    if not storage_uri.startswith("file:"):
        raise HTTPException(status_code=422, detail="Direct DuckDB execution currently requires local snapshot storage")
    uri = storage_uri
    return Path(uri.removeprefix("file:///").replace("/", os.sep) if os.name == "nt" else uri.removeprefix("file://")).resolve()


def _local_snapshot_target(storage_uri: str) -> Path:
    path = _file_uri_path(storage_uri)
    root = LocalSnapshotStorage().root.resolve()
    if root != path and root not in path.parents:
        raise HTTPException(status_code=422, detail="Snapshot path is outside DATA_SNAPSHOT_ROOT")
    if not path.exists():
        raise HTTPException(status_code=422, detail="Snapshot path does not exist")
    return path


def _discover_parquet_files(storage_uri: str) -> tuple[Path, List[Path]]:
    target = _local_snapshot_target(storage_uri)
    maximum = max(1, min(int(os.getenv("DATA_SNAPSHOT_MAX_FILES", "10000")), 100_000))
    if target.is_file():
        if target.suffix.lower() not in {".parquet", ".pq"}:
            raise HTTPException(status_code=422, detail="Registered snapshot file must use a Parquet extension")
        return target.parent, [target]
    if not target.is_dir():
        raise HTTPException(status_code=422, detail="Snapshot URI must identify a Parquet file or directory")
    files = sorted(
        (path.resolve() for path in target.rglob("*") if path.is_file() and path.suffix.lower() in {".parquet", ".pq"}),
        key=lambda path: path.relative_to(target).as_posix(),
    )
    if not files:
        raise HTTPException(status_code=422, detail="Registered snapshot directory contains no Parquet files")
    if len(files) > maximum:
        raise HTTPException(status_code=422, detail=f"Registered snapshot exceeds the {maximum}-file manifest limit")
    root = LocalSnapshotStorage().root.resolve()
    if any(root not in path.parents for path in files):
        raise HTTPException(status_code=422, detail="Snapshot manifest contains a file outside DATA_SNAPSHOT_ROOT")
    return target, files


def _s3_registration_metadata(
    storage_uri: str, partition_spec: Dict[str, Any],
) -> tuple[Dict[str, Any], str, bool, int]:
    maximum = max(1, min(int(os.getenv("DATA_SNAPSHOT_MAX_FILES", "10000")), 100_000))
    storage = _storage_for_uri(storage_uri)
    if not hasattr(storage, "list_parquet"):
        raise HTTPException(status_code=503, detail="Configured S3 adapter does not support snapshot discovery")
    try:
        objects = storage.list_parquet(storage_uri, maximum)  # type: ignore[attr-defined]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"S3 snapshot discovery failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"S3 snapshot discovery unavailable: {exc}") from exc
    exact_file = storage_uri.rstrip("/").lower().endswith((".parquet", ".pq"))
    partitioned = not exact_file
    normalized_uri = storage_uri.rstrip("/")
    bucket = str(getattr(storage, "bucket", os.environ.get("DATA_SNAPSHOT_BUCKET", "")))
    bucket_prefix = f"s3://{bucket}/"
    if not normalized_uri.startswith(bucket_prefix):
        raise HTTPException(status_code=422, detail="S3 snapshot URI belongs to another bucket")
    configured_key = normalized_uri.removeprefix(bucket_prefix)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        base = Path(temporary)
        files = []
        for item in objects:
            key = str(item["key"])
            object_uri = f"{bucket_prefix}{key}"
            relative = Path(key).name
            if partitioned:
                configured_prefix = configured_key.rstrip("/") + "/"
                if not key.startswith(configured_prefix):
                    raise HTTPException(status_code=422, detail="S3 snapshot listing returned an object outside its prefix")
                relative = key.removeprefix(configured_prefix)
            if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise HTTPException(status_code=422, detail="S3 snapshot contains an invalid object key")
            try:
                payload = storage.get(object_uri)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"S3 snapshot download failed for '{relative}': {exc}") from exc
            if int(item.get("byte_size", -1)) != len(payload):
                raise HTTPException(status_code=409, detail=f"S3 object size changed during registration: {relative}")
            target = (base / relative).resolve()
            if base.resolve() not in target.parents:
                raise HTTPException(status_code=422, detail="S3 snapshot object escaped the registration workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            files.append(target)
        metadata = _parquet_manifest_metadata(base, files, partitioned=partitioned)
        if partitioned and bool(partition_spec.get("hive_partitioning")):
            try:
                import duckdb  # type: ignore
                paths = ", ".join(_duckdb_literal(path.as_posix()) for path in files)
                connection = duckdb.connect(database=":memory:")
                try:
                    description = connection.execute(
                        f"DESCRIBE SELECT * FROM read_parquet([{paths}], union_by_name=true, hive_partitioning=true)"
                    ).fetchall()
                finally:
                    connection.close()
                metadata["schema"] = {"fields": [
                    {"name": row[0], "type": row[1], "nullable": str(row[2]).upper() != "NO"}
                    for row in description
                ]}
            except ImportError as exc:
                raise HTTPException(status_code=503, detail="Hive-partitioned S3 registration requires DuckDB") from exc
    return metadata, normalized_uri, partitioned, len(objects)


def _snapshot_local_paths(row: DataAssetSnapshot, requested_files: Optional[List[str]] = None) -> List[Path]:
    if row.storage_uri.startswith("s3://"):
        return _cache_s3_snapshot(row, requested_files)
    target = _local_snapshot_target(row.storage_uri)
    manifest = (row.partition_spec or {}).get("_manifest") or {}
    relative_files = manifest.get("files") if isinstance(manifest, dict) else None
    entries = {
        entry.get("path"): entry
        for entry in (manifest.get("entries") or [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    } if isinstance(manifest, dict) else {}
    if not relative_files:
        if requested_files is not None and requested_files != ["snapshot.parquet"]:
            raise HTTPException(status_code=422, detail="Requested snapshot files are not in the immutable manifest")
        if not target.is_file():
            raise HTTPException(status_code=422, detail="Partitioned snapshot is missing its immutable file manifest")
        return [target]
    if not target.is_dir():
        raise HTTPException(status_code=422, detail="Partitioned snapshot storage URI is not a directory")
    requested = list(requested_files) if requested_files is not None else list(relative_files)
    if not requested or any(relative not in relative_files for relative in requested):
        raise HTTPException(status_code=422, detail="Requested snapshot files are not in the immutable manifest")
    files = []
    for relative in requested:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise HTTPException(status_code=422, detail="Partitioned snapshot manifest contains an invalid relative path")
        path = (target / Path(relative)).resolve()
        if target not in path.parents or not path.is_file():
            raise HTTPException(status_code=422, detail="Partitioned snapshot manifest file is missing or outside its directory")
        entry = entries.get(relative)
        if entry and int(entry.get("byte_size", -1)) != path.stat().st_size:
            raise HTTPException(status_code=409, detail=f"Partitioned snapshot file size changed after registration: {relative}")
        if entry and os.getenv("DATA_SNAPSHOT_VERIFY_HASH", "").strip().lower() in {"1", "true", "yes"}:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != entry.get("sha256"):
                raise HTTPException(status_code=409, detail=f"Partitioned snapshot content changed after registration: {relative}")
        files.append(path)
    return files


def _snapshot_cache_root() -> Path:
    configured = os.getenv("DATA_SNAPSHOT_CACHE_ROOT")
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / "ontology-platform-snapshot-cache"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


_CACHE_METRICS_LOCK = threading.Lock()
_CACHE_FILE_LOCKS_LOCK = threading.Lock()
_CACHE_FILE_LOCKS: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
_CACHE_METRICS = {
    "hits": 0, "misses": 0, "downloaded_bytes": 0,
    "integrity_failures": 0, "evictions": 0, "evicted_bytes": 0,
}


def _cache_metric(name: str, amount: int = 1) -> None:
    with _CACHE_METRICS_LOCK:
        _CACHE_METRICS[name] = int(_CACHE_METRICS.get(name, 0)) + amount


def _cache_file_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _CACHE_FILE_LOCKS_LOCK:
        return _CACHE_FILE_LOCKS.setdefault(key, threading.Lock())


def _snapshot_cache_limit() -> int:
    try:
        configured = int(os.getenv("DATA_SNAPSHOT_CACHE_MAX_BYTES", str(20 * 1024 * 1024 * 1024)))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="DATA_SNAPSHOT_CACHE_MAX_BYTES must be an integer") from exc
    if configured < 1:
        raise HTTPException(status_code=500, detail="DATA_SNAPSHOT_CACHE_MAX_BYTES must be positive")
    return configured


def _cache_inventory() -> List[Dict[str, Any]]:
    root = _snapshot_cache_root()
    entries = []
    for candidate in root.glob("*/*"):
        if not candidate.is_dir():
            continue
        files = [path for path in candidate.rglob("*") if path.is_file() and path.name != ".lease"]
        lease = candidate / ".lease"
        entries.append({
            "path": candidate,
            "byte_size": sum(path.stat().st_size for path in files),
            "file_count": len(files),
            "last_accessed": lease.stat().st_mtime if lease.exists() else candidate.stat().st_mtime,
        })
    return entries


def _prune_snapshot_cache(
    *, target_bytes: Optional[int] = None, required_bytes: int = 0, protected: Optional[Path] = None,
) -> Dict[str, Any]:
    limit = _snapshot_cache_limit()
    desired = min(limit, target_bytes if target_bytes is not None else max(0, limit - required_bytes))
    inventory = _cache_inventory()
    total = sum(int(entry["byte_size"]) for entry in inventory)
    lease_seconds = max(0, int(os.getenv("DATA_SNAPSHOT_CACHE_LEASE_SECONDS", "3600")))
    now = time.time()
    evictions = 0
    evicted_bytes = 0
    protected_entries = 0
    protected_resolved = protected.resolve() if protected else None
    for entry in sorted(inventory, key=lambda item: float(item["last_accessed"])):
        if total <= desired:
            break
        path = entry["path"].resolve()
        if protected_resolved and path == protected_resolved:
            protected_entries += 1
            continue
        if now - float(entry["last_accessed"]) < lease_seconds:
            protected_entries += 1
            continue
        size = int(entry["byte_size"])
        shutil.rmtree(path, ignore_errors=False)
        total -= size
        evictions += 1
        evicted_bytes += size
    if total + required_bytes > limit:
        raise HTTPException(
            status_code=507,
            detail={
                "message": "Snapshot cache quota cannot accommodate the requested object",
                "cache_bytes": total, "required_bytes": required_bytes, "limit_bytes": limit,
            },
        )
    if evictions:
        _cache_metric("evictions", evictions)
        _cache_metric("evicted_bytes", evicted_bytes)
    return {
        "cache_bytes": total, "limit_bytes": limit,
        "entries": max(0, len(inventory) - evictions),
        "evictions": evictions, "evicted_bytes": evicted_bytes,
        "target_bytes": desired, "target_satisfied": total <= desired,
        "protected_entries": protected_entries,
    }


def _verified_cached_payload(payload: bytes, entry: Dict[str, Any], relative: str) -> None:
    expected_size = entry.get("byte_size")
    if expected_size is not None and int(expected_size) != len(payload):
        _cache_metric("integrity_failures")
        raise HTTPException(status_code=409, detail=f"S3 snapshot file size differs from its manifest: {relative}")
    expected_hash = entry.get("sha256")
    if expected_hash and hashlib.sha256(payload).hexdigest() != expected_hash:
        _cache_metric("integrity_failures")
        raise HTTPException(status_code=409, detail=f"S3 snapshot content differs from its manifest: {relative}")


def _ensure_cached_s3_file(
    row: DataAssetSnapshot,
    storage: SnapshotStorage,
    cache_dir: Path,
    relative: str,
    entry: Dict[str, Any],
    partitioned: bool,
) -> Path:
    relative_path = Path(relative)
    if not relative or relative_path.is_absolute() or ".." in relative_path.parts:
        raise HTTPException(status_code=422, detail="S3 snapshot cache target escaped its snapshot directory")
    target = cache_dir / relative_path
    uri = row.storage_uri.rstrip("/") + (f"/{relative}" if partitioned else "")
    with _cache_file_lock(target):
        needs_download = not target.is_file()
        if target.is_file() and entry:
            needs_download = int(entry.get("byte_size", -1)) != target.stat().st_size
            if not needs_download and entry.get("sha256"):
                needs_download = hashlib.sha256(target.read_bytes()).hexdigest() != entry.get("sha256")
        if not needs_download:
            _cache_metric("hits")
            return target
        try:
            payload = storage.get(uri)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"S3 snapshot download failed for '{relative}': {exc}") from exc
        if partitioned:
            _verified_cached_payload(payload, entry, relative)
        elif hashlib.sha256(payload).hexdigest() != row.content_hash:
            _cache_metric("integrity_failures")
            raise HTTPException(status_code=409, detail="S3 snapshot content differs from its registered hash")
        _prune_snapshot_cache(required_bytes=len(payload), protected=cache_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
        _cache_metric("misses")
        _cache_metric("downloaded_bytes", len(payload))
        return target


def _cache_s3_snapshot(row: DataAssetSnapshot, requested_files: Optional[List[str]] = None) -> List[Path]:
    manifest = (row.partition_spec or {}).get("_manifest") or {}
    relative_files = manifest.get("files") if isinstance(manifest, dict) else None
    entries = {
        entry.get("path"): entry
        for entry in (manifest.get("entries") or [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    } if isinstance(manifest, dict) else {}
    available = list(relative_files or ["snapshot.parquet"])
    requested = list(requested_files) if requested_files is not None else available
    if not requested or any(relative not in available for relative in requested):
        raise HTTPException(status_code=422, detail="Requested S3 snapshot files are not in the immutable manifest")
    cache_root = _snapshot_cache_root()
    cache_key = hashlib.sha256(f"{row.project_id}:{row.asset_id}:{row.id}".encode("utf-8")).hexdigest()
    cache_dir = (cache_root / cache_key[:2] / cache_key).resolve()
    if cache_root not in cache_dir.parents:
        raise HTTPException(status_code=500, detail="S3 snapshot cache path escaped its configured root")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / ".lease").touch()
    storage = _storage_for_uri(row.storage_uri)
    paths: List[Path] = []
    for relative in requested:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise HTTPException(status_code=422, detail="S3 snapshot manifest contains an invalid relative path")
        entry = entries.get(relative) or {}
        paths.append(_ensure_cached_s3_file(
            row, storage, cache_dir, relative, entry, bool(relative_files),
        ))
    (cache_dir / ".lease").touch()
    return paths


def _duckdb_parquet_relation(row: DataAssetSnapshot, requested_files: Optional[List[str]] = None) -> str:
    if row.storage_format != "parquet":
        raise HTTPException(status_code=422, detail="DuckDB pipeline execution requires a Parquet input snapshot")
    files = _snapshot_local_paths(row, requested_files)
    paths = ", ".join(_duckdb_literal(path.as_posix()) for path in files)
    hive_partitioning = bool((row.partition_spec or {}).get("hive_partitioning"))
    hive_option = ", hive_partitioning = true" if hive_partitioning else ""
    return f"read_parquet([{paths}], union_by_name = true{hive_option})"


def _parquet_manifest_metadata(base: Path, files: List[Path], *, partitioned: bool) -> Dict[str, Any]:
    try:
        import pyarrow.parquet as parquet  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Parquet registration requires pyarrow") from exc
    # Both sides resolved before any comparison. On macOS `/var` is a symlink to
    # `/private/var`, so a caller holding an unresolved base while the file list
    # came back resolved made `relative_to` raise ValueError -- and the bare
    # `except Exception` below reported that as "Registered snapshot is not valid
    # Parquet", naming a file that was perfectly valid. Every host whose temporary
    # directory traverses a symlink hits it, which is most of them.
    base = base.resolve()
    files = [path.resolve() for path in files]

    arrow_schema = None
    row_count = 0
    byte_size = 0
    digest = hashlib.sha256()
    if partitioned:
        digest.update(b"ontology-parquet-manifest-v1\0")
    relative_files = []
    entries = []
    try:
        for path in files:
            if not path.is_relative_to(base):
                # Said plainly, because the generic handler below would call this
                # a Parquet defect and send the reader to the wrong file.
                raise HTTPException(
                    status_code=422,
                    detail=(f"Snapshot file '{path}' is outside the snapshot directory "
                            f"'{base}'"),
                )
            parquet_file = parquet.ParquetFile(path)
            candidate_schema = parquet_file.schema_arrow
            if arrow_schema is None:
                arrow_schema = candidate_schema
            elif not arrow_schema.equals(candidate_schema, check_metadata=False):
                raise HTTPException(
                    status_code=422,
                    detail=f"Partitioned snapshot schema mismatch in '{path.relative_to(base).as_posix()}'",
                )
            relative = path.relative_to(base).as_posix()
            relative_files.append(relative)
            if partitioned:
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
            file_digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    file_digest.update(chunk)
            file_rows = int(parquet_file.metadata.num_rows)
            file_bytes = path.stat().st_size
            row_count += file_rows
            byte_size += file_bytes
            entries.append({
                "path": relative, "byte_size": file_bytes,
                "row_count": file_rows, "sha256": file_digest.hexdigest(),
            })
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Registered snapshot is not valid Parquet: {exc}") from exc
    if arrow_schema is None:
        raise HTTPException(status_code=422, detail="Registered snapshot has no Parquet schema")
    return {
        "content_hash": digest.hexdigest(),
        "row_count": row_count,
        "byte_size": byte_size,
        "schema": {"fields": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in arrow_schema
        ]},
        "manifest": {
            "version": 1,
            "file_count": len(files),
            "files": relative_files,
            "entries": entries,
        },
    }


def _duckdb_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _duckdb_type(value: str) -> str:
    normalized = str(value).lower()
    mapping = {
        "string": "VARCHAR", "str": "VARCHAR", "integer": "BIGINT", "int": "BIGINT",
        "number": "DOUBLE", "float": "DOUBLE", "double": "DOUBLE",
        "boolean": "BOOLEAN", "bool": "BOOLEAN", "timestamp": "TIMESTAMP",
    }
    if normalized not in mapping:
        raise HTTPException(status_code=422, detail=f"Unsupported DuckDB cast type '{value}'")
    return mapping[normalized]


def _output_partition_fields(config: Dict[str, Any]) -> List[str]:
    raw = config.get("partition_by") or config.get("partition_fields") or []
    fields = [raw] if isinstance(raw, str) else raw
    if not isinstance(fields, list):
        raise HTTPException(status_code=422, detail="Dataset output partition_by must be a field list")
    normalized = [str(field).strip() for field in fields]
    if any(not field for field in normalized):
        raise HTTPException(status_code=422, detail="Dataset output partition fields cannot be empty")
    if len(normalized) > 8:
        raise HTTPException(status_code=422, detail="Dataset output supports at most 8 partition fields")
    if len(set(normalized)) != len(normalized):
        raise HTTPException(status_code=422, detail="Dataset output partition fields must be unique")
    return normalized


def _lock_snapshot_publication(
    db: Session,
    *,
    project_id: str,
    asset_id: str,
    display_name: str,
    execution_idempotency_key: Optional[str],
    execution_fence_job_id: Optional[str],
    execution_lease_token: Optional[str],
) -> tuple[models.DataAsset, Optional[DataAssetSnapshot]]:
    """Serialize one output namespace and fence stale workers before publish.

    DuckDB computation happens outside this critical section. PostgreSQL uses a
    transaction advisory lock because an output asset may not exist yet; the
    process-local lock at the caller supplies equivalent serialization for the
    single-process SQLite development runtime.
    """
    if db.get_bind().dialect.name == "postgresql":
        lock_key = int.from_bytes(
            hashlib.sha256(f"snapshot-publish:{project_id}:{asset_id}".encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    # A replacement worker may have completed while this worker was computing.
    # Returning that immutable result is safe even when the caller's lease is
    # stale because this branch performs no publication or metadata mutation.
    prior = None
    if execution_idempotency_key:
        prior = db.query(DataAssetSnapshot).filter(
            DataAssetSnapshot.project_id == project_id,
            DataAssetSnapshot.asset_id == asset_id,
        ).order_by(DataAssetSnapshot.snapshot_number.desc()).limit(100).all()
        prior = next((
            row for row in prior
            if str((row.lineage or {}).get("execution_job_id") or "") == execution_idempotency_key
        ), None)

    asset_query = db.query(models.DataAsset).filter(
        models.DataAsset.id == asset_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        asset_query = asset_query.with_for_update()
    asset = asset_query.populate_existing().first()
    if asset and asset.project_id != project_id:
        raise HTTPException(status_code=409, detail="Output asset belongs to another project")
    if prior:
        if asset is None:
            raise HTTPException(status_code=409, detail="Committed snapshot references a missing output asset")
        return asset, prior

    if execution_fence_job_id:
        if not execution_lease_token:
            raise HTTPException(status_code=409, detail="Snapshot delivery requires the current worker lease token")
        job_query = db.query(platform_runtime.PlatformJob).filter(
            platform_runtime.PlatformJob.id == execution_fence_job_id,
        )
        lease_query = db.query(platform_runtime.PlatformJobLease).filter(
            platform_runtime.PlatformJobLease.job_id == execution_fence_job_id,
        )
        if db.get_bind().dialect.name == "postgresql":
            job_query = job_query.with_for_update()
            lease_query = lease_query.with_for_update()
        job = job_query.populate_existing().first()
        lease = lease_query.populate_existing().first()
        if (
            not job
            or job.status != "RUNNING"
            or not lease
            or lease.token != execution_lease_token
            or lease.expires_at <= int(time.time())
        ):
            raise HTTPException(
                status_code=409,
                detail="Snapshot delivery was cancelled or lost its worker lease before publish",
            )

    if asset is None:
        asset = models.DataAsset(
            id=asset_id,
            project_id=project_id,
            display_name=display_name,
            description="DuckDB snapshot pipeline output",
            kind="dataset",
            asset_schema={},
            records=[],
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        db.add(asset)
        db.flush()
    return asset, None


def _remove_internal_output_path(path: Path, root: Path) -> None:
    resolved = path.resolve()
    if root != resolved and root not in resolved.parents:
        raise HTTPException(status_code=500, detail="Refusing to replace output outside DATA_SNAPSHOT_ROOT")
    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def _publish_output_snapshot(
    target: Path,
    *,
    project_id: str,
    asset_id: str,
    metadata: Dict[str, Any],
    partitioned: bool,
) -> str:
    if os.getenv("DATA_SNAPSHOT_BACKEND", "local").strip().lower() != "s3":
        return target.as_uri()
    storage = _storage()
    key = f"{project_id}/{asset_id}/{target.name}"
    if not partitioned:
        return storage.put(key, target.read_bytes(), "application/vnd.apache.parquet")
    base_uri = ""
    for entry in metadata["manifest"]["entries"]:
        relative = str(entry["path"])
        uri = storage.put(
            f"{key}/{relative}",
            (target / Path(relative)).read_bytes(),
            "application/vnd.apache.parquet",
        )
        base_uri = uri[:-(len(relative) + 1)]
    if not base_uri:
        raise HTTPException(status_code=503, detail="Partitioned S3 output did not publish any objects")
    return base_uri


def _filter_specs(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    filters = config.get("filters")
    if isinstance(filters, dict):
        return [
            {
                "field": field,
                "op": next(iter(expression.keys())) if isinstance(expression, dict) else "eq",
                "value": next(iter(expression.values())) if isinstance(expression, dict) else expression,
            }
            for field, expression in filters.items()
        ]
    if isinstance(filters, list):
        return [dict(item) for item in filters if isinstance(item, dict)]
    return [{
        "field": config.get("field"),
        "op": config.get("op") or config.get("operator") or "eq",
        "value": config.get("value"),
    }]


def _duckdb_point_expressions(alias: str, config: Dict[str, Any], side: str = "") -> tuple[str, str]:
    prefix = f"{side}_" if side else ""
    latitude_field = config.get(f"{prefix}latitude_field")
    longitude_field = config.get(f"{prefix}longitude_field")
    if latitude_field or longitude_field:
        latitude = _quoted_identifier(str(latitude_field or "latitude"))
        longitude = _quoted_identifier(str(longitude_field or "longitude"))
        return f"{alias}.{latitude}", f"{alias}.{longitude}"
    geometry_field = str(config.get(f"{prefix}geometry_field") or "geometry")
    geometry = f"{alias}.{_quoted_identifier(geometry_field)}"
    coordinates = f"struct_extract({geometry}, 'coordinates')"
    return f"{coordinates}[2]", f"{coordinates}[1]"


def _duckdb_distance_expression(left_lat: str, left_lon: str, right_lat: str, right_lon: str) -> str:
    delta_lat = f"radians(({right_lat}) - ({left_lat}))"
    delta_lon = f"radians(({right_lon}) - ({left_lon}))"
    haversine = (
        f"pow(sin(({delta_lat}) / 2), 2) + "
        f"cos(radians({left_lat})) * cos(radians({right_lat})) * "
        f"pow(sin(({delta_lon}) / 2), 2)"
    )
    bounded = f"least(1.0, greatest(0.0, {haversine}))"
    return f"6371000.0 * 2.0 * atan2(sqrt({bounded}), sqrt(1.0 - ({bounded})))"


def _duckdb_mgrs_projection(sql: str, config: Dict[str, Any]) -> str:
    latitude = _quoted_identifier(str(config.get("latitude_field") or "latitude"))
    longitude = _quoted_identifier(str(config.get("longitude_field") or "longitude"))
    target = _quoted_identifier(str(config.get("target_field") or "mgrs"))
    precision = int(config.get("precision", 5))
    if precision < 0 or precision > 5:
        raise HTTPException(status_code=422, detail="DuckDB MGRS precision must be between 0 and 5")
    scale = 10 ** (5 - precision)
    zone = (
        "CASE "
        "WHEN mgrs_lat >= 56 AND mgrs_lat < 64 AND mgrs_lon >= 3 AND mgrs_lon < 12 THEN 32 "
        "WHEN mgrs_lat >= 72 AND mgrs_lat < 84 AND mgrs_lon >= 0 AND mgrs_lon < 9 THEN 31 "
        "WHEN mgrs_lat >= 72 AND mgrs_lat < 84 AND mgrs_lon >= 9 AND mgrs_lon < 21 THEN 33 "
        "WHEN mgrs_lat >= 72 AND mgrs_lat < 84 AND mgrs_lon >= 21 AND mgrs_lon < 33 THEN 35 "
        "WHEN mgrs_lat >= 72 AND mgrs_lat < 84 AND mgrs_lon >= 33 AND mgrs_lon < 42 THEN 37 "
        "ELSE least(60, greatest(1, floor((mgrs_lon + 180) / 6)::INTEGER + 1)) END"
    )
    e2 = 0.0066943799901413165
    ep2 = e2 / (1 - e2)
    meridian_a = 1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256
    meridian_b = 3 * e2 / 8 + 3 * e2 * e2 / 32 + 45 * e2 ** 3 / 1024
    meridian_c = 15 * e2 * e2 / 256 + 45 * e2 ** 3 / 1024
    meridian_d = 35 * e2 ** 3 / 3072
    digits = "''" if precision == 0 else (
        f"lpad(floor(mod(mgrs_easting, 100000) / {scale})::BIGINT::VARCHAR, {precision}, '0') || "
        f"lpad(floor(mod(mgrs_northing, 100000) / {scale})::BIGINT::VARCHAR, {precision}, '0')"
    )
    compact = (
        "mgrs_zone::VARCHAR || "
        "substr('CDEFGHJKLMNPQRSTUVWX', least(20, floor((mgrs_lat + 80) / 8)::INTEGER + 1), 1) || "
        "substr(CASE mod(mgrs_zone - 1, 3) WHEN 0 THEN 'ABCDEFGH' WHEN 1 THEN 'JKLMNPQR' ELSE 'STUVWXYZ' END, "
        "greatest(1, least(8, floor(mgrs_easting / 100000)::INTEGER)), 1) || "
        "substr('ABCDEFGHJKLMNPQRSTUV', mod(floor(mgrs_northing / 100000)::INTEGER + "
        "CASE WHEN mod(mgrs_zone, 2) = 0 THEN 5 ELSE 0 END, 20) + 1, 1) || " + digits
    )
    return (
        f"SELECT input_rows.*, CASE WHEN mgrs_lat IS NULL OR mgrs_lon IS NULL THEN NULL "
        f"WHEN mgrs_lat < -80 OR mgrs_lat > 84 OR mgrs_lon < -180 OR mgrs_lon > 180 "
        f"THEN error('MGRS coordinates are outside the supported WGS84 range') ELSE {compact} END AS {target} "
        f"FROM ({sql}) AS input_rows "
        f"CROSS JOIN LATERAL (SELECT CAST(input_rows.{latitude} AS DOUBLE) AS mgrs_lat, "
        f"CAST(input_rows.{longitude} AS DOUBLE) AS mgrs_lon) AS mgrs_coordinates "
        f"CROSS JOIN LATERAL (SELECT {zone} AS mgrs_zone) AS mgrs_zones "
        f"CROSS JOIN LATERAL (SELECT radians(mgrs_lat) AS mgrs_lat_rad, radians(mgrs_lon) AS mgrs_lon_rad, "
        f"radians((mgrs_zone - 1) * 6 - 177) AS mgrs_lon0) AS mgrs_angles "
        f"CROSS JOIN LATERAL (SELECT sin(mgrs_lat_rad) AS mgrs_sin, cos(mgrs_lat_rad) AS mgrs_cos, "
        f"tan(mgrs_lat_rad) AS mgrs_tan) AS mgrs_trig "
        f"CROSS JOIN LATERAL (SELECT 6378137.0 / sqrt(1 - {e2} * mgrs_sin * mgrs_sin) AS mgrs_n, "
        f"mgrs_tan * mgrs_tan AS mgrs_t, {ep2} * mgrs_cos * mgrs_cos AS mgrs_c, "
        f"mgrs_cos * (mgrs_lon_rad - mgrs_lon0) AS mgrs_a, "
        f"6378137.0 * ({meridian_a} * mgrs_lat_rad - {meridian_b} * sin(2 * mgrs_lat_rad) + "
        f"{meridian_c} * sin(4 * mgrs_lat_rad) - {meridian_d} * sin(6 * mgrs_lat_rad)) AS mgrs_m) AS mgrs_terms "
        f"CROSS JOIN LATERAL (SELECT 0.9996 * mgrs_n * (mgrs_a + (1 - mgrs_t + mgrs_c) * pow(mgrs_a, 3) / 6 + "
        f"(5 - 18 * mgrs_t + mgrs_t * mgrs_t + 72 * mgrs_c - 58 * {ep2}) * pow(mgrs_a, 5) / 120) + 500000 AS mgrs_easting, "
        f"0.9996 * (mgrs_m + mgrs_n * mgrs_tan * (mgrs_a * mgrs_a / 2 + "
        f"(5 - mgrs_t + 9 * mgrs_c + 4 * mgrs_c * mgrs_c) * pow(mgrs_a, 4) / 24 + "
        f"(61 - 58 * mgrs_t + mgrs_t * mgrs_t + 600 * mgrs_c - 330 * {ep2}) * pow(mgrs_a, 6) / 720)) + "
        f"CASE WHEN mgrs_lat < 0 THEN 10000000 ELSE 0 END AS mgrs_northing) AS mgrs_utm"
    )


def _polygon_rings(value: Any) -> List[List[tuple[float, float]]]:
    if not isinstance(value, dict) or value.get("type") != "Polygon" or not isinstance(value.get("coordinates"), list):
        raise HTTPException(status_code=422, detail="DuckDB geofence requires a GeoJSON Polygon")
    rings: List[List[tuple[float, float]]] = []
    total_vertices = 0
    for raw_ring in value["coordinates"]:
        if not isinstance(raw_ring, list) or len(raw_ring) < 4:
            raise HTTPException(status_code=422, detail="DuckDB geofence rings require at least four positions")
        ring: List[tuple[float, float]] = []
        for position in raw_ring:
            if not isinstance(position, (list, tuple)) or len(position) < 2:
                raise HTTPException(status_code=422, detail="DuckDB geofence positions require longitude and latitude")
            longitude, latitude = float(position[0]), float(position[1])
            if not math.isfinite(longitude) or not math.isfinite(latitude) or not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise HTTPException(status_code=422, detail="DuckDB geofence positions must be finite WGS84 coordinates")
            ring.append((longitude, latitude))
        if ring[0] != ring[-1]:
            raise HTTPException(status_code=422, detail="DuckDB geofence rings must be closed")
        total_vertices += len(ring)
        rings.append(ring)
    if not rings or total_vertices > 10_000:
        raise HTTPException(status_code=422, detail="DuckDB geofence requires 1-10,000 polygon positions")
    return rings


def _duckdb_ring_edges(ring: List[tuple[float, float]]) -> List[List[float]]:
    """Return non-horizontal ray-crossing edges as one typed DuckDB value.

    Binding an edge list keeps compiled SQL bounded for operational polygons
    with thousands of vertices. The former implementation emitted one CASE
    expression per edge, which eventually hit parser depth and query-size
    limits before the executor could evaluate the data.
    """
    edges: List[List[float]] = []
    previous = ring[-1]
    for current in ring:
        lon_i, lat_i = current
        lon_j, lat_j = previous
        if lat_i != lat_j:
            edges.append([lon_i, lat_i, lon_j, lat_j])
        previous = current
    return edges


def _duckdb_ring_predicate(
    longitude: str,
    latitude: str,
    ring: List[tuple[float, float]],
    bind: Any,
) -> str:
    edges = _duckdb_ring_edges(ring)
    if not edges:
        return "FALSE"
    # DuckDB's Python client recursively infers nested list/struct parameters;
    # a 9K-edge operational boundary can spend tens of seconds in binding
    # before query execution. Compact JSON is one scalar parameter and is
    # decoded set-wise by DuckDB in milliseconds.
    edge_parameter = bind(json.dumps(edges, separators=(",", ":")))
    return (
        "mod((SELECT count(*) FROM (SELECT "
        "CAST(json_extract(value, '$[0]') AS DOUBLE) AS lon_i, "
        "CAST(json_extract(value, '$[1]') AS DOUBLE) AS lat_i, "
        "CAST(json_extract(value, '$[2]') AS DOUBLE) AS lon_j, "
        "CAST(json_extract(value, '$[3]') AS DOUBLE) AS lat_j "
        f"FROM json_each({edge_parameter})) AS polygon_edge WHERE "
        f"((polygon_edge.lat_i > ({latitude})) <> (polygon_edge.lat_j > ({latitude}))) "
        f"AND ({longitude}) < ((polygon_edge.lon_j - polygon_edge.lon_i) * "
        f"(({latitude}) - polygon_edge.lat_i) / "
        "(polygon_edge.lat_j - polygon_edge.lat_i) + polygon_edge.lon_i)), 2) = 1"
    )


def _duckdb_polygon_filter_sql(
    current_sql: str,
    config: Dict[str, Any],
    polygon: Any,
    bind: Any,
) -> str:
    """Evaluate a polygon once per distinct coordinate, then restore rows.

    Industrial telemetry commonly repeats coordinates across millions of
    observations. A distinct point relation avoids multiplying every repeated
    observation by every polygon edge while retaining exact point-in-polygon
    semantics, including holes.
    """
    rings = _polygon_rings(polygon)
    point_latitude, point_longitude = _duckdb_point_expressions("point_rows", config)
    source_latitude, source_longitude = _duckdb_point_expressions("source_rows", config)
    outer_longitudes = [position[0] for position in rings[0]]
    outer_latitudes = [position[1] for position in rings[0]]
    min_lon, max_lon = min(outer_longitudes), max(outer_longitudes)
    min_lat, max_lat = min(outer_latitudes), max(outer_latitudes)
    outer = _duckdb_ring_predicate("polygon_lon", "polygon_lat", rings[0], bind)
    holes = [
        _duckdb_ring_predicate("polygon_lon", "polygon_lat", ring, bind)
        for ring in rings[1:]
    ]
    predicate = f"({outer})" + "".join(f" AND NOT ({hole})" for hole in holes)
    return (
        f"WITH polygon_source AS ({current_sql}), polygon_points AS ("
        f"SELECT DISTINCT CAST({point_latitude} AS DOUBLE) AS polygon_lat, "
        f"CAST({point_longitude} AS DOUBLE) AS polygon_lon "
        "FROM polygon_source AS point_rows "
        f"WHERE {point_latitude} IS NOT NULL AND {point_longitude} IS NOT NULL "
        f"AND {point_longitude} BETWEEN {bind(min_lon)}::DOUBLE AND {bind(max_lon)}::DOUBLE "
        f"AND {point_latitude} BETWEEN {bind(min_lat)}::DOUBLE AND {bind(max_lat)}::DOUBLE), "
        f"polygon_inside AS (SELECT polygon_lat, polygon_lon FROM polygon_points WHERE {predicate}) "
        "SELECT source_rows.* FROM polygon_source AS source_rows "
        "INNER JOIN polygon_inside ON "
        f"CAST({source_latitude} AS DOUBLE) = polygon_inside.polygon_lat AND "
        f"CAST({source_longitude} AS DOUBLE) = polygon_inside.polygon_lon"
    )


def _compile_duckdb_plan(
    db: Session,
    plan: PipelineExecutionPlan,
    graph: pipeline_builder_ops.PipelineBuilderGraph,
    parameters: Dict[str, Any],
    source_file_overrides: Optional[Dict[str, List[str]]] = None,
) -> tuple[str, Dict[str, Any], List[DataAssetSnapshot], List[Dict[str, Any]]]:
    ordered = pipeline_builder_ops._topological_nodes(graph)
    predecessors = pipeline_builder_ops._predecessors(graph)
    unsupported = sorted({
        pipeline_builder_ops._node_type(node)
        for _node_id, node in ordered
        if pipeline_builder_ops._node_type(node) not in _DUCKDB_SNAPSHOT_OPERATIONS
    })
    if unsupported:
        raise HTTPException(status_code=422, detail={
            "message": "DuckDB snapshot executor does not support these operations",
            "operations": unsupported,
        })
    source_snapshots: Dict[str, DataAssetSnapshot] = {}
    sql_by_node: Dict[str, str] = {}
    parameters_by_node: Dict[str, Dict[str, Any]] = {}
    current_sql = ""
    sql_parameters: Dict[str, Any] = {}
    metrics: List[Dict[str, Any]] = []
    parameter_index = 0

    def bind(value: Any) -> str:
        nonlocal parameter_index
        name = f"pipeline_parameter_{parameter_index}"
        parameter_index += 1
        sql_parameters[name] = value
        return f"${name}"

    def snapshot_relation(asset_id: str, snapshot_id: str = "") -> tuple[str, DataAssetSnapshot]:
        snapshot = db.get(DataAssetSnapshot, snapshot_id) if snapshot_id else None
        if snapshot is None and asset_id:
            snapshot = db.query(DataAssetSnapshot).filter(
                DataAssetSnapshot.project_id == plan.project_id,
                DataAssetSnapshot.asset_id == asset_id,
                DataAssetSnapshot.status == "AVAILABLE",
            ).order_by(DataAssetSnapshot.snapshot_number.desc()).first()
        if not snapshot:
            raise HTTPException(status_code=422, detail=f"No available snapshot exists for input '{asset_id or snapshot_id}'")
        if snapshot.project_id != plan.project_id or (asset_id and snapshot.asset_id != asset_id):
            raise HTTPException(status_code=409, detail="Input snapshot belongs to another project or asset")
        source_snapshots[snapshot.id] = snapshot
        requested_files = (source_file_overrides or {}).get(snapshot.id)
        return f"SELECT * FROM {_duckdb_parquet_relation(snapshot, requested_files)}", snapshot

    for node_id, node in ordered:
        node_type = pipeline_builder_ops._node_type(node)
        config = {
            **pipeline_builder_ops._config(node),
            **(parameters.get(node_id, {}) if isinstance(parameters.get(node_id), dict) else {}),
        }
        started = time.perf_counter()
        if node_type in {"input_dataset", "dataset_input"}:
            snapshot_id = str(config.get("snapshot_id") or "")
            asset_id = str(config.get("asset_id") or config.get("dataset_id") or "")
            current_sql, _snapshot = snapshot_relation(asset_id, snapshot_id)
            sql_parameters = {}
        else:
            parent_ids = predecessors.get(node_id, [])
            if not parent_ids:
                raise HTTPException(status_code=422, detail=f"DuckDB node '{node_id}' has no input")
            if parent_ids[0] not in sql_by_node:
                raise HTTPException(status_code=422, detail=f"DuckDB node '{node_id}' references an unresolved input")
            current_sql = sql_by_node[parent_ids[0]]
            sql_parameters = dict(parameters_by_node[parent_ids[0]])

        if node_type == "filter":
            predicates = []
            operators = {
                "eq": "=", "equals": "=", "==": "=", "ne": "<>", "not_equals": "<>",
                "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
            }
            for spec in _filter_specs(config):
                field = spec.get("field")
                if not field:
                    continue
                operation = str(spec.get("op") or spec.get("operator") or "eq").lower()
                identifier = _quoted_identifier(str(field))
                value = spec.get("value")
                if operation in operators:
                    predicates.append(f"{identifier} {operators[operation]} {bind(value)}")
                elif operation == "contains":
                    predicates.append(f"CAST({identifier} AS VARCHAR) ILIKE {bind(f'%{value}%')}")
                elif operation == "in":
                    values = value if isinstance(value, list) else [value]
                    predicates.append("FALSE" if not values else f"{identifier} IN ({', '.join(bind(item) for item in values)})")
                elif operation in {"is_null", "null"}:
                    predicates.append(f"{identifier} IS {'NOT ' if value is False else ''}NULL")
                else:
                    raise HTTPException(status_code=422, detail=f"Unsupported DuckDB filter operator '{operation}'")
            current_sql = f"SELECT * FROM ({current_sql}) AS input_rows" + (f" WHERE {' AND '.join(predicates)}" if predicates else "")
        elif node_type in {"project", "select"}:
            fields = config.get("columns") or config.get("fields") or []
            if fields:
                current_sql = f"SELECT {', '.join(_quoted_identifier(str(field)) for field in fields)} FROM ({current_sql}) AS input_rows"
        elif node_type == "rename":
            mapping = config.get("mapping") or {}
            if mapping:
                clauses = ", ".join(f"{_quoted_identifier(str(source))} AS {_quoted_identifier(str(target))}" for source, target in mapping.items())
                current_sql = f"SELECT * RENAME ({clauses}) FROM ({current_sql}) AS input_rows"
        elif node_type == "cast":
            mapping = config.get("mapping") or config.get("types") or ({config["field"]: config.get("target_type")} if config.get("field") else {})
            clauses = ", ".join(
                f"TRY_CAST({_quoted_identifier(str(field))} AS {_duckdb_type(str(target))}) AS {_quoted_identifier(str(field))}"
                for field, target in mapping.items()
            )
            if clauses:
                current_sql = f"SELECT * REPLACE ({clauses}) FROM ({current_sql}) AS input_rows"
        elif node_type == "derive":
            derivations = config.get("derivations") or [config]
            additions = []
            for spec in derivations:
                target = spec.get("target") or spec.get("target_field") or spec.get("as")
                fields = spec.get("fields") or spec.get("source_fields") or ([spec.get("field")] if spec.get("field") else [])
                operation = str(spec.get("operation") or spec.get("op") or "copy").lower()
                identifiers = [_quoted_identifier(str(field)) for field in fields]
                if not target:
                    continue
                if operation == "copy" and identifiers:
                    expression = identifiers[0]
                elif operation in {"lower", "upper", "trim"} and identifiers:
                    expression = f"{operation}({identifiers[0]})"
                elif operation == "concat" and identifiers:
                    expression = f"concat_ws({bind(str(spec.get('separator', '')))}, {', '.join(identifiers)})"
                elif operation in {"add", "subtract", "multiply", "divide"} and identifiers:
                    operator = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}[operation]
                    expression = f" {operator} ".join(identifiers)
                else:
                    raise HTTPException(status_code=422, detail=f"Unsupported DuckDB derive operation '{operation}'")
                additions.append(f"{expression} AS {_quoted_identifier(str(target))}")
            if additions:
                current_sql = f"SELECT *, {', '.join(additions)} FROM ({current_sql}) AS input_rows"
        elif node_type == "fill_nulls":
            defaults = config.get("defaults") or config.get("mapping") or ({config["field"]: config.get("value")} if config.get("field") else {})
            clauses = []
            for field, value in defaults.items():
                clauses.append(
                    f"coalesce({_quoted_identifier(str(field))}, {bind(value)}) AS {_quoted_identifier(str(field))}"
                )
            if clauses:
                current_sql = f"SELECT * REPLACE ({', '.join(clauses)}) FROM ({current_sql}) AS input_rows"
        elif node_type == "normalize":
            mode = str(config.get("case") or config.get("mode") or "trim").lower()
            if mode not in {"trim", "lower", "upper", "title"}:
                raise HTTPException(status_code=422, detail=f"Unsupported DuckDB normalization mode '{mode}'")
            clauses = []
            for field in config.get("fields") or []:
                identifier = _quoted_identifier(str(field))
                expression = f"trim({identifier})"
                if mode in {"lower", "upper"}:
                    expression = f"{mode}({expression})"
                elif mode == "title":
                    expression = (
                        f"array_to_string(list_transform(regexp_split_to_array(lower({expression}), '\\s+'), "
                        f"word -> upper(substr(word, 1, 1)) || substr(word, 2)), ' ')"
                    )
                clauses.append(f"{expression} AS {identifier}")
            if clauses:
                current_sql = f"SELECT * REPLACE ({', '.join(clauses)}) FROM ({current_sql}) AS input_rows"
        elif node_type == "deduplicate":
            keys = config.get("keys") or config.get("fields") or []
            if not keys:
                raise HTTPException(status_code=422, detail="DuckDB deduplicate requires key fields")
            direction = "DESC" if str(config.get("keep", "first")).lower() == "last" else "ASC"
            order_fields = config.get("order_by") or config.get("order_fields") or keys
            order_fields = [order_fields] if isinstance(order_fields, str) else order_fields
            order_clause = ", ".join(
                f"{_quoted_identifier(str(field))} {direction} NULLS LAST"
                for field in order_fields
            )
            current_sql = (
                f"SELECT * FROM ({current_sql}) AS input_rows QUALIFY "
                f"row_number() OVER (PARTITION BY {', '.join(_quoted_identifier(str(field)) for field in keys)} "
                f"ORDER BY {order_clause}) = 1"
            )
        elif node_type in {"join", "union"}:
            parent_ids = predecessors.get(node_id, [])
            if len(parent_ids) > 2:
                raise HTTPException(status_code=422, detail=f"DuckDB {node_type} supports exactly two inputs")
            right_sql = sql_by_node[parent_ids[1]] if len(parent_ids) == 2 else ""
            right_parameters = dict(parameters_by_node[parent_ids[1]]) if len(parent_ids) == 2 else {}
            configured_asset = str(config.get("right_asset_id") or (config.get("asset_id") if node_type == "union" else "") or "")
            configured_snapshot = str(config.get("right_snapshot_id") or config.get("snapshot_id") or "")
            if configured_asset or configured_snapshot:
                if len(parent_ids) == 2:
                    raise HTTPException(status_code=422, detail=f"DuckDB {node_type} cannot combine a second branch and configured dataset")
                right_sql, _snapshot = snapshot_relation(configured_asset, configured_snapshot)
                right_parameters = {}
            if not right_sql:
                raise HTTPException(status_code=422, detail=f"DuckDB {node_type} requires a second branch or configured dataset")
            left_sql = current_sql
            left_parameters = sql_parameters
            if node_type == "union":
                current_sql = f"SELECT * FROM ({left_sql}) AS left_rows UNION ALL BY NAME SELECT * FROM ({right_sql}) AS right_rows"
            else:
                left_key = str(config.get("left_key") or config.get("on") or "")
                right_key = str(config.get("right_key") or config.get("on") or "")
                if not left_key or not right_key:
                    raise HTTPException(status_code=422, detail="DuckDB join requires left_key and right_key")
                how = str(config.get("how") or "inner").lower()
                join_type = {"inner": "INNER", "left": "LEFT", "right": "RIGHT", "outer": "FULL", "full": "FULL"}.get(how)
                if not join_type:
                    raise HTTPException(status_code=422, detail=f"Unsupported DuckDB join type '{how}'")
                right_projection = "right_rows.*"
                if right_key == left_key:
                    right_projection = f"right_rows.* EXCLUDE ({_quoted_identifier(right_key)})"
                current_sql = (
                    f"SELECT left_rows.*, {right_projection} FROM ({left_sql}) AS left_rows "
                    f"{join_type} JOIN ({right_sql}) AS right_rows ON "
                    f"left_rows.{_quoted_identifier(left_key)} = right_rows.{_quoted_identifier(right_key)}"
                )
            sql_parameters = {**left_parameters, **right_parameters}
        elif node_type == "unique_id":
            target = str(config.get("target_field") or "id")
            fields = config.get("source_fields") or config.get("fields") or []
            if not fields:
                raise HTTPException(status_code=422, detail="DuckDB unique_id requires source fields")
            values = ", ".join(
                f"coalesce(CAST({_quoted_identifier(str(field))} AS VARCHAR), 'None')"
                for field in fields
            )
            current_sql = (
                f"SELECT *, substr(sha1(concat_ws('|', {values})), 1, 16) AS {_quoted_identifier(target)} "
                f"FROM ({current_sql}) AS input_rows"
            )
        elif node_type == "pivot":
            index_fields = config.get("index") or config.get("group_by") or []
            index_fields = [index_fields] if isinstance(index_fields, str) else index_fields
            column_field = config.get("column") or config.get("column_field")
            value_field = config.get("value") or config.get("value_field")
            operation = str(config.get("operation") or config.get("aggregation") or "first").lower()
            aggregate = {"first": "first", "sum": "sum", "count": "count"}.get(operation)
            if not column_field or not value_field or not aggregate:
                raise HTTPException(status_code=422, detail="DuckDB pivot requires index, column, value, and a supported aggregation")
            group_clause = (
                " GROUP BY " + ", ".join(_quoted_identifier(str(field)) for field in index_fields)
                if index_fields else ""
            )
            current_sql = (
                f"PIVOT ({current_sql}) ON {_quoted_identifier(str(column_field))} "
                f"USING {aggregate}({_quoted_identifier(str(value_field))}){group_clause}"
            )
        elif node_type == "unpivot":
            value_fields = config.get("value_fields") or []
            if not value_fields:
                raise HTTPException(status_code=422, detail="DuckDB unpivot requires value_fields")
            name_field = _quoted_identifier(str(config.get("name_field") or "field"))
            value_field = _quoted_identifier(str(config.get("value_field") or "value"))
            current_sql = (
                f"UNPIVOT ({current_sql}) ON "
                f"{', '.join(_quoted_identifier(str(field)) for field in value_fields)} "
                f"INTO NAME {name_field} VALUE {value_field}"
            )
        elif node_type == "window":
            partition_by = config.get("partition_by") or []
            partition_by = [partition_by] if isinstance(partition_by, str) else partition_by
            order_by = config.get("order_by")
            operation = str(config.get("operation") or "row_number").lower()
            target = str(config.get("target_field") or operation)
            field = config.get("field") or config.get("value_field")
            window_parts = []
            if partition_by:
                window_parts.append("PARTITION BY " + ", ".join(_quoted_identifier(str(item)) for item in partition_by))
            if order_by:
                window_parts.append(f"ORDER BY {_quoted_identifier(str(order_by))} ASC NULLS LAST")
            if operation == "row_number":
                expression = f"row_number() OVER ({' '.join(window_parts)})"
            elif operation == "rank":
                if not order_by:
                    raise HTTPException(status_code=422, detail="DuckDB rank requires order_by")
                expression = f"rank() OVER ({' '.join(window_parts)})"
            elif operation == "running_sum":
                if not field or not order_by:
                    raise HTTPException(status_code=422, detail="DuckDB running_sum requires field and order_by")
                expression = (
                    f"sum(coalesce({_quoted_identifier(str(field))}, 0)) OVER "
                    f"({' '.join(window_parts)} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"
                )
            else:
                raise HTTPException(status_code=422, detail=f"Unsupported DuckDB window operation '{operation}'")
            current_sql = f"SELECT *, {expression} AS {_quoted_identifier(target)} FROM ({current_sql}) AS input_rows"
        elif node_type == "validate":
            checks = config.get("checks") or ([{
                "field": config.get("field"), "type": config.get("check", "required"),
                "expected": config.get("expected"), "min": config.get("min"), "max": config.get("max"),
                "values": config.get("values") or config.get("allowed_values"),
            }] if config.get("field") else [])
            error_expressions = []
            for check in checks:
                field = check.get("field")
                if not field:
                    continue
                identifier = _quoted_identifier(str(field))
                check_type = str(check.get("type") or "required").lower()
                predicates = []
                message = f"{field} failed {check_type} validation"
                if check_type in {"required", "non_null"}:
                    predicates.append(f"{identifier} IS NULL")
                    message = f"{field} is required"
                elif check_type == "range":
                    if check.get("min") is not None:
                        predicates.append(f"{identifier} < {bind(check['min'])}")
                    if check.get("max") is not None:
                        predicates.append(f"{identifier} > {bind(check['max'])}")
                elif check_type in {"allowed", "allowed_values"}:
                    values = check.get("values") or check.get("allowed_values") or []
                    predicates.append("TRUE" if not values else f"{identifier} NOT IN ({', '.join(bind(item) for item in values)})")
                elif check_type == "type":
                    expected = str(check.get("expected") or "string").lower()
                    accepted = {
                        "string": ["VARCHAR"],
                        "integer": ["TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"],
                        "number": ["TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL"],
                        "boolean": ["BOOLEAN"],
                    }.get(expected)
                    if not accepted:
                        raise HTTPException(status_code=422, detail=f"Unsupported DuckDB validation type '{expected}'")
                    type_checks = " AND ".join(
                        f"NOT starts_with(typeof({identifier}), {_duckdb_literal(item)})" for item in accepted
                    )
                    predicates.append(f"{identifier} IS NOT NULL AND {type_checks}")
                else:
                    raise HTTPException(status_code=422, detail=f"Unsupported DuckDB validation check '{check_type}'")
                if predicates:
                    error_expressions.append(
                        f"CASE WHEN {' OR '.join(f'({predicate})' for predicate in predicates)} "
                        f"THEN {_duckdb_literal(message)} END"
                    )
            if error_expressions:
                errors_sql = f"list_filter([{', '.join(error_expressions)}], item -> item IS NOT NULL)"
                validated_sql = f"SELECT *, {errors_sql} AS _validation_errors FROM ({current_sql}) AS input_rows"
                on_error = str(config.get("on_error") or "annotate").lower()
                if on_error == "drop":
                    current_sql = f"SELECT * FROM ({validated_sql}) AS validated_rows WHERE len(_validation_errors) = 0"
                elif on_error == "fail":
                    current_sql = (
                        f"SELECT * FROM ({validated_sql}) AS validated_rows WHERE "
                        f"CASE WHEN len(_validation_errors) > 0 "
                        f"THEN error(array_to_string(_validation_errors, '; ')) ELSE true END"
                    )
                elif on_error == "annotate":
                    current_sql = validated_sql
                else:
                    raise HTTPException(status_code=422, detail=f"Unsupported DuckDB validation mode '{on_error}'")
        elif node_type == "derive_geo_point":
            latitude = _quoted_identifier(str(config.get("latitude_field") or "latitude"))
            longitude = _quoted_identifier(str(config.get("longitude_field") or "longitude"))
            target = _quoted_identifier(str(config.get("target_field") or "geometry"))
            geometry = (
                f"CASE WHEN {latitude} IS NULL OR {longitude} IS NULL THEN NULL ELSE "
                f"struct_pack(type := 'Point', coordinates := [CAST({longitude} AS DOUBLE), CAST({latitude} AS DOUBLE)]) END"
            )
            current_sql = f"SELECT *, {geometry} AS {target} FROM ({current_sql}) AS input_rows"
        elif node_type == "derive_mgrs":
            current_sql = _duckdb_mgrs_projection(current_sql, config)
        elif node_type == "spatial_filter":
            mode = str(config.get("mode") or "radius").lower()
            latitude, longitude = _duckdb_point_expressions("input_rows", config)
            if mode == "radius":
                center = config.get("center") or {}
                if center.get("latitude") is None or center.get("longitude") is None:
                    raise HTTPException(status_code=422, detail="DuckDB radius filter requires center latitude and longitude")
                radius = float(config.get("radius_meters") or 0)
                if radius <= 0:
                    raise HTTPException(status_code=422, detail="DuckDB radius filter requires a positive radius_meters")
                distance = _duckdb_distance_expression(latitude, longitude, "bounds.center_lat", "bounds.center_lon")
                current_sql = (
                    f"SELECT input_rows.* FROM ({current_sql}) AS input_rows CROSS JOIN "
                    f"(SELECT {bind(center['latitude'])}::DOUBLE AS center_lat, "
                    f"{bind(center['longitude'])}::DOUBLE AS center_lon, {bind(radius)}::DOUBLE AS radius_meters) AS bounds "
                    f"WHERE {latitude} IS NOT NULL AND {longitude} IS NOT NULL AND {distance} <= bounds.radius_meters"
                )
            elif mode in {"geofence", "polygon"}:
                current_sql = _duckdb_polygon_filter_sql(
                    current_sql,
                    config,
                    config.get("polygon") or config.get("geofence"),
                    bind,
                )
            else:
                raise HTTPException(status_code=422, detail=f"Unsupported DuckDB spatial filter mode '{mode}'")
        elif node_type == "spatial_join":
            parent_ids = predecessors.get(node_id, [])
            if len(parent_ids) > 2:
                raise HTTPException(status_code=422, detail="DuckDB spatial_join supports exactly two inputs")
            right_sql = sql_by_node[parent_ids[1]] if len(parent_ids) == 2 else ""
            right_parameters = dict(parameters_by_node[parent_ids[1]]) if len(parent_ids) == 2 else {}
            configured_asset = str(config.get("right_asset_id") or "")
            configured_snapshot = str(config.get("right_snapshot_id") or "")
            if configured_asset or configured_snapshot:
                if len(parent_ids) == 2:
                    raise HTTPException(status_code=422, detail="DuckDB spatial_join cannot combine a second branch and configured dataset")
                right_sql, _snapshot = snapshot_relation(configured_asset, configured_snapshot)
                right_parameters = {}
            if not right_sql:
                raise HTTPException(status_code=422, detail="DuckDB spatial_join requires a second branch or configured dataset")
            maximum = float(config.get("max_distance_meters") or config.get("distance_meters") or 1000)
            if maximum <= 0:
                raise HTTPException(status_code=422, detail="DuckDB spatial_join requires a positive distance")
            left_sql = current_sql
            left_parameters = sql_parameters
            left_lat, left_lon = _duckdb_point_expressions("left_rows", config, "left")
            right_lat, right_lon = _duckdb_point_expressions("right_rows", config, "right")
            distance = _duckdb_distance_expression(left_lat, left_lon, right_lat, right_lon)
            distance_field = _quoted_identifier(str(config.get("distance_field") or "distance_meters"))
            joined_sql = (
                f"SELECT left_rows.*, right_rows.*, {distance} AS {distance_field} "
                f"FROM ({left_sql}) AS left_rows CROSS JOIN ({right_sql}) AS right_rows "
                f"WHERE {left_lat} IS NOT NULL AND {left_lon} IS NOT NULL "
                f"AND {right_lat} IS NOT NULL AND {right_lon} IS NOT NULL"
            )
            sql_parameters = {**left_parameters, **right_parameters}
            current_sql = f"SELECT * FROM ({joined_sql}) AS joined_rows WHERE {distance_field} <= {bind(maximum)}"
        elif node_type == "aggregate":
            group_by = config.get("group_by") or []
            group_by = [group_by] if isinstance(group_by, str) else group_by
            metrics_config = config.get("metrics") or [{
                "operation": config.get("operation") or "count",
                "field": config.get("field"),
                "alias": config.get("target_field") or config.get("alias") or "count",
            }]
            group_fields = [_quoted_identifier(str(field)) for field in group_by]
            aggregate_fields = []
            for metric in metrics_config:
                operation = str(metric.get("operation") or metric.get("op") or "count").lower()
                if operation not in {"count", "sum", "avg", "min", "max"}:
                    raise HTTPException(status_code=422, detail=f"Unsupported DuckDB aggregate '{operation}'")
                field = metric.get("field")
                expression = "*" if operation == "count" and not field else _quoted_identifier(str(field))
                alias = metric.get("alias") or metric.get("as") or f"{operation}_{field or 'rows'}"
                aggregate_fields.append(f"{operation}({expression}) AS {_quoted_identifier(str(alias))}")
            selection = ", ".join([*group_fields, *aggregate_fields])
            current_sql = f"SELECT {selection} FROM ({current_sql}) AS input_rows" + (f" GROUP BY {', '.join(group_fields)}" if group_fields else "")
        elif node_type == "sort":
            field = config.get("field")
            if field:
                direction = "DESC" if str(config.get("direction", "asc")).lower() == "desc" else "ASC"
                current_sql = f"SELECT * FROM ({current_sql}) AS input_rows ORDER BY {_quoted_identifier(str(field))} {direction} NULLS LAST"
        elif node_type == "limit":
            row_limit = max(1, int(config.get("limit") or config.get("count") or 1))
            current_sql = f"SELECT * FROM ({current_sql}) AS input_rows LIMIT {row_limit}"
        sql_by_node[node_id] = current_sql
        parameters_by_node[node_id] = dict(sql_parameters)
        metrics.append({
            "node_id": node_id,
            "operation": node_type,
            "compile_ms": round((time.perf_counter() - started) * 1000, 3),
        })
    if not source_snapshots:
        raise HTTPException(status_code=422, detail="DuckDB plan has no input snapshot")
    if not ordered:
        raise HTTPException(status_code=422, detail="DuckDB plan has no nodes")
    final_node_id = ordered[-1][0]
    return sql_by_node[final_node_id], parameters_by_node[final_node_id], list(source_snapshots.values()), metrics


def execute_duckdb_snapshot_partition(
    db: Session,
    plan_id: str,
    *,
    source_snapshot_id: str,
    source_files: List[str],
    parameters: Dict[str, Any],
    execution_group_id: str,
    partition_index: int,
    partition_count: int,
    actor: str,
) -> Dict[str, Any]:
    """Execute one manifest subset and publish an immutable intermediate fragment."""
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="DuckDB execution requires the duckdb dependency") from exc
    if not re.fullmatch(r"[a-f0-9]{32}", execution_group_id):
        raise HTTPException(status_code=422, detail="Invalid distributed execution group")
    if partition_index < 0 or partition_count < 2 or partition_index >= partition_count:
        raise HTTPException(status_code=422, detail="Invalid distributed partition coordinates")
    plan = db.get(PipelineExecutionPlan, plan_id)
    if not plan or plan.executor != "duckdb":
        raise HTTPException(status_code=404, detail="DuckDB pipeline execution plan not found")
    graph = db.get(pipeline_builder_ops.PipelineBuilderGraph, plan.graph_id)
    if not graph or graph.project_id != plan.project_id or graph.updated_at != plan.graph_updated_at:
        raise HTTPException(status_code=409, detail="Pipeline changed after this distributed plan was compiled")
    source_snapshot = db.get(DataAssetSnapshot, source_snapshot_id)
    if not source_snapshot or source_snapshot.project_id != plan.project_id:
        raise HTTPException(status_code=404, detail="Distributed source snapshot not found")
    distribution = _partition_execution_spec(db, plan, graph, partition_count, parameters)
    if not distribution["eligible"] or distribution["source_snapshot_id"] != source_snapshot.id:
        raise HTTPException(status_code=422, detail="Pipeline is no longer safe for partition execution")
    expected_files = list(distribution["partitions"][partition_index])
    if list(source_files) != expected_files:
        raise HTTPException(status_code=409, detail="Distributed partition assignment no longer matches the immutable plan")
    allowed_files = set((source_snapshot.partition_spec or {}).get("_manifest", {}).get("files") or [])
    if not source_files or len(source_files) > 10_000 or any(item not in allowed_files for item in source_files):
        raise HTTPException(status_code=422, detail="Distributed partition references files outside the immutable manifest")

    sql, sql_parameters, source_snapshots, compile_metrics = _compile_duckdb_plan(
        db, plan, graph, parameters,
        source_file_overrides={source_snapshot.id: list(source_files)},
    )
    if [snapshot.id for snapshot in source_snapshots] != [source_snapshot.id]:
        raise HTTPException(status_code=422, detail="Distributed partition resolved an unexpected input snapshot")
    started = time.perf_counter()
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET preserve_insertion_order = false")
        connection.execute("SET threads = 4")
        with tempfile.TemporaryDirectory(prefix="ontology-pipeline-partition-") as temporary:
            fragment = Path(temporary) / f"part-{partition_index:05d}.parquet"
            connection.execute(
                f"COPY ({sql}) TO {_duckdb_literal(fragment.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)",
                sql_parameters,
            )
            metadata = _parquet_manifest_metadata(fragment.parent, [fragment], partitioned=False)
            project_key = hashlib.sha256(plan.project_id.encode("utf-8")).hexdigest()[:20]
            key = f"pipeline-fragments/{project_key}/{execution_group_id}/part-{partition_index:05d}.parquet"
            storage_uri = _storage().put(key, fragment.read_bytes(), "application/vnd.apache.parquet")
    except (duckdb.BinderException, duckdb.ConversionException, duckdb.InvalidInputException) as exc:
        raise HTTPException(status_code=422, detail=f"DuckDB partition execution rejected plan: {exc}") from exc
    finally:
        connection.close()
    return {
        "engine": "duckdb-distributed-partition",
        "plan_id": plan.id,
        "plan_hash": plan.plan_hash,
        "execution_group_id": execution_group_id,
        "partition_index": partition_index,
        "partition_count": partition_count,
        "source_snapshot_id": source_snapshot.id,
        "source_files": list(source_files),
        "fragment": {
            "storage_uri": storage_uri,
            "content_hash": metadata["content_hash"],
            "row_count": int(metadata["row_count"]),
            "byte_size": int(metadata["byte_size"]),
            "schema": metadata["schema"],
        },
        "metrics": {
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "compile_steps": compile_metrics,
            "materialized_python_rows": 0,
        },
        "actor": actor,
    }


def finalize_duckdb_snapshot_partitions(
    db: Session,
    plan_id: str,
    *,
    partition_job_ids: List[str],
    source_snapshot_id: str,
    output_asset_id: Optional[str],
    parameters: Dict[str, Any],
    execution_group_id: str,
    actor: str,
    execution_job_id: str,
    execution_lease_token: str,
) -> Dict[str, Any]:
    """Validate shard results and publish one lease-fenced immutable snapshot."""
    if not partition_job_ids or len(partition_job_ids) > 256 or len(set(partition_job_ids)) != len(partition_job_ids):
        raise HTTPException(status_code=422, detail="Distributed finalizer requires unique partition jobs")
    plan = db.get(PipelineExecutionPlan, plan_id)
    if not plan or plan.executor != "duckdb":
        raise HTTPException(status_code=404, detail="DuckDB pipeline execution plan not found")
    graph = db.get(pipeline_builder_ops.PipelineBuilderGraph, plan.graph_id)
    if not graph or graph.project_id != plan.project_id or graph.updated_at != plan.graph_updated_at:
        raise HTTPException(status_code=409, detail="Pipeline changed after this distributed plan was compiled")
    source_snapshot = db.get(DataAssetSnapshot, source_snapshot_id)
    if not source_snapshot or source_snapshot.project_id != plan.project_id:
        raise HTTPException(status_code=404, detail="Distributed source snapshot not found")
    jobs_by_id = {
        row.id: row for row in db.query(platform_runtime.PlatformJob).filter(
            platform_runtime.PlatformJob.id.in_(partition_job_ids),
        ).all()
    }
    if len(jobs_by_id) != len(partition_job_ids):
        raise HTTPException(status_code=409, detail="Distributed finalizer is missing partition jobs")
    fragments = []
    for job_id in partition_job_ids:
        job = jobs_by_id[job_id]
        result = dict(job.result or {})
        fragment = dict(result.get("fragment") or {})
        if (
            job.project_id != plan.project_id
            or job.job_type != "pipeline.duckdb.partition"
            or job.status != "SUCCEEDED"
            or result.get("execution_group_id") != execution_group_id
            or result.get("source_snapshot_id") != source_snapshot.id
            or int(result.get("partition_count") or 0) != len(partition_job_ids)
            or not fragment.get("storage_uri")
        ):
            raise HTTPException(status_code=409, detail=f"Partition job '{job_id}' is not a valid completed shard")
        fragments.append({"job_id": job_id, "partition_index": int(result["partition_index"]), **fragment})
    fragments.sort(key=lambda item: (item["partition_index"], item["job_id"]))
    if [item["partition_index"] for item in fragments] != list(range(len(fragments))):
        raise HTTPException(status_code=409, detail="Distributed partition results are incomplete or duplicated")

    ordered_nodes = pipeline_builder_ops._topological_nodes(graph)
    if ordered_nodes:
        final_node_id, final_node = ordered_nodes[-1]
        final_config = {
            **pipeline_builder_ops._config(final_node),
            **(parameters.get(final_node_id, {}) if isinstance(parameters.get(final_node_id), dict) else {}),
            **(parameters.get("__output__", {}) if isinstance(parameters.get("__output__"), dict) else {}),
        }
    else:
        final_config = {}
    asset_id = str(output_asset_id or final_config.get("asset_id") or final_config.get("dataset_id") or final_config.get("output_asset_id") or f"{graph.id}_output")
    output_snapshot_id = f"dataset_snapshot_{hashlib.sha256(f'{plan.project_id}:{asset_id}:{execution_job_id}'.encode('utf-8')).hexdigest()[:32]}"
    prior = db.get(DataAssetSnapshot, output_snapshot_id)
    if prior and (prior.project_id != plan.project_id or prior.asset_id != str(asset_id)):
        raise HTTPException(status_code=409, detail="Distributed execution snapshot identity conflicts with another output")
    if prior:
        return {
            "engine": "duckdb-distributed-finalizer", "mode": "deliver", "plan_id": plan.id,
            "plan_hash": plan.plan_hash, "execution_group_id": execution_group_id,
            "partition_count": len(fragments), "input_row_count": source_snapshot.row_count,
            "row_count": prior.row_count, "schema": prior.schema or {},
            "output_snapshot": _snapshot_dict(prior), "idempotent_replay": True,
        }

    root = LocalSnapshotStorage().root.resolve()
    publish_dir = (root / plan.project_id / str(asset_id)).resolve()
    if root not in publish_dir.parents:
        raise HTTPException(status_code=422, detail="Dataset output path escaped DATA_SNAPSHOT_ROOT")
    publish_dir.mkdir(parents=True, exist_ok=True)
    stable_suffix = hashlib.sha256(f"{plan.project_id}:{asset_id}:{execution_job_id}".encode("utf-8")).hexdigest()[:12]
    staging = publish_dir / f".distributed-{stable_suffix}-{uuid.uuid4().hex}.tmp"
    started = time.perf_counter()
    try:
        staging.mkdir(parents=True, exist_ok=False)
        staged_files = []
        for item in fragments:
            payload = _storage_for_uri(str(item["storage_uri"])).get(str(item["storage_uri"]))
            if len(payload) != int(item["byte_size"]) or hashlib.sha256(payload).hexdigest() != item["content_hash"]:
                raise HTTPException(status_code=409, detail=f"Partition fragment {item['job_id']} failed integrity validation")
            target_file = staging / f"part-{item['partition_index']:05d}.parquet"
            target_file.write_bytes(payload)
            staged_files.append(target_file)
        metadata = _parquet_manifest_metadata(staging, staged_files, partitioned=True)
        schema = metadata["schema"]
        with _cache_file_lock(publish_dir / ".publish.lock"):
            asset, concurrent_prior = _lock_snapshot_publication(
                db,
                project_id=plan.project_id,
                asset_id=str(asset_id),
                display_name=f"{graph.display_name} output",
                execution_idempotency_key=execution_job_id,
                execution_fence_job_id=execution_job_id,
                execution_lease_token=execution_lease_token,
            )
            if concurrent_prior:
                _remove_internal_output_path(staging, root)
                return {
                    "engine": "duckdb-distributed-finalizer", "mode": "deliver", "plan_id": plan.id,
                    "plan_hash": plan.plan_hash, "execution_group_id": execution_group_id,
                    "partition_count": len(fragments), "input_row_count": source_snapshot.row_count,
                    "row_count": concurrent_prior.row_count, "schema": concurrent_prior.schema or {},
                    "output_snapshot": _snapshot_dict(concurrent_prior), "idempotent_replay": True,
                }
            snapshot_number = int(db.query(func.max(DataAssetSnapshot.snapshot_number)).filter(
                DataAssetSnapshot.project_id == plan.project_id,
                DataAssetSnapshot.asset_id == asset_id,
            ).scalar() or 0) + 1
            target = publish_dir / f"{snapshot_number}-{stable_suffix}"
            if target.exists():
                _remove_internal_output_path(target, root)
            os.replace(staging, target)
            storage_uri = _publish_output_snapshot(
                target, project_id=plan.project_id, asset_id=str(asset_id),
                metadata=metadata, partitioned=True,
            )
            snapshot = DataAssetSnapshot(
                id=output_snapshot_id,
                project_id=plan.project_id, asset_id=str(asset_id), snapshot_number=snapshot_number,
                status="AVAILABLE", storage_format="parquet", storage_uri=storage_uri,
                content_hash=metadata["content_hash"], row_count=int(metadata["row_count"]),
                byte_size=int(metadata["byte_size"]), schema=schema,
                partition_spec={
                    "fields": [], "hive_partitioning": False,
                    "execution_partitions": len(fragments), "_manifest": metadata["manifest"],
                },
                lineage={
                    "source_snapshot_id": source_snapshot.id,
                    "source_snapshot_ids": [source_snapshot.id],
                    "pipeline_plan_id": plan.id, "plan_hash": plan.plan_hash,
                    "execution_job_id": execution_job_id,
                    "execution_fence_job_id": execution_job_id,
                    "distributed_execution_group_id": execution_group_id,
                    "partition_job_ids": partition_job_ids,
                    "file_count": len(fragments), "distributed": True,
                },
                created_by=actor, created_at=int(time.time()),
            )
            db.add(snapshot)
            asset.records = []
            asset.asset_schema = {**schema, "project_id": plan.project_id, "storage_mode": "snapshot"}
            asset.updated_at = int(time.time())
            create_audit_log(
                db, actor=actor, event_type="pipeline.duckdb.distributed_delivered",
                subject_type="data_asset_snapshot", subject_id=snapshot.id,
                payload={
                    "project_id": plan.project_id, "plan_id": plan.id,
                    "source_snapshot_id": source_snapshot.id, "output_asset_id": asset_id,
                    "row_count": snapshot.row_count, "content_hash": snapshot.content_hash,
                    "partition_count": len(fragments), "partition_job_ids": partition_job_ids,
                    "execution_group_id": execution_group_id, "execution_job_id": execution_job_id,
                    "lease_fenced": True,
                },
            )
            db.commit()
            output_snapshot = _snapshot_dict(snapshot)
    except Exception:
        if staging.exists():
            _remove_internal_output_path(staging, root)
        raise
    return {
        "engine": "duckdb-distributed-finalizer", "mode": "deliver", "plan_id": plan.id,
        "plan_hash": plan.plan_hash, "execution_group_id": execution_group_id,
        "partition_count": len(fragments), "partition_job_ids": partition_job_ids,
        "input_row_count": source_snapshot.row_count, "row_count": int(metadata["row_count"]),
        "schema": schema, "output_snapshot": output_snapshot, "idempotent_replay": False,
        "metrics": {
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "materialized_python_rows": 0, "fragment_bytes": int(metadata["byte_size"]),
        },
    }


def execute_duckdb_snapshot_plan(
    db: Session,
    plan_id: str,
    *,
    mode: str,
    limit: int,
    output_asset_id: Optional[str],
    parameters: Dict[str, Any],
    actor: str,
    execution_job_id: Optional[str] = None,
    execution_fence_job_id: Optional[str] = None,
    execution_lease_token: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="DuckDB execution requires the duckdb dependency") from exc
    plan = db.get(PipelineExecutionPlan, plan_id)
    if not plan or plan.executor != "duckdb":
        raise HTTPException(status_code=404, detail="DuckDB pipeline execution plan not found")
    graph = db.get(pipeline_builder_ops.PipelineBuilderGraph, plan.graph_id)
    if not graph or graph.project_id != plan.project_id:
        raise HTTPException(status_code=404, detail="Pipeline graph not found for plan")
    if graph.updated_at != plan.graph_updated_at:
        raise HTTPException(status_code=409, detail="Pipeline changed after this plan was compiled")
    sql, sql_parameters, source_snapshots, compile_metrics = _compile_duckdb_plan(db, plan, graph, parameters)
    ordered_nodes = pipeline_builder_ops._topological_nodes(graph)
    final_node_id, final_node = ordered_nodes[-1]
    final_config = {
        **pipeline_builder_ops._config(final_node),
        **(parameters.get(final_node_id, {}) if isinstance(parameters.get(final_node_id), dict) else {}),
        **(parameters.get("__output__", {}) if isinstance(parameters.get("__output__"), dict) else {}),
    }
    partition_fields = _output_partition_fields(final_config) if mode == "deliver" else []
    source_snapshot = source_snapshots[0]
    source_snapshot_ids = [snapshot.id for snapshot in source_snapshots]
    input_row_count = sum(snapshot.row_count for snapshot in source_snapshots)
    started = time.perf_counter()
    asset_id = (
        output_asset_id
        or final_config.get("asset_id")
        or final_config.get("dataset_id")
        or final_config.get("output_asset_id")
        or f"{graph.id}_output"
    )

    def replay_payload(prior: DataAssetSnapshot) -> Dict[str, Any]:
        return {
            "engine": "duckdb-snapshot", "mode": mode, "plan_id": plan.id,
            "plan_hash": plan.plan_hash, "source_snapshot_id": source_snapshot.id,
            "source_snapshot_ids": source_snapshot_ids,
            "input_row_count": input_row_count, "row_count": prior.row_count,
            "rows": [], "schema": prior.schema or {}, "output_snapshot": _snapshot_dict(prior),
            "idempotent_replay": True,
            "metrics": {
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "operations": len(compile_metrics), "compile_steps": compile_metrics,
                "materialized_python_rows": 0,
            },
        }

    if mode == "deliver" and execution_job_id:
        prior_snapshots = db.query(DataAssetSnapshot).filter(
            DataAssetSnapshot.project_id == plan.project_id,
            DataAssetSnapshot.asset_id == asset_id,
        ).order_by(DataAssetSnapshot.snapshot_number.desc()).limit(100).all()
        prior = next((
            row for row in prior_snapshots
            if str((row.lineage or {}).get("execution_job_id") or "") == execution_job_id
        ), None)
        if prior:
            return replay_payload(prior)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET preserve_insertion_order = false")
        connection.execute("SET threads = 4")
        if mode == "preview":
            preview_parameters = {
                **sql_parameters,
                "ontology_preview_limit": max(1, min(limit, 500)),
            }
            result = connection.execute(
                f"SELECT result_rows.*, count(*) OVER() AS __ontology_total "
                f"FROM ({sql}) AS result_rows LIMIT $ontology_preview_limit",
                preview_parameters,
            )
            names = [column[0] for column in result.description]
            values = result.fetchall()
            total_index = names.index("__ontology_total")
            rows = [
                {name: row[index] for index, name in enumerate(names) if index != total_index}
                for row in values
            ]
            row_count = int(values[0][total_index]) if values else 0
            schema = {"fields": [
                {"name": name, "type": str(result.description[index][1])}
                for index, name in enumerate(names) if index != total_index
            ]}
            output_snapshot = None
        else:
            root = LocalSnapshotStorage().root.resolve()
            output_token = execution_job_id or uuid.uuid4().hex
            stable_suffix = hashlib.sha256(
                f"{plan.project_id}:{asset_id}:{output_token}".encode("utf-8")
            ).hexdigest()[:12]
            publish_dir = (root / plan.project_id / asset_id).resolve()
            if root not in publish_dir.parents:
                raise HTTPException(status_code=422, detail="Dataset output path escaped DATA_SNAPSHOT_ROOT")
            description = connection.execute(
                f"DESCRIBE SELECT * FROM ({sql}) AS output_rows",
                sql_parameters,
            ).fetchall()
            schema = {"fields": [{"name": row[0], "type": row[1]} for row in description]}
            schema_names = {field["name"] for field in schema["fields"]}
            missing_partitions = [field for field in partition_fields if field not in schema_names]
            if missing_partitions:
                raise HTTPException(
                    status_code=422,
                    detail=f"Dataset output partition fields are missing from the output schema: {', '.join(missing_partitions)}",
                )
            publish_dir.mkdir(parents=True, exist_ok=True)
            staging_name = f".delivery-{stable_suffix}-{uuid.uuid4().hex}.tmp"
            if not partition_fields:
                staging_name += ".parquet"
            staging = publish_dir / staging_name
            try:
                if partition_fields:
                    partition_clause = ", ".join(_quoted_identifier(field) for field in partition_fields)
                    connection.execute(
                        f"COPY ({sql}) TO {_duckdb_literal(staging.as_posix())} "
                        f"(FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY ({partition_clause}))",
                        sql_parameters,
                    )
                    staged_files = sorted(
                        (path.resolve() for path in staging.rglob("*.parquet") if path.is_file()),
                        key=lambda path: path.relative_to(staging).as_posix(),
                    )
                    if not staged_files:
                        staging.mkdir(parents=True, exist_ok=True)
                        empty_part = staging / "part-00000.parquet"
                        connection.execute(
                            f"COPY (SELECT * FROM ({sql}) AS output_rows LIMIT 0) "
                            f"TO {_duckdb_literal(empty_part.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)",
                            sql_parameters,
                        )
                        staged_files = [empty_part.resolve()]
                    metadata = _parquet_manifest_metadata(staging, staged_files, partitioned=True)
                else:
                    connection.execute(
                        f"COPY ({sql}) TO {_duckdb_literal(staging.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)",
                        sql_parameters,
                    )
                    metadata = _parquet_manifest_metadata(staging.parent, [staging], partitioned=False)
                with _cache_file_lock(publish_dir / ".publish.lock"):
                    asset, concurrent_prior = _lock_snapshot_publication(
                        db,
                        project_id=plan.project_id,
                        asset_id=asset_id,
                        display_name=f"{graph.display_name} output",
                        execution_idempotency_key=execution_job_id,
                        execution_fence_job_id=execution_fence_job_id,
                        execution_lease_token=execution_lease_token,
                    )
                    if concurrent_prior:
                        _remove_internal_output_path(staging, root)
                        return replay_payload(concurrent_prior)
                    snapshot_number = int(db.query(func.max(DataAssetSnapshot.snapshot_number)).filter(
                        DataAssetSnapshot.project_id == plan.project_id,
                        DataAssetSnapshot.asset_id == asset_id,
                    ).scalar() or 0) + 1
                    target_name = (
                        f"{snapshot_number}-{stable_suffix}"
                        if partition_fields
                        else f"{snapshot_number}-{stable_suffix}.parquet"
                    )
                    target = publish_dir / target_name
                    if target.exists():
                        _remove_internal_output_path(target, root)
                    os.replace(staging, target)
                    row_count = int(metadata["row_count"])
                    partition_spec = {
                        "fields": partition_fields,
                        "hive_partitioning": True,
                        "_manifest": metadata["manifest"],
                    } if partition_fields else {}
                    storage_uri = _publish_output_snapshot(
                        target,
                        project_id=plan.project_id,
                        asset_id=asset_id,
                        metadata=metadata,
                        partitioned=bool(partition_fields),
                    )
                    snapshot_id = (
                        f"dataset_snapshot_{hashlib.sha256(f'{plan.project_id}:{asset_id}:{execution_job_id}'.encode('utf-8')).hexdigest()[:32]}"
                        if execution_job_id else f"dataset_snapshot_{uuid.uuid4().hex}"
                    )
                    snapshot = DataAssetSnapshot(
                        id=snapshot_id, project_id=plan.project_id,
                        asset_id=asset_id, snapshot_number=snapshot_number, status="AVAILABLE",
                        storage_format="parquet", storage_uri=storage_uri, content_hash=metadata["content_hash"],
                        row_count=row_count, byte_size=int(metadata["byte_size"]), schema=schema,
                        partition_spec=partition_spec, lineage={
                            "source_snapshot_id": source_snapshot.id, "source_snapshot_ids": source_snapshot_ids,
                            "pipeline_plan_id": plan.id,
                            "plan_hash": plan.plan_hash, "execution_job_id": execution_job_id,
                            "execution_fence_job_id": execution_fence_job_id,
                            "file_count": int(metadata["manifest"]["file_count"]),
                            "partition_by": partition_fields,
                        }, created_by=actor, created_at=int(time.time()),
                    )
                    db.add(snapshot)
                    asset.records = []
                    asset.asset_schema = {**schema, "project_id": plan.project_id, "storage_mode": "snapshot"}
                    asset.updated_at = int(time.time())
                    create_audit_log(
                        db, actor=actor, event_type="pipeline.duckdb.delivered",
                        subject_type="data_asset_snapshot", subject_id=snapshot.id,
                        payload={
                            "project_id": plan.project_id, "plan_id": plan.id,
                            "source_snapshot_id": source_snapshot.id,
                            "source_snapshot_ids": source_snapshot_ids,
                            "output_asset_id": asset_id,
                            "row_count": row_count, "content_hash": snapshot.content_hash,
                            "file_count": int(metadata["manifest"]["file_count"]),
                            "partition_by": partition_fields,
                            "execution_job_id": execution_job_id,
                            "execution_fence_job_id": execution_fence_job_id,
                            "lease_fenced": bool(execution_fence_job_id),
                        },
                    )
                    db.commit()
                    output_snapshot = _snapshot_dict(snapshot)
                    rows = []
            except Exception:
                if staging.exists():
                    _remove_internal_output_path(staging, root)
                raise
    except (duckdb.BinderException, duckdb.ConversionException, duckdb.InvalidInputException) as exc:
        raise HTTPException(status_code=422, detail=f"DuckDB execution rejected plan: {exc}") from exc
    finally:
        connection.close()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "engine": "duckdb-snapshot",
        "mode": mode,
        "plan_id": plan.id,
        "plan_hash": plan.plan_hash,
        "source_snapshot_id": source_snapshot.id,
        "source_snapshot_ids": source_snapshot_ids,
        "input_row_count": input_row_count,
        "row_count": row_count,
        "rows": rows,
        "schema": schema,
        "output_snapshot": output_snapshot,
        "metrics": {
            "elapsed_ms": elapsed_ms,
            "operations": len(compile_metrics),
            "compile_steps": compile_metrics,
            "materialized_python_rows": len(rows),
        },
    }


def _snapshot_dict(row: DataAssetSnapshot) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "asset_id": row.asset_id,
        "snapshot_number": row.snapshot_number, "status": row.status,
        "storage_format": row.storage_format, "storage_uri": row.storage_uri,
        "content_hash": row.content_hash, "row_count": row.row_count, "byte_size": row.byte_size,
        "schema": row.schema or {}, "partition_spec": row.partition_spec or {}, "lineage": row.lineage or {},
        "created_by": row.created_by, "created_at": row.created_at,
    }


@router.get("/snapshot-cache/summary")
def snapshot_cache_summary(principal: Principal = Depends(require_permission("view"))):
    inventory = _cache_inventory()
    with _CACHE_METRICS_LOCK:
        metrics = dict(_CACHE_METRICS)
    return {
        "backend": os.getenv("DATA_SNAPSHOT_BACKEND", "local").strip().lower(),
        "cache_root": str(_snapshot_cache_root()),
        "cache_bytes": sum(int(entry["byte_size"]) for entry in inventory),
        "limit_bytes": _snapshot_cache_limit(),
        "entry_count": len(inventory),
        "file_count": sum(int(entry["file_count"]) for entry in inventory),
        "lease_seconds": max(0, int(os.getenv("DATA_SNAPSHOT_CACHE_LEASE_SECONDS", "3600"))),
        "metrics": metrics,
        "last_updated": int(time.time()),
    }


@router.post("/snapshot-cache/prune")
def prune_snapshot_cache(
    body: SnapshotCachePruneRequest = SnapshotCachePruneRequest(),
    principal: Principal = Depends(require_permission("administer")),
):
    result = _prune_snapshot_cache(target_bytes=body.target_bytes)
    return {**result, "requested_target_bytes": body.target_bytes, "last_updated": int(time.time())}


def _plan_dict(row: PipelineExecutionPlan) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "graph_id": row.graph_id,
        "graph_updated_at": row.graph_updated_at, "status": row.status, "executor": row.executor,
        "plan_hash": row.plan_hash, "logical_plan": row.logical_plan or {},
        "input_schema": row.input_schema or {}, "output_schema": row.output_schema or {},
        "field_lineage": row.field_lineage or {}, "validation": row.validation or {},
        "created_by": row.created_by, "created_at": row.created_at,
    }


def _compile_plan(db: Session, graph: pipeline_builder_ops.PipelineBuilderGraph, executor: str, actor: str) -> PipelineExecutionPlan:
    validation = pipeline_builder_ops._validate_graph(db, graph)
    operations = []
    input_schemas: Dict[str, Any] = {}
    field_lineage: Dict[str, List[Dict[str, Any]]] = {}
    for position, (node_id, node) in enumerate(pipeline_builder_ops._topological_nodes(graph)):
        node_type = pipeline_builder_ops._node_type(node)
        config = pipeline_builder_ops._config(node)
        operations.append({
            "position": position,
            "node_id": node_id,
            "operation": node_type,
            "config": config,
            "inputs": pipeline_builder_ops._predecessors(graph).get(node_id, []),
        })
        if node_type in {"input_dataset", "dataset_input"}:
            asset_id = str(config.get("asset_id") or config.get("dataset_id") or "")
            asset = db.get(models.DataAsset, asset_id) if asset_id else None
            if asset:
                snapshot_id = str(config.get("snapshot_id") or "")
                snapshot = db.get(DataAssetSnapshot, snapshot_id) if snapshot_id else db.query(DataAssetSnapshot).filter(
                    DataAssetSnapshot.project_id == graph.project_id,
                    DataAssetSnapshot.asset_id == asset.id,
                    DataAssetSnapshot.status == "AVAILABLE",
                ).order_by(DataAssetSnapshot.snapshot_number.desc()).first()
                input_schemas[node_id] = (
                    snapshot.schema if snapshot else asset.asset_schema
                ) or _infer_schema([dict(row) for row in (asset.records or []) if isinstance(row, dict)])
                for field in (input_schemas[node_id].get("fields") or []):
                    if isinstance(field, dict) and field.get("name"):
                        field_lineage[str(field["name"])] = [{
                            "asset_id": asset.id,
                            "snapshot_id": snapshot.id if snapshot else None,
                            "field": field["name"],
                            "node_id": node_id,
                        }]
        elif node_type == "rename":
            mapping = config.get("mapping") or {}
            for source, target in mapping.items():
                field_lineage[str(target)] = [*field_lineage.get(str(source), []), {"node_id": node_id, "operation": "rename", "source_field": source}]
        elif node_type in {"cast", "derive", "formula", "normalize", "select", "project"}:
            for field in set(config.get("fields") or []) | {str(config.get("target_field")) if config.get("target_field") else ""}:
                if field:
                    field_lineage.setdefault(field, []).append({"node_id": node_id, "operation": node_type})
    logical_plan = {
        "version": 1,
        "graph_id": graph.id,
        "graph_updated_at": graph.updated_at,
        "executor": executor,
        "operations": operations,
        "outputs": [node_id for node_id, node in pipeline_builder_ops._topological_nodes(graph) if pipeline_builder_ops._node_type(node) in {"dataset_output", "ontology_output"}],
    }
    canonical = json.dumps(logical_plan, sort_keys=True, separators=(",", ":"), default=str)
    plan_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = db.query(PipelineExecutionPlan).filter(
        PipelineExecutionPlan.project_id == graph.project_id,
        PipelineExecutionPlan.graph_id == graph.id,
        PipelineExecutionPlan.plan_hash == plan_hash,
    ).first()
    if existing:
        return existing
    row = PipelineExecutionPlan(
        id=f"pipeline_plan_{uuid.uuid4().hex}",
        project_id=graph.project_id,
        graph_id=graph.id,
        graph_updated_at=graph.updated_at,
        status="VALID" if not validation.get("errors") else "INVALID",
        executor=executor,
        plan_hash=plan_hash,
        logical_plan=logical_plan,
        input_schema=input_schemas,
        output_schema={},
        field_lineage=field_lineage,
        validation=validation,
        created_by=actor,
        created_at=int(time.time()),
    )
    db.add(row)
    db.flush()
    create_audit_log(
        db, actor=actor, event_type="pipeline.execution_plan.compiled", subject_type="pipeline_execution_plan", subject_id=row.id,
        payload={"project_id": graph.project_id, "graph_id": graph.id, "plan_hash": plan_hash, "status": row.status, "executor": executor},
    )
    return row


def ensure_dataset_snapshot(
    db: Session,
    asset: models.DataAsset,
    *,
    actor: str,
    storage_format: str = "auto",
    partition_spec: Optional[Dict[str, Any]] = None,
    lineage: Optional[Dict[str, Any]] = None,
) -> DataAssetSnapshot:
    """Create or reuse an immutable snapshot without owning the caller's transaction."""
    records = [dict(record) for record in (asset.records or []) if isinstance(record, dict)]
    if not records:
        raise HTTPException(status_code=422, detail="DataAsset has no embedded records to snapshot")
    payload, resolved_format, content_type = _serialize(records, storage_format)
    content_hash = hashlib.sha256(payload).hexdigest()
    existing = db.query(DataAssetSnapshot).filter(
        DataAssetSnapshot.project_id == asset.project_id,
        DataAssetSnapshot.asset_id == asset.id,
        DataAssetSnapshot.content_hash == content_hash,
    ).first()
    if existing:
        return existing
    snapshot_number = int(db.query(func.max(DataAssetSnapshot.snapshot_number)).filter(
        DataAssetSnapshot.project_id == asset.project_id,
        DataAssetSnapshot.asset_id == asset.id,
    ).scalar() or 0) + 1
    extension = "parquet" if resolved_format == "parquet" else "jsonl"
    key = f"{asset.project_id}/{asset.id}/{snapshot_number}-{content_hash[:12]}.{extension}"
    try:
        storage_uri = _storage().put(key, payload, content_type)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Snapshot storage failed: {exc}") from exc
    row = DataAssetSnapshot(
        id=f"dataset_snapshot_{uuid.uuid4().hex}", project_id=asset.project_id, asset_id=asset.id,
        snapshot_number=snapshot_number, status="AVAILABLE", storage_format=resolved_format,
        storage_uri=storage_uri, content_hash=content_hash, row_count=len(records), byte_size=len(payload),
        schema=asset.asset_schema or _infer_schema(records), partition_spec=partition_spec or {},
        lineage={**(lineage or {}), "source_asset_id": asset.id}, created_by=actor, created_at=int(time.time()),
    )
    db.add(row)
    db.flush()
    create_audit_log(
        db, actor=actor, event_type="dataset.snapshot.created", subject_type="data_asset_snapshot", subject_id=row.id,
        payload={
            "project_id": asset.project_id, "asset_id": asset.id, "snapshot_number": snapshot_number,
            "row_count": len(records), "content_hash": content_hash,
        },
    )
    return row


@router.post("/datasets/{asset_id}/snapshots", status_code=201)
def create_dataset_snapshot(asset_id: str, body: SnapshotCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    asset = semantic_scope.asset_for(db, principal, asset_id, "edit")
    row = ensure_dataset_snapshot(
        db, asset, actor=principal.id, storage_format=body.storage_format,
        partition_spec=body.partition_spec, lineage=body.lineage,
    )
    db.commit()
    return _snapshot_dict(row)


@router.post("/datasets/{asset_id}/snapshots/register", status_code=201)
def register_dataset_snapshot(asset_id: str, body: SnapshotRegister, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    """Register connector-produced local or S3 Parquet files without materializing rows."""
    asset = semantic_scope.asset_for(db, principal, asset_id, "edit")
    if body.storage_uri.startswith("s3://"):
        metadata, registered_uri, partitioned, file_count = _s3_registration_metadata(
            body.storage_uri, body.partition_spec or {},
        )
        registration = "external-s3-parquet-partitioned" if partitioned else "external-s3-parquet"
    else:
        target = _local_snapshot_target(body.storage_uri)
        base, files = _discover_parquet_files(body.storage_uri)
        partitioned = target.is_dir()
        metadata = _parquet_manifest_metadata(base, files, partitioned=partitioned)
        registered_uri = target.as_uri()
        file_count = len(files)
        registration = "external-parquet-partitioned" if partitioned else "external-parquet"
    content_hash = metadata["content_hash"]
    existing = db.query(DataAssetSnapshot).filter(
        DataAssetSnapshot.project_id == asset.project_id,
        DataAssetSnapshot.asset_id == asset.id,
        DataAssetSnapshot.content_hash == content_hash,
    ).first()
    if existing:
        return _snapshot_dict(existing)
    snapshot_number = int(db.query(func.max(DataAssetSnapshot.snapshot_number)).filter(
        DataAssetSnapshot.project_id == asset.project_id,
        DataAssetSnapshot.asset_id == asset.id,
    ).scalar() or 0) + 1
    schema = metadata["schema"]
    partition_spec = dict(body.partition_spec or {})
    if partitioned:
        partition_spec["_manifest"] = metadata["manifest"]
    row = DataAssetSnapshot(
        id=f"dataset_snapshot_{uuid.uuid4().hex}", project_id=asset.project_id,
        asset_id=asset.id, snapshot_number=snapshot_number, status="AVAILABLE",
        storage_format="parquet", storage_uri=registered_uri, content_hash=content_hash,
        row_count=metadata["row_count"], byte_size=metadata["byte_size"], schema=schema,
        partition_spec=partition_spec,
        lineage={
            **body.lineage, "source_asset_id": asset.id,
            "registration": registration,
            "file_count": file_count,
        },
        created_by=principal.id, created_at=int(time.time()),
    )
    db.add(row)
    asset.records = []
    asset.asset_schema = {**schema, "project_id": asset.project_id, "storage_mode": "snapshot"}
    asset.updated_at = int(time.time())
    create_audit_log(
        db, actor=principal.id, event_type="dataset.snapshot.registered",
        subject_type="data_asset_snapshot", subject_id=row.id,
        payload={
            "project_id": asset.project_id, "asset_id": asset.id,
            "snapshot_number": snapshot_number, "row_count": row.row_count,
            "byte_size": row.byte_size, "content_hash": content_hash,
            "file_count": file_count, "partitioned": partitioned,
            "storage_backend": "s3" if registered_uri.startswith("s3://") else "local",
        },
    )
    db.commit()
    return _snapshot_dict(row)


@router.get("/datasets/{asset_id}/snapshots")
def list_dataset_snapshots(asset_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    asset = semantic_scope.asset_for(db, principal, asset_id, "view")
    rows = db.query(DataAssetSnapshot).filter(
        DataAssetSnapshot.project_id == asset.project_id,
        DataAssetSnapshot.asset_id == asset.id,
    ).order_by(DataAssetSnapshot.snapshot_number.desc()).all()
    return {"asset_id": asset.id, "snapshots": [_snapshot_dict(row) for row in rows]}


@router.get("/dataset-snapshots/{snapshot_id}/rows")
def read_dataset_snapshot(snapshot_id: str, limit: int = 100, offset: int = 0, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = db.get(DataAssetSnapshot, snapshot_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dataset snapshot not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "view")
    offset = max(0, offset)
    limit = max(1, min(limit, 1000))
    try:
        if row.storage_format == "parquet":
            result = _query_local_parquet_snapshot(row, SnapshotQueryRequest(limit=limit, offset=offset))
            records = result["rows"]
        else:
            all_records = _deserialize(_storage_for_uri(row.storage_uri).get(row.storage_uri), row.storage_format)
            records = all_records[offset:offset + limit]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Snapshot read failed: {exc}") from exc
    return {
        "snapshot": _snapshot_dict(row), "count": len(records), "total": row.row_count, "rows": records,
        "next_offset": offset + limit if offset + limit < row.row_count else None,
    }


@router.post("/dataset-snapshots/{snapshot_id}/query")
def query_dataset_snapshot(snapshot_id: str, body: SnapshotQueryRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = db.get(DataAssetSnapshot, snapshot_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dataset snapshot not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "view")
    try:
        result = (
            _query_local_parquet_snapshot(row, body)
            if row.storage_format == "parquet"
            else _query_snapshot(_storage_for_uri(row.storage_uri).get(row.storage_uri), row.storage_format, body)
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Snapshot query failed: {exc}") from exc
    return {"snapshot": _snapshot_dict(row), **result}


@router.post("/pipelines/{graph_id}/plans", status_code=201)
def compile_pipeline_plan(graph_id: str, body: PlanCompileRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    graph = pipeline_builder_ops._graph_for(db, graph_id, principal, "edit")
    if body.executor == "duckdb":
        try:
            import duckdb  # noqa: F401
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="DuckDB execution requires the optional duckdb dependency") from exc
    row = _compile_plan(db, graph, body.executor, principal.id)
    db.commit()
    return _plan_dict(row)


@router.get("/pipelines/{graph_id}/plans")
def list_pipeline_plans(graph_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    graph = pipeline_builder_ops._graph_for(db, graph_id, principal, "view")
    rows = db.query(PipelineExecutionPlan).filter(
        PipelineExecutionPlan.project_id == graph.project_id,
        PipelineExecutionPlan.graph_id == graph.id,
    ).order_by(PipelineExecutionPlan.created_at.desc()).all()
    return {"graph_id": graph.id, "plans": [_plan_dict(row) for row in rows]}


@router.get("/pipeline-plans/{plan_id}")
def get_pipeline_plan(plan_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    plan = db.get(PipelineExecutionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Pipeline execution plan not found")
    tenancy.assert_project_permission(db, principal, plan.project_id, "view")
    pipeline_builder_ops._graph_for(db, plan.graph_id, principal, "view")
    return _plan_dict(plan)


@router.post("/pipeline-plans/{plan_id}/execute", status_code=202)
def execute_pipeline_plan(plan_id: str, body: PlanExecuteRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    plan = db.get(PipelineExecutionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Pipeline execution plan not found")
    tenancy.assert_project_permission(db, principal, plan.project_id, "deploy" if body.mode == "deliver" else "execute")
    graph = pipeline_builder_ops._graph_for(db, plan.graph_id, principal, "deploy" if body.mode == "deliver" else "execute")
    if graph.updated_at != plan.graph_updated_at:
        raise HTTPException(status_code=409, detail={"message": "Pipeline changed after this plan was compiled", "plan_graph_updated_at": plan.graph_updated_at, "current_graph_updated_at": graph.updated_at})
    if plan.status != "VALID":
        raise HTTPException(status_code=422, detail={"message": "Cannot execute an invalid plan", "validation": plan.validation})
    job = _executor(plan.executor).enqueue(plan, graph, body, principal, db)
    return {"plan": _plan_dict(plan), "execution": job}
