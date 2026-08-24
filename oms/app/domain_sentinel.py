import hashlib
import re
from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from . import models, object_writes
from .runtime import create_audit_log, extract_document_intelligence, now_ts


SENTINEL_OBJECT_TYPES = [
    "sentinel_case",
    "sentinel_evidence_document",
    "sentinel_observation",
    "sentinel_entity",
    "sentinel_location",
    "sentinel_event",
    "sentinel_task",
    "sentinel_finding",
    "sentinel_decision",
    "sentinel_report",
]


def _resource_summary(resource_type: str, resource_id: str, action: str) -> Dict[str, str]:
    return {"resource_type": resource_type, "id": resource_id, "action": action}


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _upsert_object_type(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    properties: Dict[str, Any],
) -> Dict[str, str]:
    existing = db.query(models.ObjectType).filter(models.ObjectType.id == id).first()
    if existing:
        existing.display_name = display_name
        existing.description = description
        existing.properties = properties
        existing.updated_at = now_ts()
        return _resource_summary("object_type", id, "updated")

    db.add(models.ObjectType(
        id=id,
        display_name=display_name,
        description=description,
        properties=properties,
        created_at=now_ts(),
        updated_at=now_ts(),
    ))
    return _resource_summary("object_type", id, "created")


def _upsert_link_type(
    db: Session,
    *,
    id: str,
    display_name: str,
    source_object_type_id: str,
    target_object_type_id: str,
    cardinality: str = "MANY_TO_MANY",
) -> Dict[str, str]:
    existing = db.query(models.LinkType).filter(models.LinkType.id == id).first()
    payload = {
        "display_name": display_name,
        "source_object_type_id": source_object_type_id,
        "target_object_type_id": target_object_type_id,
        "cardinality": cardinality,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        return _resource_summary("link_type", id, "updated")

    db.add(models.LinkType(id=id, **payload))
    return _resource_summary("link_type", id, "created")


def _upsert_action_type(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    parameters: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, str]:
    existing = db.query(models.ActionType).filter(models.ActionType.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "parameters": parameters,
        "rules": rules,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        return _resource_summary("action_type", id, "updated")

    db.add(models.ActionType(id=id, **payload))
    return _resource_summary("action_type", id, "created")


def _upsert_agent(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    allowed_object_types: List[str],
    allowed_actions: List[str],
) -> Dict[str, str]:
    existing = db.query(models.AgentDefinition).filter(models.AgentDefinition.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "system_prompt": (
            "You are a lawful enterprise investigation copilot. Preserve provenance, avoid unsupported claims, "
            "surface missing evidence, and require human approval for sensitive operational actions."
        ),
        "allowed_object_types": allowed_object_types,
        "allowed_actions": allowed_actions,
        "model_endpoint_id": None,
        "approval_required": True,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = now_ts()
        return _resource_summary("agent", id, "updated")

    db.add(models.AgentDefinition(id=id, **payload, created_at=now_ts(), updated_at=now_ts()))
    return _resource_summary("agent", id, "created")


def _upsert_eval_suite(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    target_agent_id: str,
    cases: List[Dict[str, Any]],
) -> Dict[str, str]:
    existing = db.query(models.EvalSuite).filter(models.EvalSuite.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "target_agent_id": target_agent_id,
        "cases": cases,
        "criteria": {},
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = now_ts()
        return _resource_summary("eval_suite", id, "updated")

    db.add(models.EvalSuite(id=id, **payload, created_at=now_ts(), updated_at=now_ts()))
    return _resource_summary("eval_suite", id, "created")


# The project every Sentinel object has always been written into, by omission.
DEFAULT_PROJECT_ID = "default"


def _object_payload(obj: models.ObjectInstance) -> Dict[str, Any]:
    return {
        "id": obj.id,
        "object_type_id": obj.object_type_id,
        "properties": obj.properties or {},
        "lineage": obj.lineage or {},
    }


def _link_payload(link: models.LinkInstance) -> Dict[str, Any]:
    return {
        "id": link.id,
        "link_type_id": link.link_type_id,
        "source_object_id": link.source_object_id,
        "target_object_id": link.target_object_id,
        "properties": link.properties or {},
    }


def _upsert_object_instance(
    db: Session,
    *,
    id: str,
    object_type_id: str,
    properties: Dict[str, Any],
    actor: str,
    lineage: Optional[Dict[str, Any]] = None,
) -> models.ObjectInstance:
    existing = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == id).first()
    if existing:
        existing.object_type_id = object_type_id
        updated, _before = object_writes.update_object(
            db, existing,
            properties=properties,
            actor=actor,
            event_type="ontology.object.updated",
            source_type="domain_sentinel",
            source_id=id,
            lineage=lineage or {},
        )
        return updated

    return object_writes.create_object(
        db,
        object_id=id,
        object_type_id=object_type_id,
        # This module never set project_id, so every object it creates has always
        # landed in the column default. Passing it explicitly changes nothing and
        # stops it being an accident: a Sentinel case is readable by anyone with
        # `view` on `default`, and that is a tenancy question this module cannot
        # answer on its own.
        project_id=DEFAULT_PROJECT_ID,
        properties=properties,
        actor=actor,
        event_type="ontology.object.created",
        source_type="domain_sentinel",
        source_id=id,
        lineage=lineage or {"created_by": actor},
    )


def _upsert_link_instance(
    db: Session,
    *,
    id: str,
    link_type_id: str,
    source_object_id: str,
    target_object_id: str,
    actor: str,
    confidence: float = 1.0,
    source_id: Optional[str] = None,
    extraction_method: str = "manual",
    properties: Optional[Dict[str, Any]] = None,
) -> models.LinkInstance:
    provenance = {
        "confidence": confidence,
        "source_id": source_id,
        "extraction_method": extraction_method,
        "created_by": actor,
        "created_at": now_ts(),
    }
    payload = {**provenance, **(properties or {})}
    existing = db.query(models.LinkInstance).filter(models.LinkInstance.id == id).first()
    if existing:
        existing.properties = {**(existing.properties or {}), **payload}
        return existing

    link = models.LinkInstance(
        id=id,
        link_type_id=link_type_id,
        source_object_id=source_object_id,
        target_object_id=target_object_id,
        properties=payload,
        created_at=now_ts(),
    )
    db.add(link)
    return link


def bootstrap_sentinel_operations_graph(db: Session, *, actor: str = "system") -> Dict[str, Any]:
    resources: List[Dict[str, str]] = []

    object_specs = [
        ("sentinel_case", "Case", "Governed investigation or incident-response workspace.", {
            "title": {"type": "string", "required": True},
            "description": {"type": "string"},
            "status": {"type": "string", "required": True},
            "owner": {"type": "string"},
            "sensitivity": {"type": "string"},
        }),
        ("sentinel_evidence_document", "Evidence Document", "Document, note, report, or source record attached to a case.", {
            "title": {"type": "string", "required": True},
            "text": {"type": "string", "required": True},
            "source_uri": {"type": "string"},
            "source_type": {"type": "string"},
            "case_id": {"type": "string", "required": True},
            "summary": {"type": "string"},
            "sensitivity": {"type": "string"},
            "captured_at": {"type": "integer"},
        }),
        ("sentinel_observation", "Observation", "Analyst or extracted observation tied to evidence.", {
            "title": {"type": "string", "required": True},
            "text": {"type": "string"},
            "case_id": {"type": "string", "required": True},
            "source_evidence_id": {"type": "string"},
            "observed_at": {"type": "integer"},
        }),
        ("sentinel_entity", "Entity", "Person, organization, asset, account, device, or other named item.", {
            "name": {"type": "string", "required": True},
            "entity_type": {"type": "string", "required": True},
            "normalized_value": {"type": "string"},
            "sensitivity": {"type": "string"},
        }),
        ("sentinel_location", "Location", "Place or site relevant to a case.", {
            "name": {"type": "string", "required": True},
            "address": {"type": "string"},
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "geometry": {"type": "geometry"},
        }),
        ("sentinel_event", "Event", "Time-bound incident or operational event.", {
            "title": {"type": "string", "required": True},
            "case_id": {"type": "string", "required": True},
            "description": {"type": "string"},
            "event_time": {"type": "integer"},
            "geometry": {"type": "geometry"},
        }),
        ("sentinel_task", "Task", "Analyst task or operational next step.", {
            "title": {"type": "string", "required": True},
            "case_id": {"type": "string", "required": True},
            "description": {"type": "string"},
            "priority": {"type": "string"},
            "status": {"type": "string", "required": True},
            "assignee": {"type": "string"},
        }),
        ("sentinel_finding", "Finding", "Evidence-backed analytic finding.", {
            "title": {"type": "string", "required": True},
            "case_id": {"type": "string", "required": True},
            "summary": {"type": "string"},
            "confidence": {"type": "number"},
            "status": {"type": "string", "required": True},
        }),
        ("sentinel_decision", "Decision", "Human decision based on findings and evidence.", {
            "title": {"type": "string", "required": True},
            "case_id": {"type": "string", "required": True},
            "rationale": {"type": "string"},
            "status": {"type": "string", "required": True},
        }),
        ("sentinel_report", "Report", "Draft or approved case report.", {
            "title": {"type": "string", "required": True},
            "case_id": {"type": "string", "required": True},
            "summary": {"type": "string"},
            "status": {"type": "string", "required": True},
        }),
    ]
    for id, display_name, description, properties in object_specs:
        resources.append(_upsert_object_type(
            db,
            id=id,
            display_name=display_name,
            description=description,
            properties=properties,
        ))

    link_specs = [
        ("case_contains_evidence", "Case Contains Evidence", "sentinel_case", "sentinel_evidence_document"),
        ("case_has_task", "Case Has Task", "sentinel_case", "sentinel_task"),
        ("case_has_finding", "Case Has Finding", "sentinel_case", "sentinel_finding"),
        ("case_has_decision", "Case Has Decision", "sentinel_case", "sentinel_decision"),
        ("case_has_report", "Case Has Report", "sentinel_case", "sentinel_report"),
        ("case_has_observation", "Case Has Observation", "sentinel_case", "sentinel_observation"),
        ("case_has_event", "Case Has Event", "sentinel_case", "sentinel_event"),
        ("evidence_mentions_entity", "Evidence Mentions Entity", "sentinel_evidence_document", "sentinel_entity"),
        ("evidence_supports_observation", "Evidence Supports Observation", "sentinel_evidence_document", "sentinel_observation"),
        ("observation_supports_finding", "Observation Supports Finding", "sentinel_observation", "sentinel_finding"),
        ("finding_supports_decision", "Finding Supports Decision", "sentinel_finding", "sentinel_decision"),
        ("event_occurred_at_location", "Event Occurred At Location", "sentinel_event", "sentinel_location"),
        ("entity_associated_with_entity", "Entity Associated With Entity", "sentinel_entity", "sentinel_entity"),
    ]
    for id, display_name, source, target in link_specs:
        resources.append(_upsert_link_type(
            db,
            id=id,
            display_name=display_name,
            source_object_type_id=source,
            target_object_type_id=target,
        ))

    resources.extend([
        _upsert_action_type(
            db,
            id="publish_sentinel_report",
            display_name="Publish Sentinel Report",
            description="Publish a case report after review.",
            parameters={
                "report_id": {"type": "string", "required": True},
                "approval_note": {"type": "string", "required": True},
            },
            rules={
                "requires_approval": True,
                "risk_level": "high",
                "object_mutations": [
                    {
                        "object_type_id": "sentinel_report",
                        "object_id_param": "report_id",
                        "set": {"status": {"value": "PUBLISHED"}, "summary": "$approval_note"},
                    }
                ],
            },
        ),
        _upsert_action_type(
            db,
            id="close_sentinel_case",
            display_name="Close Sentinel Case",
            description="Close a case after analyst review.",
            parameters={
                "case_id": {"type": "string", "required": True},
                "resolution": {"type": "string", "required": True},
            },
            rules={
                "requires_approval": True,
                "risk_level": "high",
                "object_mutations": [
                    {
                        "object_type_id": "sentinel_case",
                        "object_id_param": "case_id",
                        "set": {"status": {"value": "CLOSED"}, "description": "$resolution"},
                    }
                ],
            },
        ),
    ])

    resources.extend([
        _upsert_agent(
            db,
            id="sentinel_analyst_agent",
            display_name="Sentinel Analyst Agent",
            description="Lawful investigation copilot for case summaries, missing evidence, and next steps.",
            allowed_object_types=SENTINEL_OBJECT_TYPES,
            allowed_actions=["publish_sentinel_report", "close_sentinel_case"],
        ),
        _upsert_eval_suite(
            db,
            id="sentinel_analyst_eval",
            display_name="Sentinel Analyst Eval",
            description="Checks that the Sentinel agent retrieves case evidence and proposes governed report publication.",
            target_agent_id="sentinel_analyst_agent",
            cases=[
                {
                    "id": "publish_report_case",
                    "prompt": "Please publish sentinel report after review",
                    "expected_actions": ["publish_sentinel_report"],
                    "expected_context_object_types": ["sentinel_case"],
                }
            ],
        ),
    ])

    create_audit_log(
        db,
        actor=actor,
        event_type="domain.sentinel.bootstrapped",
        subject_type="domain",
        subject_id="sentinel_operations_graph",
        payload={"resources": resources},
    )
    db.commit()

    return {
        "domain": "sentinel_operations_graph",
        "resources": resources,
        "agent_id": "sentinel_analyst_agent",
        "eval_suite_id": "sentinel_analyst_eval",
        "object_types": SENTINEL_OBJECT_TYPES,
    }


def create_case(
    db: Session,
    *,
    title: str,
    description: str = "",
    owner: str = "analyst",
    sensitivity: str = "internal",
    status: str = "OPEN",
    case_id: Optional[str] = None,
    actor: str = "analyst",
) -> Dict[str, Any]:
    case_id = case_id or _stable_id("case", f"{title}:{owner}:{now_ts()}")
    obj = _upsert_object_instance(
        db,
        id=case_id,
        object_type_id="sentinel_case",
        actor=actor,
        properties={
            "title": title,
            "description": description,
            "owner": owner,
            "sensitivity": sensitivity,
            "status": status,
        },
        lineage={"created_by": actor, "created_at": now_ts()},
    )
    create_audit_log(
        db,
        actor=actor,
        event_type="sentinel.case.created",
        subject_type="sentinel_case",
        subject_id=case_id,
        payload={"title": title, "sensitivity": sensitivity},
    )
    db.commit()
    return _object_payload(obj)


def _entity_mentions_from_extraction(extraction: Dict[str, Any]) -> List[Tuple[str, str]]:
    mentions: List[Tuple[str, str]] = []
    for entity_type, values in (extraction.get("entities") or {}).items():
        for value in values:
            mentions.append((entity_type[:-1] if entity_type.endswith("s") else entity_type, value))
    for field, value in (extraction.get("fields") or {}).items():
        if value:
            mentions.append((field, str(value)))
    return mentions


def ingest_evidence(
    db: Session,
    *,
    case_id: str,
    title: str,
    text: str,
    source_uri: Optional[str] = None,
    source_type: str = "document",
    sensitivity: str = "internal",
    extraction_schema: Optional[Dict[str, Any]] = None,
    evidence_id: Optional[str] = None,
    actor: str = "analyst",
) -> Dict[str, Any]:
    case = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == case_id).first()
    if not case or case.object_type_id != "sentinel_case":
        raise ValueError(f"Sentinel case '{case_id}' not found")

    extraction = extract_document_intelligence(text, extraction_schema or {})
    evidence_id = evidence_id or _stable_id("evidence", f"{case_id}:{title}:{text[:80]}")
    evidence = _upsert_object_instance(
        db,
        id=evidence_id,
        object_type_id="sentinel_evidence_document",
        actor=actor,
        properties={
            "title": title,
            "text": text,
            "source_uri": source_uri,
            "source_type": source_type,
            "case_id": case_id,
            "summary": extraction["summary"],
            "sensitivity": sensitivity,
            "captured_at": now_ts(),
        },
        lineage={"created_by": actor, "extraction_method": "document_intelligence", "created_at": now_ts()},
    )
    _upsert_link_instance(
        db,
        id=f"case_contains_evidence:{case_id}:{evidence_id}",
        link_type_id="case_contains_evidence",
        source_object_id=case_id,
        target_object_id=evidence_id,
        actor=actor,
        confidence=1.0,
        source_id=evidence_id,
        extraction_method="manual_attach",
    )

    created_entities = []
    for entity_type, value in _entity_mentions_from_extraction(extraction):
        entity_id = _stable_id("entity", f"{entity_type}:{value.lower()}")
        entity = _upsert_object_instance(
            db,
            id=entity_id,
            object_type_id="sentinel_entity",
            actor=actor,
            properties={
                "name": value,
                "entity_type": entity_type,
                "normalized_value": value.lower(),
                "sensitivity": sensitivity,
            },
            lineage={"source_evidence_id": evidence_id, "extraction_method": "document_intelligence"},
        )
        _upsert_link_instance(
            db,
            id=f"evidence_mentions_entity:{evidence_id}:{entity_id}",
            link_type_id="evidence_mentions_entity",
            source_object_id=evidence_id,
            target_object_id=entity_id,
            actor=actor,
            confidence=extraction.get("confidence", 0.5),
            source_id=evidence_id,
            extraction_method="document_intelligence",
        )
        created_entities.append(_object_payload(entity))

    observation_id = _stable_id("observation", f"{evidence_id}:{extraction['summary']}")
    observation = _upsert_object_instance(
        db,
        id=observation_id,
        object_type_id="sentinel_observation",
        actor=actor,
        properties={
            "title": f"Observation from {title}",
            "text": extraction["summary"],
            "case_id": case_id,
            "source_evidence_id": evidence_id,
            "observed_at": now_ts(),
        },
        lineage={"source_evidence_id": evidence_id, "extraction_method": "document_intelligence"},
    )
    _upsert_link_instance(
        db,
        id=f"case_has_observation:{case_id}:{observation_id}",
        link_type_id="case_has_observation",
        source_object_id=case_id,
        target_object_id=observation_id,
        actor=actor,
        confidence=extraction.get("confidence", 0.5),
        source_id=evidence_id,
        extraction_method="document_intelligence",
    )
    _upsert_link_instance(
        db,
        id=f"evidence_supports_observation:{evidence_id}:{observation_id}",
        link_type_id="evidence_supports_observation",
        source_object_id=evidence_id,
        target_object_id=observation_id,
        actor=actor,
        confidence=extraction.get("confidence", 0.5),
        source_id=evidence_id,
        extraction_method="document_intelligence",
    )

    create_audit_log(
        db,
        actor=actor,
        event_type="sentinel.evidence.ingested",
        subject_type="sentinel_evidence_document",
        subject_id=evidence_id,
        payload={"case_id": case_id, "entity_count": len(created_entities), "confidence": extraction["confidence"]},
    )
    db.commit()
    return {
        "evidence": _object_payload(evidence),
        "entities": created_entities,
        "observation": _object_payload(observation),
        "extraction": extraction,
    }


def create_case_task(
    db: Session,
    *,
    case_id: str,
    title: str,
    description: str = "",
    priority: str = "normal",
    status: str = "OPEN",
    assignee: Optional[str] = None,
    task_id: Optional[str] = None,
    actor: str = "analyst",
) -> Dict[str, Any]:
    task_id = task_id or _stable_id("task", f"{case_id}:{title}:{now_ts()}")
    task = _upsert_object_instance(
        db,
        id=task_id,
        object_type_id="sentinel_task",
        actor=actor,
        properties={
            "title": title,
            "description": description,
            "priority": priority,
            "status": status,
            "assignee": assignee,
            "case_id": case_id,
        },
    )
    _upsert_link_instance(
        db,
        id=f"case_has_task:{case_id}:{task_id}",
        link_type_id="case_has_task",
        source_object_id=case_id,
        target_object_id=task_id,
        actor=actor,
        source_id=case_id,
    )
    create_audit_log(db, actor=actor, event_type="sentinel.task.created", subject_type="sentinel_task", subject_id=task_id, payload={"case_id": case_id})
    db.commit()
    return _object_payload(task)


def create_case_finding(
    db: Session,
    *,
    case_id: str,
    title: str,
    summary: str,
    confidence: float = 0.5,
    status: str = "DRAFT",
    finding_id: Optional[str] = None,
    actor: str = "analyst",
) -> Dict[str, Any]:
    finding_id = finding_id or _stable_id("finding", f"{case_id}:{title}:{now_ts()}")
    finding = _upsert_object_instance(
        db,
        id=finding_id,
        object_type_id="sentinel_finding",
        actor=actor,
        properties={"title": title, "summary": summary, "confidence": confidence, "status": status, "case_id": case_id},
    )
    _upsert_link_instance(
        db,
        id=f"case_has_finding:{case_id}:{finding_id}",
        link_type_id="case_has_finding",
        source_object_id=case_id,
        target_object_id=finding_id,
        actor=actor,
        confidence=confidence,
        source_id=case_id,
    )
    create_audit_log(db, actor=actor, event_type="sentinel.finding.created", subject_type="sentinel_finding", subject_id=finding_id, payload={"case_id": case_id, "confidence": confidence})
    db.commit()
    return _object_payload(finding)


def draft_case_report(db: Session, *, case_id: str, actor: str = "analyst") -> Dict[str, Any]:
    summary = summarize_case(db, case_id=case_id)
    report_id = _stable_id("report", f"{case_id}:{summary['summary']}")
    report = _upsert_object_instance(
        db,
        id=report_id,
        object_type_id="sentinel_report",
        actor=actor,
        properties={
            "title": f"Report for {summary['case'].get('title', case_id)}",
            "case_id": case_id,
            "summary": summary["summary"],
            "status": "DRAFT",
        },
    )
    _upsert_link_instance(
        db,
        id=f"case_has_report:{case_id}:{report_id}",
        link_type_id="case_has_report",
        source_object_id=case_id,
        target_object_id=report_id,
        actor=actor,
        confidence=1.0,
        source_id=case_id,
    )
    create_audit_log(db, actor=actor, event_type="sentinel.report.drafted", subject_type="sentinel_report", subject_id=report_id, payload={"case_id": case_id})
    db.commit()
    return _object_payload(report)


def _all_links(db: Session) -> List[models.LinkInstance]:
    return db.query(models.LinkInstance).all()


def _adjacency(links: Iterable[models.LinkInstance]) -> Dict[str, List[Tuple[str, models.LinkInstance]]]:
    adjacency: Dict[str, List[Tuple[str, models.LinkInstance]]] = {}
    for link in links:
        adjacency.setdefault(link.source_object_id, []).append((link.target_object_id, link))
        adjacency.setdefault(link.target_object_id, []).append((link.source_object_id, link))
    return adjacency


def graph_neighbors(db: Session, *, object_id: str, depth: int = 1) -> Dict[str, Any]:
    depth = max(0, min(depth, 5))
    links = _all_links(db)
    adjacency = _adjacency(links)
    seen: Set[str] = {object_id}
    queue = deque([(object_id, 0)])
    edge_ids: Set[str] = set()

    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for neighbor, link in adjacency.get(current, []):
            edge_ids.add(link.id)
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, current_depth + 1))

    nodes = db.query(models.ObjectInstance).filter(models.ObjectInstance.id.in_(seen)).all() if seen else []
    selected_links = [link for link in links if link.id in edge_ids]
    return {"nodes": [_object_payload(node) for node in nodes], "edges": [_link_payload(link) for link in selected_links]}


def case_subgraph(db: Session, *, case_id: str, depth: int = 2) -> Dict[str, Any]:
    return graph_neighbors(db, object_id=case_id, depth=depth)


def shortest_path(db: Session, *, source_id: str, target_id: str, max_depth: int = 6) -> Dict[str, Any]:
    links = _all_links(db)
    adjacency = _adjacency(links)
    queue = deque([(source_id, [source_id], [])])
    seen = {source_id}
    max_depth = max(1, min(max_depth, 12))

    while queue:
        current, path, edge_path = queue.popleft()
        if current == target_id:
            nodes = db.query(models.ObjectInstance).filter(models.ObjectInstance.id.in_(path)).all()
            node_map = {node.id: _object_payload(node) for node in nodes}
            return {
                "found": True,
                "object_ids": path,
                "nodes": [node_map[item] for item in path if item in node_map],
                "edges": [_link_payload(edge) for edge in edge_path],
            }
        if len(path) > max_depth:
            continue
        for neighbor, link in adjacency.get(current, []):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append((neighbor, path + [neighbor], edge_path + [link]))

    return {"found": False, "object_ids": [], "nodes": [], "edges": []}


def case_timeline(db: Session, *, case_id: str) -> Dict[str, Any]:
    subgraph = case_subgraph(db, case_id=case_id, depth=2)
    items = []
    for node in subgraph["nodes"]:
        props = node["properties"]
        timestamp = props.get("event_time") or props.get("observed_at") or props.get("captured_at")
        if not timestamp:
            continue
        items.append({
            "timestamp": timestamp,
            "object_id": node["id"],
            "object_type_id": node["object_type_id"],
            "title": props.get("title") or props.get("name") or node["id"],
            "summary": props.get("summary") or props.get("text") or props.get("description"),
        })
    return {"case_id": case_id, "timeline": sorted(items, key=lambda item: item["timestamp"])}


def case_provenance(db: Session, *, case_id: str) -> Dict[str, Any]:
    subgraph = case_subgraph(db, case_id=case_id, depth=2)
    provenance = []
    for edge in subgraph["edges"]:
        props = edge["properties"]
        provenance.append({
            "link_id": edge["id"],
            "link_type_id": edge["link_type_id"],
            "source_object_id": edge["source_object_id"],
            "target_object_id": edge["target_object_id"],
            "confidence": props.get("confidence"),
            "source_id": props.get("source_id"),
            "extraction_method": props.get("extraction_method"),
            "created_by": props.get("created_by"),
            "created_at": props.get("created_at"),
        })
    return {"case_id": case_id, "provenance": provenance}


def summarize_case(db: Session, *, case_id: str) -> Dict[str, Any]:
    case = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == case_id).first()
    if not case:
        raise ValueError(f"Case '{case_id}' not found")
    subgraph = case_subgraph(db, case_id=case_id, depth=2)
    counts: Dict[str, int] = {}
    for node in subgraph["nodes"]:
        counts[node["object_type_id"]] = counts.get(node["object_type_id"], 0) + 1
    evidence_titles = [
        node["properties"].get("title")
        for node in subgraph["nodes"]
        if node["object_type_id"] == "sentinel_evidence_document"
    ]
    entity_names = [
        node["properties"].get("name")
        for node in subgraph["nodes"]
        if node["object_type_id"] == "sentinel_entity"
    ]
    title = (case.properties or {}).get("title", case_id)
    summary = (
        f"Case '{title}' contains {counts.get('sentinel_evidence_document', 0)} evidence item(s), "
        f"{counts.get('sentinel_entity', 0)} extracted entity/entities, and "
        f"{counts.get('sentinel_task', 0)} task(s)."
    )
    return {
        "case": case.properties or {},
        "summary": summary,
        "evidence_titles": [item for item in evidence_titles if item],
        "entity_names": [item for item in entity_names if item],
        "counts": counts,
    }


def missing_evidence(db: Session, *, case_id: str) -> Dict[str, Any]:
    subgraph = case_subgraph(db, case_id=case_id, depth=2)
    object_types = {node["object_type_id"] for node in subgraph["nodes"]}
    missing = []
    if "sentinel_evidence_document" not in object_types:
        missing.append("Attach at least one source evidence document.")
    if "sentinel_entity" not in object_types:
        missing.append("Extract or manually add entities mentioned by evidence.")
    if "sentinel_finding" not in object_types:
        missing.append("Create at least one evidence-backed finding before final decisions.")
    if "sentinel_task" not in object_types:
        missing.append("Create analyst tasks for unresolved questions.")
    return {"case_id": case_id, "missing": missing, "complete": not missing}


def suggest_next_steps(db: Session, *, case_id: str) -> Dict[str, Any]:
    gaps = missing_evidence(db, case_id=case_id)["missing"]
    suggestions = [
        {"title": gap, "priority": "high" if "finding" in gap.lower() else "normal"}
        for gap in gaps
    ]
    if not suggestions:
        suggestions = [{"title": "Draft case report for review", "priority": "normal"}]
    return {"case_id": case_id, "suggestions": suggestions}


def sentinel_summary(db: Session) -> Dict[str, Any]:
    counts = {
        object_type_id: db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == object_type_id
        ).count()
        for object_type_id in SENTINEL_OBJECT_TYPES
    }
    open_cases = [
        {
            "id": item.id,
            "title": (item.properties or {}).get("title"),
            "status": (item.properties or {}).get("status"),
            "sensitivity": (item.properties or {}).get("sensitivity"),
        }
        for item in db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == "sentinel_case"
        ).all()
        if (item.properties or {}).get("status") != "CLOSED"
    ]
    return {
        "domain": "sentinel_operations_graph",
        "object_counts": counts,
        "open_cases": open_cases,
        "agent_id": "sentinel_analyst_agent",
        "eval_suite_id": "sentinel_analyst_eval",
    }
