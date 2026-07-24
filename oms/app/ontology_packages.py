"""Governed, portable ontology packages with project-scoped installation."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, ontology_core, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["ontology_packages"])
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
API_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _now() -> int:
    return int(time.time())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class OntologyPackage(Base):
    __tablename__ = "ontology_packages"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    organization_id: Mapped[str] = mapped_column(String, index=True)
    owning_project_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="DRAFT", index=True)
    current_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class OntologyPackageVersion(Base):
    __tablename__ = "ontology_package_versions"
    __table_args__ = (UniqueConstraint("package_id", "version", name="uq_ontology_package_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    package_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="DRAFT", index=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String, index=True)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    author: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class OntologyPackageInstallation(Base):
    __tablename__ = "ontology_package_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    package_id: Mapped[str] = mapped_column(String, index=True)
    package_version_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String)
    target_project_id: Mapped[str] = mapped_column(String, index=True)
    namespace: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE", index=True)
    installed_resources: Mapped[list] = mapped_column(JSON, default=list)
    prior_state: Mapped[list] = mapped_column(JSON, default=list)
    previous_installation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    installed_by: Mapped[str] = mapped_column(String)
    installed_at: Mapped[int] = mapped_column(Integer)
    rolled_back_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class OntologyPackageResource(Base):
    __tablename__ = "ontology_package_resources"
    __table_args__ = (UniqueConstraint("target_project_id", "resource_type", "resource_id", name="uq_package_project_resource"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    package_id: Mapped[str] = mapped_column(String, index=True)
    installation_id: Mapped[str] = mapped_column(String, index=True)
    target_project_id: Mapped[str] = mapped_column(String, index=True)
    namespace: Mapped[str] = mapped_column(String)
    resource_type: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    source_resource_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class PackageCreate(BaseModel):
    id: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    organization_id: str
    owning_project_id: str
    display_name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class PackageVersionCreate(BaseModel):
    version: str
    manifest: Dict[str, Any]


class PackageCaptureRequest(BaseModel):
    version: str
    object_type_ids: List[str] = Field(min_length=1)
    action_type_ids: List[str] = Field(default_factory=list)
    dependencies: List[Dict[str, str]] = Field(default_factory=list)


class PackagePublishRequest(BaseModel):
    expected_checksum: Optional[str] = None


class PackageInstallRequest(BaseModel):
    target_project_id: str
    namespace: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    expected_checksum: Optional[str] = None


def _checksum(manifest: Dict[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _package(db: Session, package_id: str) -> OntologyPackage:
    row = db.get(OntologyPackage, package_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ontology package not found")
    return row


def _version(db: Session, package_id: str, version: str) -> OntologyPackageVersion:
    row = db.query(OntologyPackageVersion).filter(OntologyPackageVersion.package_id == package_id, OntologyPackageVersion.version == version).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ontology package version not found")
    return row


def _audit(db: Session, principal: Principal, event_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(id=_id("audit"), actor=principal.id, event_type=event_type, subject_type="ontology_package", subject_id=subject_id, payload=payload))


def _validate_manifest(db: Session, manifest: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []
    if manifest.get("schema_version") != 1:
        issues.append({"severity": "ERROR", "path": "schema_version", "message": "schema_version must be 1"})
    object_types = manifest.get("object_types") or []
    link_types = manifest.get("link_types") or []
    action_types = manifest.get("action_types") or []
    if not isinstance(object_types, list) or not isinstance(link_types, list) or not isinstance(action_types, list):
        issues.append({"severity": "ERROR", "path": "resources", "message": "Resource collections must be arrays"})
        object_types, link_types, action_types = [], [], []
    object_ids = [str(row.get("id", "")) for row in object_types if isinstance(row, dict)]
    if len(object_ids) != len(set(object_ids)):
        issues.append({"severity": "ERROR", "path": "object_types", "message": "Object type IDs must be unique"})
    for index, row in enumerate(object_types):
        if not isinstance(row, dict) or not API_NAME.match(str(row.get("id", ""))):
            issues.append({"severity": "ERROR", "path": f"object_types[{index}].id", "message": "A valid API name is required"})
            continue
        if not isinstance(row.get("properties", {}), dict):
            issues.append({"severity": "ERROR", "path": f"object_types[{index}].properties", "message": "Properties must be an object"})
        primary_key = row.get("primary_key")
        if primary_key and primary_key not in (row.get("properties") or {}):
            issues.append({"severity": "ERROR", "path": f"object_types[{index}].primary_key", "message": "Primary key must reference a declared property"})
    for index, row in enumerate(link_types):
        if not isinstance(row, dict) or not API_NAME.match(str(row.get("id", ""))):
            issues.append({"severity": "ERROR", "path": f"link_types[{index}].id", "message": "A valid API name is required"})
            continue
        if row.get("source_object_type_id") not in object_ids or row.get("target_object_type_id") not in object_ids:
            issues.append({"severity": "ERROR", "path": f"link_types[{index}]", "message": "Link endpoints must be object types in this package"})
        if row.get("cardinality", "MANY_TO_MANY") not in {"ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"}:
            issues.append({"severity": "ERROR", "path": f"link_types[{index}].cardinality", "message": "Unsupported cardinality"})
    dependencies = manifest.get("dependencies") or []
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict) or not dependency.get("package_id") or not dependency.get("version"):
            issues.append({"severity": "ERROR", "path": f"dependencies[{index}]", "message": "Dependency package_id and version are required"})
            continue
        dependency_version = db.query(OntologyPackageVersion).filter(
            OntologyPackageVersion.package_id == dependency["package_id"],
            OntologyPackageVersion.version == dependency["version"],
            OntologyPackageVersion.status == "PUBLISHED",
        ).first()
        if not dependency_version:
            issues.append({"severity": "ERROR", "path": f"dependencies[{index}]", "message": "Dependency is not published"})
    errors = sum(1 for issue in issues if issue["severity"] == "ERROR")
    return {
        "status": "PASS" if errors == 0 else "FAIL",
        "summary": {"object_types": len(object_types), "link_types": len(link_types), "action_types": len(action_types), "dependencies": len(dependencies), "errors": errors},
        "issues": issues,
        "validated_at": _now(),
    }


def _package_dict(db: Session, row: OntologyPackage, principal: Principal) -> Dict[str, Any]:
    versions = db.query(OntologyPackageVersion).filter(OntologyPackageVersion.package_id == row.id).count()
    installs = db.query(OntologyPackageInstallation).filter(OntologyPackageInstallation.package_id == row.id, OntologyPackageInstallation.status == "ACTIVE").count()
    project_allowed = tenancy.project_permissions(db, principal, row.owning_project_id)
    allowed = [name for name in ("view", "edit", "publish", "export", "restore", "administer") if principal.allows(name) and ("*" in project_allowed or name in project_allowed)]
    return {
        "id": row.id, "organization_id": row.organization_id, "owning_project_id": row.owning_project_id,
        "display_name": row.display_name, "description": row.description, "status": row.status,
        "current_version": row.current_version, "version_count": versions, "active_installations": installs,
        "permissions": allowed,
        "created_by": row.created_by, "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _version_dict(row: OntologyPackageVersion, include_manifest: bool = True) -> Dict[str, Any]:
    result = {
        "id": row.id, "package_id": row.package_id, "version": row.version, "status": row.status,
        "checksum": row.checksum, "validation": row.validation or {}, "author": row.author,
        "created_at": row.created_at, "published_at": row.published_at,
    }
    if include_manifest:
        result["manifest"] = row.manifest or {}
    return result


@router.post("/ontology-packages", status_code=201)
def create_package(body: PackageCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.owning_project_id, "edit")
    project = db.get(tenancy.PlatformProject, body.owning_project_id)
    if project and project.organization_id != body.organization_id:
        raise HTTPException(status_code=422, detail="Package organization must match the owning project")
    if principal.organization_id and principal.organization_id != body.organization_id:
        raise HTTPException(status_code=403, detail="Package organization does not match the authenticated organization")
    if db.get(OntologyPackage, body.id):
        raise HTTPException(status_code=409, detail="Ontology package already exists")
    now = _now()
    row = OntologyPackage(id=body.id, organization_id=body.organization_id, owning_project_id=body.owning_project_id, display_name=body.display_name, description=body.description, status="DRAFT", current_version=None, created_by=principal.id, created_at=now, updated_at=now)
    db.add(row)
    _audit(db, principal, "ontology.package.created", row.id, {"project_id": body.owning_project_id})
    db.commit()
    return _package_dict(db, row, principal)


@router.get("/ontology-packages")
def list_packages(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    allowed = tenancy.accessible_project_ids(db, principal, "view")
    query = db.query(OntologyPackage)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(OntologyPackage.owning_project_id == project_id)
    elif allowed is not None:
        query = query.filter(OntologyPackage.owning_project_id.in_(allowed)) if allowed else query.filter(OntologyPackage.id == "__none__")
    return [_package_dict(db, row, principal) for row in query.order_by(OntologyPackage.updated_at.desc()).all()]


@router.get("/ontology-packages/{package_id}")
def get_package(package_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _package(db, package_id)
    tenancy.assert_project_permission(db, principal, row.owning_project_id, "view")
    result = _package_dict(db, row, principal)
    result["versions"] = [_version_dict(version, False) for version in db.query(OntologyPackageVersion).filter(OntologyPackageVersion.package_id == package_id).order_by(OntologyPackageVersion.created_at.desc()).all()]
    return result


@router.post("/ontology-packages/{package_id}/versions", status_code=201)
def create_package_version(package_id: str, body: PackageVersionCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    package = _package(db, package_id)
    tenancy.assert_project_permission(db, principal, package.owning_project_id, "edit")
    if not SEMVER.match(body.version):
        raise HTTPException(status_code=422, detail="Version must be semantic versioning, for example 1.2.0")
    if db.query(OntologyPackageVersion).filter(OntologyPackageVersion.package_id == package_id, OntologyPackageVersion.version == body.version).first():
        raise HTTPException(status_code=409, detail="Package version already exists and is immutable")
    manifest = json.loads(json.dumps(body.manifest))
    manifest.setdefault("schema_version", 1)
    manifest.setdefault("package_id", package_id)
    validation = _validate_manifest(db, manifest)
    row = OntologyPackageVersion(id=_id("package_version"), package_id=package_id, version=body.version, status="DRAFT", manifest=manifest, checksum=_checksum(manifest), validation=validation, author=principal.id, created_at=_now(), published_at=None)
    db.add(row)
    package.updated_at = _now()
    _audit(db, principal, "ontology.package.version_created", package_id, {"version": body.version, "checksum": row.checksum, "validation": validation["status"]})
    db.commit()
    return _version_dict(row)


@router.post("/ontology-packages/{package_id}/versions/capture", status_code=201)
def capture_package_version(package_id: str, body: PackageCaptureRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    object_types = []
    for object_type_id in body.object_type_ids:
        row = db.get(models.ObjectType, object_type_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Object type '{object_type_id}' not found")
        properties = {name: value for name, value in (row.properties or {}).items() if not name.startswith("__")}
        manager = (row.properties or {}).get("__manager") or {}
        profile = db.get(ontology_core.ObjectTypeProfile, row.id)
        profile_manifest = None if not profile else {
            "api_name": profile.api_name, "primary_key": profile.primary_key, "title_key": profile.title_key,
            "icon": profile.icon, "color": profile.color, "plural_name": profile.plural_name,
            "groups": profile.groups or [], "properties": profile.properties or {},
        }
        object_types.append({"id": row.id, "display_name": row.display_name, "description": row.description, "properties": properties, "primary_key": profile.primary_key if profile else manager.get("primary_key"), "profile": profile_manifest})
    selected = set(body.object_type_ids)
    links = db.query(models.LinkType).filter(models.LinkType.source_object_type_id.in_(selected), models.LinkType.target_object_type_id.in_(selected)).all()
    link_types = [{"id": row.id, "display_name": row.display_name, "description": row.description, "source_object_type_id": row.source_object_type_id, "target_object_type_id": row.target_object_type_id, "cardinality": row.cardinality} for row in links]
    action_types = []
    for action_type_id in body.action_type_ids:
        row = db.get(models.ActionType, action_type_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Action type '{action_type_id}' not found")
        action_types.append({"id": row.id, "display_name": row.display_name, "description": row.description, "parameters": row.parameters or {}, "rules": row.rules or {}})
    return create_package_version(package_id, PackageVersionCreate(version=body.version, manifest={"schema_version": 1, "package_id": package_id, "object_types": object_types, "link_types": link_types, "action_types": action_types, "dependencies": body.dependencies}), principal, db)


@router.post("/ontology-packages/{package_id}/versions/{version}/validate")
def validate_package_version(package_id: str, version: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    package = _package(db, package_id)
    tenancy.assert_project_permission(db, principal, package.owning_project_id, "view")
    row = _version(db, package_id, version)
    validation = _validate_manifest(db, row.manifest or {})
    if row.status == "DRAFT":
        row.validation = validation
        db.commit()
    return validation


@router.post("/ontology-packages/{package_id}/versions/{version}/publish")
def publish_package_version(package_id: str, version: str, body: PackagePublishRequest, principal: Principal = Depends(require_permission("publish")), db: Session = Depends(get_db)):
    package = _package(db, package_id)
    tenancy.assert_project_permission(db, principal, package.owning_project_id, "publish")
    row = _version(db, package_id, version)
    if body.expected_checksum and body.expected_checksum != row.checksum:
        raise HTTPException(status_code=409, detail="Package checksum changed")
    validation = _validate_manifest(db, row.manifest or {})
    if validation["status"] != "PASS":
        raise HTTPException(status_code=422, detail={"message": "Package validation failed", "validation": validation})
    now = _now()
    row.validation = validation
    row.status = "PUBLISHED"
    row.published_at = now
    package.current_version = version
    package.status = "PUBLISHED"
    package.updated_at = now
    _audit(db, principal, "ontology.package.published", package_id, {"version": version, "checksum": row.checksum})
    db.commit()
    return _version_dict(row)


def _resource_id(namespace: str, source_id: str) -> str:
    return f"{namespace}__{source_id}"


def _owned_resource(db: Session, project_id: str, resource_type: str, resource_id: str) -> Optional[OntologyPackageResource]:
    return db.query(OntologyPackageResource).filter(OntologyPackageResource.target_project_id == project_id, OntologyPackageResource.resource_type == resource_type, OntologyPackageResource.resource_id == resource_id).first()


@router.post("/ontology-packages/{package_id}/versions/{version}/install", status_code=201)
def install_package_version(package_id: str, version: str, body: PackageInstallRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    package = _package(db, package_id)
    tenancy.assert_project_permission(db, principal, package.owning_project_id, "view")
    tenancy.assert_project_permission(db, principal, body.target_project_id, "edit")
    row = _version(db, package_id, version)
    if row.status != "PUBLISHED":
        raise HTTPException(status_code=409, detail="Only published package versions can be installed")
    if body.expected_checksum and body.expected_checksum != row.checksum:
        raise HTTPException(status_code=409, detail="Package checksum does not match")
    manifest = row.manifest or {}
    for dependency in manifest.get("dependencies") or []:
        installed = db.query(OntologyPackageInstallation).filter(
            OntologyPackageInstallation.package_id == dependency.get("package_id"),
            OntologyPackageInstallation.version == dependency.get("version"),
            OntologyPackageInstallation.target_project_id == body.target_project_id,
            OntologyPackageInstallation.status == "ACTIVE",
        ).first()
        if not installed:
            raise HTTPException(status_code=409, detail={"message": "Package dependency is not installed", "dependency": dependency})
    previous = db.query(OntologyPackageInstallation).filter(
        OntologyPackageInstallation.package_id == package_id,
        OntologyPackageInstallation.target_project_id == body.target_project_id,
        OntologyPackageInstallation.namespace == body.namespace,
        OntologyPackageInstallation.status == "ACTIVE",
    ).first()
    if previous and previous.version == version:
        return {
            "id": previous.id, "package_id": package_id, "version": version,
            "target_project_id": body.target_project_id, "namespace": body.namespace,
            "status": previous.status, "installed_resources": previous.installed_resources,
            "previous_installation_id": previous.previous_installation_id,
            "installed_at": previous.installed_at, "idempotent_replay": True,
        }
    installation_id = _id("package_installation")
    prior_state: List[Dict[str, Any]] = []
    installed_resources: List[Dict[str, str]] = []
    now = _now()

    def assert_ownership(resource_type: str, resource_id: str, existing: Any) -> Optional[OntologyPackageResource]:
        ownership = _owned_resource(db, body.target_project_id, resource_type, resource_id)
        if existing and (not ownership or ownership.package_id != package_id or ownership.namespace != body.namespace):
            raise HTTPException(status_code=409, detail={"message": "Target resource is owned outside this package installation", "resource_type": resource_type, "resource_id": resource_id})
        return ownership

    object_id_map = {item["id"]: _resource_id(body.namespace, item["id"]) for item in manifest.get("object_types") or []}
    for item in manifest.get("object_types") or []:
        resource_id = object_id_map[item["id"]]
        existing = db.get(models.ObjectType, resource_id)
        existing_profile = db.get(ontology_core.ObjectTypeProfile, resource_id)
        ownership = assert_ownership("object_type", resource_id, existing)
        prior_state.append({
            "resource_type": "object_type", "resource_id": resource_id,
            "state": {"display_name": existing.display_name, "description": existing.description, "properties": existing.properties} if existing else None,
            "profile_state": None if not existing_profile else {"api_name": existing_profile.api_name, "primary_key": existing_profile.primary_key, "title_key": existing_profile.title_key, "icon": existing_profile.icon, "color": existing_profile.color, "plural_name": existing_profile.plural_name, "groups": existing_profile.groups, "properties": existing_profile.properties, "created_at": existing_profile.created_at, "updated_at": existing_profile.updated_at},
        })
        properties = json.loads(json.dumps(item.get("properties") or {}))
        properties["__package"] = {"package_id": package_id, "version": version, "source_resource_id": item["id"], "target_project_id": body.target_project_id, "namespace": body.namespace}
        if item.get("primary_key"):
            properties.setdefault("__manager", {})["primary_key"] = item["primary_key"]
        if existing:
            existing.display_name, existing.description, existing.properties, existing.updated_at = item["display_name"], item.get("description"), properties, now
        else:
            db.add(models.ObjectType(id=resource_id, display_name=item["display_name"], description=item.get("description"), properties=properties, created_at=now, updated_at=now))
        profile_values = item.get("profile")
        if isinstance(profile_values, dict):
            values = {
                "api_name": profile_values.get("api_name") or item["id"],
                "primary_key": profile_values.get("primary_key") or item.get("primary_key"),
                "title_key": profile_values.get("title_key"), "icon": profile_values.get("icon"),
                "color": profile_values.get("color"), "plural_name": profile_values.get("plural_name"),
                "groups": profile_values.get("groups") or [], "properties": profile_values.get("properties") or {},
            }
            if existing_profile:
                for key, value in values.items(): setattr(existing_profile, key, value)
                existing_profile.updated_at = now
            else:
                db.add(ontology_core.ObjectTypeProfile(object_type_id=resource_id, **values, created_at=now, updated_at=now))
        if ownership:
            ownership.installation_id, ownership.updated_at = installation_id, now
        else:
            db.add(OntologyPackageResource(id=_id("package_resource"), package_id=package_id, installation_id=installation_id, target_project_id=body.target_project_id, namespace=body.namespace, resource_type="object_type", resource_id=resource_id, source_resource_id=item["id"], created_at=now, updated_at=now))
        installed_resources.append({"resource_type": "object_type", "resource_id": resource_id, "source_resource_id": item["id"]})

    for item in manifest.get("link_types") or []:
        resource_id = _resource_id(body.namespace, item["id"])
        existing = db.get(models.LinkType, resource_id)
        ownership = assert_ownership("link_type", resource_id, existing)
        prior_state.append({"resource_type": "link_type", "resource_id": resource_id, "state": {"display_name": existing.display_name, "description": existing.description, "source_object_type_id": existing.source_object_type_id, "target_object_type_id": existing.target_object_type_id, "cardinality": existing.cardinality} if existing else None})
        values = {"display_name": item["display_name"], "description": item.get("description"), "source_object_type_id": object_id_map[item["source_object_type_id"]], "target_object_type_id": object_id_map[item["target_object_type_id"]], "cardinality": item.get("cardinality", "MANY_TO_MANY")}
        if existing:
            for key, value in values.items(): setattr(existing, key, value)
        else:
            db.add(models.LinkType(id=resource_id, **values))
        if ownership:
            ownership.installation_id, ownership.updated_at = installation_id, now
        else:
            db.add(OntologyPackageResource(id=_id("package_resource"), package_id=package_id, installation_id=installation_id, target_project_id=body.target_project_id, namespace=body.namespace, resource_type="link_type", resource_id=resource_id, source_resource_id=item["id"], created_at=now, updated_at=now))
        installed_resources.append({"resource_type": "link_type", "resource_id": resource_id, "source_resource_id": item["id"]})

    for item in manifest.get("action_types") or []:
        resource_id = _resource_id(body.namespace, item["id"])
        existing = db.get(models.ActionType, resource_id)
        ownership = assert_ownership("action_type", resource_id, existing)
        prior_state.append({"resource_type": "action_type", "resource_id": resource_id, "state": {"display_name": existing.display_name, "description": existing.description, "parameters": existing.parameters, "rules": existing.rules} if existing else None})
        values = {"display_name": item["display_name"], "description": item.get("description"), "parameters": item.get("parameters") or {}, "rules": {**(item.get("rules") or {}), "__package": {"package_id": package_id, "version": version, "target_project_id": body.target_project_id}}}
        if existing:
            for key, value in values.items(): setattr(existing, key, value)
        else:
            db.add(models.ActionType(id=resource_id, **values))
        if ownership:
            ownership.installation_id, ownership.updated_at = installation_id, now
        else:
            db.add(OntologyPackageResource(id=_id("package_resource"), package_id=package_id, installation_id=installation_id, target_project_id=body.target_project_id, namespace=body.namespace, resource_type="action_type", resource_id=resource_id, source_resource_id=item["id"], created_at=now, updated_at=now))
        installed_resources.append({"resource_type": "action_type", "resource_id": resource_id, "source_resource_id": item["id"]})

    installation = OntologyPackageInstallation(id=installation_id, package_id=package_id, package_version_id=row.id, version=version, target_project_id=body.target_project_id, namespace=body.namespace, status="ACTIVE", installed_resources=installed_resources, prior_state=prior_state, previous_installation_id=previous.id if previous else None, installed_by=principal.id, installed_at=now, rolled_back_at=None)
    db.add(installation)
    if previous:
        previous.status = "SUPERSEDED"
    _audit(db, principal, "ontology.package.installed", installation.id, {"package_id": package_id, "version": version, "target_project_id": body.target_project_id, "namespace": body.namespace, "checksum": row.checksum, "resources": installed_resources})
    db.commit()
    return {"id": installation.id, "package_id": package_id, "version": version, "target_project_id": body.target_project_id, "namespace": body.namespace, "status": installation.status, "installed_resources": installed_resources, "previous_installation_id": installation.previous_installation_id, "installed_at": now}


@router.get("/ontology-package-installations")
def list_package_installations(project_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    rows = db.query(OntologyPackageInstallation).filter(OntologyPackageInstallation.target_project_id == project_id).order_by(OntologyPackageInstallation.installed_at.desc()).all()
    return [{"id": row.id, "package_id": row.package_id, "version": row.version, "target_project_id": row.target_project_id, "namespace": row.namespace, "status": row.status, "installed_resources": row.installed_resources, "previous_installation_id": row.previous_installation_id, "installed_at": row.installed_at, "rolled_back_at": row.rolled_back_at} for row in rows]


@router.post("/ontology-package-installations/{installation_id}/rollback")
def rollback_package_installation(installation_id: str, principal: Principal = Depends(require_permission("restore")), db: Session = Depends(get_db)):
    installation = db.get(OntologyPackageInstallation, installation_id)
    if not installation:
        raise HTTPException(status_code=404, detail="Package installation not found")
    tenancy.assert_project_permission(db, principal, installation.target_project_id, "restore")
    if installation.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Only an active installation can be rolled back")
    for item in installation.prior_state or []:
        if item["resource_type"] == "object_type" and item.get("state") is None:
            count = db.query(models.ObjectInstance).filter(models.ObjectInstance.object_type_id == item["resource_id"]).count()
            if count:
                raise HTTPException(status_code=409, detail={"message": "Rollback would remove an object type with live objects", "resource_id": item["resource_id"], "object_count": count})
    for item in reversed(installation.prior_state or []):
        resource_type, resource_id, state = item["resource_type"], item["resource_id"], item.get("state")
        model = {"object_type": models.ObjectType, "link_type": models.LinkType, "action_type": models.ActionType}[resource_type]
        current = db.get(model, resource_id)
        if resource_type == "object_type":
            current_profile = db.get(ontology_core.ObjectTypeProfile, resource_id)
            profile_state = item.get("profile_state")
            if profile_state is None and current_profile:
                db.delete(current_profile)
            elif profile_state:
                if current_profile:
                    for key, value in profile_state.items(): setattr(current_profile, key, value)
                else:
                    db.add(ontology_core.ObjectTypeProfile(object_type_id=resource_id, **profile_state))
        if state is None:
            if current:
                db.delete(current)
            ownership = _owned_resource(db, installation.target_project_id, resource_type, resource_id)
            if ownership:
                db.delete(ownership)
        elif current:
            for key, value in state.items(): setattr(current, key, value)
    installation.status = "ROLLED_BACK"
    installation.rolled_back_at = _now()
    previous = db.get(OntologyPackageInstallation, installation.previous_installation_id) if installation.previous_installation_id else None
    if previous:
        previous.status = "ACTIVE"
        for resource in previous.installed_resources or []:
            ownership = _owned_resource(db, previous.target_project_id, resource["resource_type"], resource["resource_id"])
            if ownership:
                ownership.installation_id = previous.id
                ownership.updated_at = _now()
    _audit(db, principal, "ontology.package.rolled_back", installation.id, {"package_id": installation.package_id, "version": installation.version, "restored_installation_id": previous.id if previous else None})
    db.commit()
    return {"id": installation.id, "status": installation.status, "rolled_back_at": installation.rolled_back_at, "restored_installation_id": previous.id if previous else None}


@router.get("/ontology-packages/{package_id}/versions/{version}/export")
def export_package_version(package_id: str, version: str, principal: Principal = Depends(require_permission("export")), db: Session = Depends(get_db)):
    package = _package(db, package_id)
    tenancy.assert_project_permission(db, principal, package.owning_project_id, "export")
    row = _version(db, package_id, version)
    return {"format": "ontology-package-v1", "package": _package_dict(db, package, principal), "version": _version_dict(row), "integrity": {"algorithm": "sha256", "checksum": row.checksum, "verified": row.checksum == _checksum(row.manifest or {})}}
