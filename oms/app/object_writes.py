"""One place every object write passes, so validation and history cannot diverge.

There were seven `ObjectInstance(...)` construction sites. Four validated their
properties and five recorded a change event, and the three that did neither were
the same three -- `ontology_core._apply_mutation_set`, `ontology_core._undo`, and
`domain_sentinel._upsert_object_instance`. One fact, three findings:

  * An object created by executing an ActionType was never validated against its
    own type, so a `create-object` mutation could write any shape at all.
  * Objects created down those paths are invisible to every temporal read, not
    stale -- `_query_source` in temporal mode reads `object_change_events` and
    never touches `object_instances`, so an object with no change event does not
    exist as far as any as-of query is concerned.
  * `validate_object_properties` read `models.ObjectType.properties`, while
    property edits are written to `ObjectTypeProfile.properties` once a profile
    exists. The two agree at creation and diverge on the first edit, so a
    property added later with `required=true` was never enforced.

The third is why validation belongs here rather than at each site: the live schema
takes a resolution step, and nine modules already do it correctly while the
validator was the one that did not.

Nothing in this module decides policy. It validates against the resolved schema,
writes the row, and records the change with its actor, source and evidence -- the
same sequence `POST /objects` already performed, made available to the paths that
did not perform it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models


def _now() -> int:
    from .runtime import now_ts

    return now_ts()


def resolved_schema(db: Session, object_type: models.ObjectType) -> Dict[str, Any]:
    """The schema as it stands now, from the profile when one exists.

    Delegates to `ontology_runtime_v1._property_specs`, which is the resolution
    `ontology_health`, `pipeline_builder_ops` and the typed query path all already
    use. Duplicating it here is how the two stores drifted apart in the first
    place.
    """
    from . import ontology_runtime_v1

    specs, _profile = ontology_runtime_v1._property_specs(db, object_type)
    return specs


def validate(db: Session, object_type: models.ObjectType,
             properties: Dict[str, Any]) -> List[str]:
    from .runtime import validate_object_properties

    return validate_object_properties(object_type, properties or {},
                                      schema=resolved_schema(db, object_type))


def _object_type(db: Session, object_type_id: str) -> Optional[models.ObjectType]:
    return db.get(models.ObjectType, object_type_id)


def create_object(
    db: Session,
    *,
    object_id: str,
    object_type_id: str,
    project_id: str,
    properties: Dict[str, Any],
    actor: str,
    event_type: str,
    source_type: str,
    source_id: Optional[str] = None,
    source_asset_id: Optional[str] = None,
    lineage: Optional[Dict[str, Any]] = None,
    evidence: Optional[Dict[str, Any]] = None,
    now: Optional[int] = None,
    object_type: Optional[models.ObjectType] = None,
) -> models.ObjectInstance:
    """Create one object, validated against its live schema, with its history."""
    stamp = now if now is not None else _now()
    declared = object_type if object_type is not None else _object_type(db, object_type_id)

    if declared is not None:
        errors = validate(db, declared, properties or {})
        if errors:
            raise HTTPException(status_code=422, detail=errors)

    instance = models.ObjectInstance(
        id=object_id,
        project_id=project_id,
        object_type_id=object_type_id,
        properties=properties or {},
        source_asset_id=source_asset_id,
        lineage=lineage or {},
        created_at=stamp,
        updated_at=stamp,
    )
    db.add(instance)
    _record(db, instance, before_state={}, event_type=event_type, actor=actor,
            source_type=source_type, source_id=source_id, evidence=evidence)
    return instance


def update_object(
    db: Session,
    instance: models.ObjectInstance,
    *,
    properties: Dict[str, Any],
    actor: str,
    event_type: str,
    source_type: str,
    source_id: Optional[str] = None,
    lineage: Optional[Dict[str, Any]] = None,
    evidence: Optional[Dict[str, Any]] = None,
    now: Optional[int] = None,
    merge: bool = True,
) -> Tuple[models.ObjectInstance, Dict[str, Any]]:
    """Apply a property change, validated, with its history. Returns the before-state.

    `merge` is not a policy switch: the callers genuinely differ. An action
    mutation sets named keys and leaves the rest, while a pipeline hydration
    replaces the row. Both need the same validation and the same change event,
    which is what this exists to guarantee.
    """
    stamp = now if now is not None else _now()
    before = dict(instance.properties or {})
    after = {**before, **(properties or {})} if merge else dict(properties or {})

    declared = _object_type(db, instance.object_type_id)
    if declared is not None:
        errors = validate(db, declared, after)
        if errors:
            raise HTTPException(status_code=422, detail=errors)

    instance.properties = after
    if lineage:
        instance.lineage = {**(instance.lineage or {}), **lineage}
    instance.updated_at = stamp

    _record(db, instance, before_state=before, event_type=event_type, actor=actor,
            source_type=source_type, source_id=source_id, evidence=evidence)
    return instance, before


def _record(db: Session, instance: models.ObjectInstance, *, before_state: Dict[str, Any],
            event_type: str, actor: str, source_type: str,
            source_id: Optional[str], evidence: Optional[Dict[str, Any]]) -> None:
    """Append the change event, and the snapshot the decision plane reads.

    Both are best-effort against a partial schema, the way the change recorder
    already is: compatibility routers construct a subset of the tables on
    purpose, and a write that fails because the history table is absent would
    break them for a record nothing in that configuration reads.
    """
    from . import ontology_runtime_v1

    ontology_runtime_v1.record_object_change(
        db, instance,
        before_state=before_state,
        event_type=event_type,
        actor=actor,
        source_type=source_type,
        source_id=source_id,
        evidence=evidence or {},
    )
    try:
        from . import decision_intelligence

        decision_intelligence.record_object_snapshot(
            db, instance, event_type=event_type, actor=actor,
            source_type=source_type, source_id=source_id,
        )
    except Exception:
        # The snapshot is a read model. Losing it must not lose the write or the
        # change event, which are the record of what happened.
        pass
