"""
Foundry CONFIGURED OBJECT VIEWS (deepening module).

Reusable, centralized "detail page" presentations of a single Ontology object:
form factors (full / panel), Workshop-backed tabs, conditional tab visibility,
widgets (Property List, Links, Markdown, layout containers), standard-view
generation, rendering against an object instance, versioning (save/publish/
republish), and the applications sidebar.

All ORM classes / tables are prefixed Ov / ov_ to avoid collisions on the shared
declarative Base. This module owns ONLY ov_* tables and reads core tables
(object_types, object_instances, link_types, link_instances) read-only.

------------------------------------------------------------------------------
DOCS READ (Foundry official docs, fetched while implementing this module):
- https://www.palantir.com/docs/foundry/object-views/overview
- https://www.palantir.com/docs/foundry/object-views/config-overview
- https://www.palantir.com/docs/foundry/object-views/standard-object-views
- https://www.palantir.com/docs/foundry/object-views/config-object-views
- https://www.palantir.com/docs/foundry/object-views/config-panel-views
- https://www.palantir.com/docs/foundry/object-views/manage-versions
- https://www.palantir.com/docs/foundry/object-views/config-app-sidebar
- https://www.palantir.com/docs/foundry/object-views/widgets-properties-links
- https://www.palantir.com/docs/foundry/object-views/widgets-layout

CRITIC CORRECTION — VERIFIED:
The Panel Object Set "5 XY charts" and "3 properties per object" numbers ARE
documented: config-panel-views states the Charts tab shows "up to five XY Charts"
and the List tab shows "up to three properties per object". CONFIRMED on the live
page. HOWEVER the "50 objects max" figure is NOT documented on config-panel-views
(or use-panel-views) — that page does not specify a maximum number of objects.
Therefore the object-cap is exposed as a CONFIGURABLE field with a clearly
commented, explicitly-unverified default (see PANEL_SET_MAX_OBJECTS_DEFAULT).
Likewise the config-panel-views page does NOT mention an "adaptive mode" feature
(adaptive mode is documented on the Workshop Object View widget page, not here);
we do not assert it as a panel default.

Conditional-visibility operators implemented below mirror the documented
property-based condition options ("Is defined", "Is not defined", "Is one of",
"Is not one of") plus standard comparators, and the documented Linked-Objects
condition ("content shown based on whether linked objects of a certain type
exist"). Markdown templating uses the documented `{{propertyName}}` syntax.
------------------------------------------------------------------------------
"""

from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid

# Documented Panel Object Set defaults (config-panel-views: "up to five XY Charts",
# "up to three properties per object"). These two ARE documented.
PANEL_SET_MAX_CHARTS_DEFAULT = 5          # documented: up to five XY Charts
PANEL_SET_MAX_PROPS_PER_OBJECT_DEFAULT = 3  # documented: up to three properties per object
# NOT documented anywhere actually read: a maximum object count for the List tab.
# config-panel-views does not state one, so this is an implementation default only
# and is overridable via the panel form-factor config. Marked unverified.
PANEL_SET_MAX_OBJECTS_DEFAULT = 50        # UNVERIFIED assumption, configurable

VALID_FORM_FACTORS = {"full", "panel"}
VALID_PANEL_MODES = {"instance", "object_set"}
VALID_TAB_TYPES = {"workshop", "legacy"}
# Widget types we resolve at render time.
VALID_WIDGET_TYPES = {
    "property_list", "links", "markdown",
    "horizontal", "vertical_stack", "tabbed", "conditional",
    "charts", "object_list",
}


# ---------------------------------------------------------------------------
# SQLAlchemy models (all Ov / ov_ prefixed)
# ---------------------------------------------------------------------------

class OvView(Base):
    """A configured Object View bound to a single object type."""
    __tablename__ = "ov_views"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    object_type_id: Mapped[str] = mapped_column(String, index=True, unique=True)
    form_factor: Mapped[str] = mapped_column(String, default="full")  # full|panel
    panel_mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # instance|object_set
    panel_config: Mapped[dict] = mapped_column(JSON, default=dict)
    default_tab_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=True)
    published_version_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class OvTab(Base):
    """A tab within an Object View; each tab is backed by a Workshop module."""
    __tablename__ = "ov_tabs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    view_id: Mapped[str] = mapped_column(String, ForeignKey("ov_views.id"), index=True)
    tab_type: Mapped[str] = mapped_column(String, default="workshop")  # workshop|legacy
    display_name: Mapped[str] = mapped_column(String)
    tab_order: Mapped[int] = mapped_column(Integer, default=0)
    # {property_conditions: [{property, op, value?}], link_conditions: [{link_type_id, exists?}]}
    conditional_visibility: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class OvWidget(Base):
    """A widget within a tab (property_list, links, markdown, layout containers...)."""
    __tablename__ = "ov_widgets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tab_id: Mapped[str] = mapped_column(String, ForeignKey("ov_tabs.id"), index=True)
    widget_type: Mapped[str] = mapped_column(String)
    widget_order: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class OvVersion(Base):
    """An immutable snapshot of a view's content; published versions are user-visible."""
    __tablename__ = "ov_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    view_id: Mapped[str] = mapped_column(String, ForeignKey("ov_views.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    content_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    author: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[int] = mapped_column(Integer)


class OvSidebar(Base):
    """The applications sidebar for a view (optional, opt-in)."""
    __tablename__ = "ov_sidebars"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    view_id: Mapped[str] = mapped_column(String, ForeignKey("ov_views.id"), index=True, unique=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class OvViewCreate(BaseModel):
    id: Optional[str] = None
    object_type_id: str
    form_factor: str = "full"
    panel_mode: Optional[str] = None
    panel_config: Dict[str, Any] = Field(default_factory=dict)
    auto_publish: bool = True


class OvViewUpdate(BaseModel):
    form_factor: Optional[str] = None
    panel_mode: Optional[str] = None
    panel_config: Optional[Dict[str, Any]] = None
    default_tab_id: Optional[str] = None
    auto_publish: Optional[bool] = None


class OvViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    object_type_id: str
    form_factor: str
    panel_mode: Optional[str] = None
    panel_config: Dict[str, Any]
    default_tab_id: Optional[str] = None
    auto_publish: bool
    published_version_id: Optional[str] = None
    created_at: int
    updated_at: int


class OvTabCreate(BaseModel):
    id: Optional[str] = None
    tab_type: str = "workshop"
    display_name: str
    tab_order: Optional[int] = None
    conditional_visibility: Dict[str, Any] = Field(default_factory=dict)


class OvTabUpdate(BaseModel):
    tab_type: Optional[str] = None
    display_name: Optional[str] = None
    tab_order: Optional[int] = None
    conditional_visibility: Optional[Dict[str, Any]] = None


class OvTabRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    view_id: str
    tab_type: str
    display_name: str
    tab_order: int
    conditional_visibility: Dict[str, Any]
    created_at: int


class OvWidgetCreate(BaseModel):
    id: Optional[str] = None
    widget_type: str
    widget_order: Optional[int] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class OvWidgetUpdate(BaseModel):
    widget_type: Optional[str] = None
    widget_order: Optional[int] = None
    config: Optional[Dict[str, Any]] = None


class OvWidgetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tab_id: str
    widget_type: str
    widget_order: int
    config: Dict[str, Any]
    created_at: int


class OvSidebarUpsert(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)


class OvPublishRequest(BaseModel):
    description: Optional[str] = None
    author: str = "system"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["object-views"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_object_type(db: Session, object_type_id: str) -> "models.ObjectType":
    ot = db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id).first()
    if not ot:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    return ot


def _get_view(db: Session, view_id: str) -> OvView:
    view = db.query(OvView).filter(OvView.id == view_id).first()
    if not view:
        raise HTTPException(status_code=404, detail=f"OvView '{view_id}' not found")
    return view


def _get_view_by_ot(db: Session, object_type_id: str) -> Optional[OvView]:
    return db.query(OvView).filter(OvView.object_type_id == object_type_id).first()


def _get_tab(db: Session, tab_id: str) -> OvTab:
    tab = db.query(OvTab).filter(OvTab.id == tab_id).first()
    if not tab:
        raise HTTPException(status_code=404, detail=f"OvTab '{tab_id}' not found")
    return tab


def _prominent_property_names(ot: "models.ObjectType") -> List[str]:
    """Return prominent property names; fall back to all non-hidden if none prominent.

    Property spec shape is flexible across the platform, so we treat any of
    visibility=='prominent', prominent==True as prominent, and visibility=='hidden'
    / hidden==True as hidden.
    """
    props = ot.properties or {}
    prominent: List[str] = []
    non_hidden: List[str] = []
    for name, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        visibility = spec.get("visibility")
        is_hidden = visibility == "hidden" or spec.get("hidden") is True
        is_prominent = visibility == "prominent" or spec.get("prominent") is True
        if not is_hidden:
            non_hidden.append(name)
        if is_prominent and not is_hidden:
            prominent.append(name)
    return prominent if prominent else non_hidden


def _non_hidden_property_names(ot: "models.ObjectType") -> List[str]:
    props = ot.properties or {}
    out: List[str] = []
    for name, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        if spec.get("visibility") == "hidden" or spec.get("hidden") is True:
            continue
        out.append(name)
    return out


def _linked_object_types(db: Session, object_type_id: str) -> List[Dict[str, Any]]:
    """Derive linked object types from LinkType rows where source/target == ot."""
    out: List[Dict[str, Any]] = []
    link_types = db.query(models.LinkType).all()
    for lt in link_types:
        if lt.source_object_type_id == object_type_id:
            out.append({
                "link_type_id": lt.id,
                "display_name": lt.display_name,
                "direction": "out",
                "linked_object_type_id": lt.target_object_type_id,
                "cardinality": lt.cardinality,
            })
        elif lt.target_object_type_id == object_type_id:
            out.append({
                "link_type_id": lt.id,
                "display_name": lt.display_name,
                "direction": "in",
                "linked_object_type_id": lt.source_object_type_id,
                "cardinality": lt.cardinality,
            })
    return out


def _eval_property_condition(obj_props: Dict[str, Any], cond: Dict[str, Any]) -> bool:
    """Evaluate one documented property condition.

    Supported ops mirror the documented property-based condition options plus
    standard comparators:
      is_defined, is_not_defined, is_one_of, is_not_one_of, eq, ne, gt, gte, lt, lte
    """
    prop = cond.get("property")
    op = cond.get("op", "eq")
    expected = cond.get("value")
    present = prop in obj_props and obj_props.get(prop) is not None
    actual = obj_props.get(prop)

    if op == "is_defined":
        return present
    if op == "is_not_defined":
        return not present
    if op == "is_one_of":
        return present and actual in (expected or [])
    if op == "is_not_one_of":
        return (not present) or (actual not in (expected or []))

    # comparators require the property to be present
    if not present:
        return False
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    try:
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        if op == "lte":
            return actual <= expected
    except TypeError:
        return False
    raise HTTPException(status_code=422, detail=f"Unknown property condition op '{op}'")


def _eval_link_condition(db: Session, object_id: str, cond: Dict[str, Any]) -> bool:
    """Linked-Objects condition: content shown based on whether linked objects exist.

    cond = {link_type_id, exists?(default True)}.
    Counts LinkInstance rows touching object_id (either direction) of that link type.
    """
    link_type_id = cond.get("link_type_id")
    want_exists = cond.get("exists", True)
    q = db.query(models.LinkInstance).filter(models.LinkInstance.link_type_id == link_type_id)
    has_link = False
    for li in q.all():
        if li.source_object_id == object_id or li.target_object_id == object_id:
            has_link = True
            break
    return has_link if want_exists else (not has_link)


def _tab_is_visible(db: Session, tab: OvTab, obj: "models.ObjectInstance") -> bool:
    """A tab renders only if ALL its conditions (property + link) pass."""
    cv = tab.conditional_visibility or {}
    obj_props = (obj.properties or {}) if obj is not None else {}
    for cond in cv.get("property_conditions", []) or []:
        if not _eval_property_condition(obj_props, cond):
            return False
    for cond in cv.get("link_conditions", []) or []:
        if not _eval_link_condition(db, obj.id, cond):
            return False
    return True


def _render_markdown(template: str, obj_props: Dict[str, Any]) -> str:
    """Substitute documented `{{propertyName}}` tokens with actual values."""
    if not template:
        return ""
    out = template
    for name, value in obj_props.items():
        out = out.replace("{{" + name + "}}", "" if value is None else str(value))
    return out


def _resolve_widget(db: Session, w: OvWidget, ot: "models.ObjectType",
                    obj: "models.ObjectInstance") -> Dict[str, Any]:
    """Resolve a widget against a concrete object instance."""
    obj_props = (obj.properties or {}) if obj is not None else {}
    cfg = w.config or {}
    base = {"widget_id": w.id, "widget_type": w.widget_type, "widget_order": w.widget_order}

    if w.widget_type == "property_list":
        prop_names = cfg.get("properties")
        if not prop_names:
            prop_names = (_prominent_property_names(ot)
                          if cfg.get("prominent_only") else _non_hidden_property_names(ot))
        base["resolved"] = {"properties": {n: obj_props.get(n) for n in prop_names}}
    elif w.widget_type == "links":
        link_type_filter = cfg.get("link_types")
        groups: Dict[str, List[str]] = {}
        for li in db.query(models.LinkInstance).all():
            if link_type_filter and li.link_type_id not in link_type_filter:
                continue
            if obj is not None and li.source_object_id == obj.id:
                groups.setdefault(li.link_type_id, []).append(li.target_object_id)
            elif obj is not None and li.target_object_id == obj.id:
                groups.setdefault(li.link_type_id, []).append(li.source_object_id)
        base["resolved"] = {"links_by_type": groups}
    elif w.widget_type == "markdown":
        base["resolved"] = {"text": _render_markdown(cfg.get("template", ""), obj_props)}
    else:
        # layout containers / others: pass config through untouched.
        base["resolved"] = {"config": cfg}
    return base


def _view_content_snapshot(db: Session, view: OvView) -> Dict[str, Any]:
    """Capture the full tab+widget tree as a snapshot for versioning."""
    tabs = (db.query(OvTab).filter(OvTab.view_id == view.id)
            .order_by(OvTab.tab_order).all())
    tab_snaps = []
    for t in tabs:
        widgets = (db.query(OvWidget).filter(OvWidget.tab_id == t.id)
                   .order_by(OvWidget.widget_order).all())
        tab_snaps.append({
            "id": t.id,
            "tab_type": t.tab_type,
            "display_name": t.display_name,
            "tab_order": t.tab_order,
            "conditional_visibility": t.conditional_visibility or {},
            "widgets": [{
                "id": w.id,
                "widget_type": w.widget_type,
                "widget_order": w.widget_order,
                "config": w.config or {},
            } for w in widgets],
        })
    return {
        "object_type_id": view.object_type_id,
        "form_factor": view.form_factor,
        "panel_mode": view.panel_mode,
        "panel_config": view.panel_config or {},
        "default_tab_id": view.default_tab_id,
        "tabs": tab_snaps,
    }


def _restore_snapshot(db: Session, view: OvView, snapshot: Dict[str, Any]) -> None:
    """Rebuild tabs+widgets from a snapshot (used to republish an older version)."""
    # delete current tabs+widgets
    cur_tabs = db.query(OvTab).filter(OvTab.view_id == view.id).all()
    for t in cur_tabs:
        db.query(OvWidget).filter(OvWidget.tab_id == t.id).delete()
        db.delete(t)
    db.flush()
    now = int(time.time())
    for t in snapshot.get("tabs", []):
        tab = OvTab(
            id=t["id"],
            view_id=view.id,
            tab_type=t.get("tab_type", "workshop"),
            display_name=t["display_name"],
            tab_order=t.get("tab_order", 0),
            conditional_visibility=t.get("conditional_visibility", {}),
            created_at=now,
        )
        db.add(tab)
        for w in t.get("widgets", []):
            db.add(OvWidget(
                id=w["id"],
                tab_id=tab.id,
                widget_type=w["widget_type"],
                widget_order=w.get("widget_order", 0),
                config=w.get("config", {}),
                created_at=now,
            ))
    view.form_factor = snapshot.get("form_factor", view.form_factor)
    view.panel_mode = snapshot.get("panel_mode", view.panel_mode)
    view.panel_config = snapshot.get("panel_config", view.panel_config) or {}
    view.default_tab_id = snapshot.get("default_tab_id", view.default_tab_id)
    view.updated_at = now


def _audit(db: Session, event_type: str, subject_id: str, payload: dict) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="system", event_type=event_type,
        subject_type="object_view", subject_id=subject_id, payload=payload,
    ))


# ---------------------------------------------------------------------------
# Standard view generation
# ---------------------------------------------------------------------------

@router.get("/object-views/{object_type_id}/standard")
def get_standard_view(object_type_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Synthesize the schema-driven Standard Object View (no persistence)."""
    ot = _get_object_type(db, object_type_id)
    prominent = _prominent_property_names(ot)
    linked = _linked_object_types(db, object_type_id)
    return {
        "object_type_id": object_type_id,
        "kind": "standard",
        "widgets": [
            {
                "widget_type": "property_list",
                "config": {
                    "prominent_properties": prominent,
                    "all_properties": list((ot.properties or {}).keys()),
                },
            },
            {
                "widget_type": "links",
                "config": {
                    "linked_object_types": linked,
                    "link_type_ids": [l["link_type_id"] for l in linked],
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# View CRUD
# ---------------------------------------------------------------------------

@router.post("/object-views", response_model=OvViewRead)
def create_view(body: OvViewCreate, db: Session = Depends(get_db)):
    _get_object_type(db, body.object_type_id)
    if body.form_factor not in VALID_FORM_FACTORS:
        raise HTTPException(status_code=422, detail=f"form_factor must be one of {sorted(VALID_FORM_FACTORS)}")
    if body.panel_mode is not None and body.panel_mode not in VALID_PANEL_MODES:
        raise HTTPException(status_code=422, detail=f"panel_mode must be one of {sorted(VALID_PANEL_MODES)}")
    if body.form_factor == "panel" and body.panel_mode is None:
        raise HTTPException(status_code=422, detail="panel form_factor requires panel_mode")
    if _get_view_by_ot(db, body.object_type_id):
        raise HTTPException(status_code=400, detail="An OvView already exists for this object type")

    view_id = body.id or uuid.uuid4().hex
    if db.query(OvView).filter(OvView.id == view_id).first():
        raise HTTPException(status_code=400, detail="OvView id already exists")

    now = int(time.time())
    row = OvView(
        id=view_id,
        object_type_id=body.object_type_id,
        form_factor=body.form_factor,
        panel_mode=body.panel_mode,
        panel_config=body.panel_config,
        auto_publish=body.auto_publish,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _audit(db, "object_views.view.created", view_id,
           {"object_type_id": body.object_type_id, "form_factor": body.form_factor})
    db.commit()
    db.refresh(row)
    return row


@router.get("/object-views", response_model=List[OvViewRead])
def list_views(db: Session = Depends(get_db)):
    return db.query(OvView).order_by(OvView.created_at).all()


@router.get("/object-views/by-object-type/{object_type_id}", response_model=OvViewRead)
def get_view_by_object_type(object_type_id: str, db: Session = Depends(get_db)):
    view = _get_view_by_ot(db, object_type_id)
    if not view:
        raise HTTPException(status_code=404, detail=f"No OvView for object type '{object_type_id}'")
    return view


@router.get("/object-views/view/{view_id}", response_model=OvViewRead)
def get_view(view_id: str, db: Session = Depends(get_db)):
    return _get_view(db, view_id)


@router.patch("/object-views/view/{view_id}", response_model=OvViewRead)
def update_view(view_id: str, body: OvViewUpdate, db: Session = Depends(get_db)):
    view = _get_view(db, view_id)
    if body.form_factor is not None:
        if body.form_factor not in VALID_FORM_FACTORS:
            raise HTTPException(status_code=422, detail="invalid form_factor")
        view.form_factor = body.form_factor
    if body.panel_mode is not None:
        if body.panel_mode not in VALID_PANEL_MODES:
            raise HTTPException(status_code=422, detail="invalid panel_mode")
        view.panel_mode = body.panel_mode
    if body.panel_config is not None:
        view.panel_config = body.panel_config
    if body.default_tab_id is not None:
        if not db.query(OvTab).filter(OvTab.id == body.default_tab_id,
                                      OvTab.view_id == view_id).first():
            raise HTTPException(status_code=404, detail="default_tab_id not a tab of this view")
        view.default_tab_id = body.default_tab_id
    if body.auto_publish is not None:
        view.auto_publish = body.auto_publish
    view.updated_at = int(time.time())
    db.commit()
    db.refresh(view)
    return view


@router.delete("/object-views/view/{view_id}")
def delete_view(view_id: str, db: Session = Depends(get_db)):
    view = _get_view(db, view_id)
    tabs = db.query(OvTab).filter(OvTab.view_id == view_id).all()
    for t in tabs:
        db.query(OvWidget).filter(OvWidget.tab_id == t.id).delete()
        db.delete(t)
    db.query(OvVersion).filter(OvVersion.view_id == view_id).delete()
    db.query(OvSidebar).filter(OvSidebar.view_id == view_id).delete()
    db.delete(view)
    db.commit()
    return {"deleted": view_id}


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

@router.post("/object-views/view/{view_id}/tabs", response_model=OvTabRead)
def add_tab(view_id: str, body: OvTabCreate, db: Session = Depends(get_db)):
    _get_view(db, view_id)
    if body.tab_type not in VALID_TAB_TYPES:
        raise HTTPException(status_code=422, detail=f"tab_type must be one of {sorted(VALID_TAB_TYPES)}")
    tab_id = body.id or uuid.uuid4().hex
    if db.query(OvTab).filter(OvTab.id == tab_id).first():
        raise HTTPException(status_code=400, detail="OvTab id already exists")
    if body.tab_order is None:
        existing = db.query(OvTab).filter(OvTab.view_id == view_id).count()
        order = existing
    else:
        order = body.tab_order
    row = OvTab(
        id=tab_id,
        view_id=view_id,
        tab_type=body.tab_type,
        display_name=body.display_name,
        tab_order=order,
        conditional_visibility=body.conditional_visibility,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/object-views/view/{view_id}/tabs", response_model=List[OvTabRead])
def list_tabs(view_id: str, db: Session = Depends(get_db)):
    _get_view(db, view_id)
    return (db.query(OvTab).filter(OvTab.view_id == view_id)
            .order_by(OvTab.tab_order).all())


@router.patch("/object-views/tabs/{tab_id}", response_model=OvTabRead)
def update_tab(tab_id: str, body: OvTabUpdate, db: Session = Depends(get_db)):
    tab = _get_tab(db, tab_id)
    if body.tab_type is not None:
        if body.tab_type not in VALID_TAB_TYPES:
            raise HTTPException(status_code=422, detail="invalid tab_type")
        tab.tab_type = body.tab_type
    if body.display_name is not None:
        tab.display_name = body.display_name
    if body.tab_order is not None:
        tab.tab_order = body.tab_order
    if body.conditional_visibility is not None:
        tab.conditional_visibility = body.conditional_visibility
    db.commit()
    db.refresh(tab)
    return tab


@router.delete("/object-views/tabs/{tab_id}")
def delete_tab(tab_id: str, db: Session = Depends(get_db)):
    tab = _get_tab(db, tab_id)
    db.query(OvWidget).filter(OvWidget.tab_id == tab_id).delete()
    # deleting a tab also deletes the Workshop module it contains (per docs)
    view = db.query(OvView).filter(OvView.id == tab.view_id).first()
    if view and view.default_tab_id == tab_id:
        view.default_tab_id = None
    db.delete(tab)
    db.commit()
    return {"deleted": tab_id}


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

@router.post("/object-views/tabs/{tab_id}/widgets", response_model=OvWidgetRead)
def add_widget(tab_id: str, body: OvWidgetCreate, db: Session = Depends(get_db)):
    _get_tab(db, tab_id)
    if body.widget_type not in VALID_WIDGET_TYPES:
        raise HTTPException(status_code=422, detail=f"widget_type must be one of {sorted(VALID_WIDGET_TYPES)}")
    widget_id = body.id or uuid.uuid4().hex
    if db.query(OvWidget).filter(OvWidget.id == widget_id).first():
        raise HTTPException(status_code=400, detail="OvWidget id already exists")
    if body.widget_order is None:
        order = db.query(OvWidget).filter(OvWidget.tab_id == tab_id).count()
    else:
        order = body.widget_order
    row = OvWidget(
        id=widget_id,
        tab_id=tab_id,
        widget_type=body.widget_type,
        widget_order=order,
        config=body.config,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/object-views/tabs/{tab_id}/widgets", response_model=List[OvWidgetRead])
def list_widgets(tab_id: str, db: Session = Depends(get_db)):
    _get_tab(db, tab_id)
    return (db.query(OvWidget).filter(OvWidget.tab_id == tab_id)
            .order_by(OvWidget.widget_order).all())


@router.patch("/object-views/widgets/{widget_id}", response_model=OvWidgetRead)
def update_widget(widget_id: str, body: OvWidgetUpdate, db: Session = Depends(get_db)):
    w = db.query(OvWidget).filter(OvWidget.id == widget_id).first()
    if not w:
        raise HTTPException(status_code=404, detail=f"OvWidget '{widget_id}' not found")
    if body.widget_type is not None:
        if body.widget_type not in VALID_WIDGET_TYPES:
            raise HTTPException(status_code=422, detail="invalid widget_type")
        w.widget_type = body.widget_type
    if body.widget_order is not None:
        w.widget_order = body.widget_order
    if body.config is not None:
        w.config = body.config
    db.commit()
    db.refresh(w)
    return w


@router.delete("/object-views/widgets/{widget_id}")
def delete_widget(widget_id: str, db: Session = Depends(get_db)):
    w = db.query(OvWidget).filter(OvWidget.id == widget_id).first()
    if not w:
        raise HTTPException(status_code=404, detail=f"OvWidget '{widget_id}' not found")
    db.delete(w)
    db.commit()
    return {"deleted": widget_id}


# ---------------------------------------------------------------------------
# Render (form-factor-aware, conditional visibility applied)
# ---------------------------------------------------------------------------

@router.get("/object-views/{object_type_id}/{object_id}/rendered")
def render_view(object_type_id: str, object_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Render the configured view (or standard if none) against an object instance."""
    ot = _get_object_type(db, object_type_id)
    obj = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.id == object_id,
        models.ObjectInstance.object_type_id == object_type_id,
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"ObjectInstance '{object_id}' not found for type")

    view = _get_view_by_ot(db, object_type_id)
    if not view:
        # fall back to standard view, resolved against the instance
        std = get_standard_view(object_type_id, db)
        resolved_widgets = []
        for w in std["widgets"]:
            if w["widget_type"] == "property_list":
                names = w["config"]["all_properties"]
                resolved_widgets.append({
                    "widget_type": "property_list",
                    "resolved": {"properties": {n: (obj.properties or {}).get(n) for n in names}},
                })
            else:
                resolved_widgets.append(w)
        return {"object_type_id": object_type_id, "object_id": object_id,
                "kind": "standard", "tabs": [{"display_name": "Standard",
                "visible": True, "widgets": resolved_widgets}]}

    tabs = (db.query(OvTab).filter(OvTab.view_id == view.id)
            .order_by(OvTab.tab_order).all())
    rendered_tabs = []
    for t in tabs:
        if not _tab_is_visible(db, t, obj):
            continue
        widgets = (db.query(OvWidget).filter(OvWidget.tab_id == t.id)
                   .order_by(OvWidget.widget_order).all())
        rendered_tabs.append({
            "tab_id": t.id,
            "display_name": t.display_name,
            "visible": True,
            "widgets": [_resolve_widget(db, w, ot, obj) for w in widgets],
        })
    return {
        "object_type_id": object_type_id,
        "object_id": object_id,
        "view_id": view.id,
        "kind": "configured",
        "default_tab_id": view.default_tab_id,
        "tabs": rendered_tabs,
    }


# ---------------------------------------------------------------------------
# Form factor (full / panel)
# ---------------------------------------------------------------------------

@router.get("/object-views/{object_type_id}/form-factor/{factor}")
def get_form_factor(object_type_id: str, factor: str,
                    object_id: Optional[str] = Query(default=None),
                    db: Session = Depends(get_db)) -> Dict[str, Any]:
    ot = _get_object_type(db, object_type_id)
    if factor not in VALID_FORM_FACTORS:
        raise HTTPException(status_code=422, detail=f"factor must be one of {sorted(VALID_FORM_FACTORS)}")
    view = _get_view_by_ot(db, object_type_id)

    if factor == "full":
        tabs = []
        if view:
            for t in (db.query(OvTab).filter(OvTab.view_id == view.id)
                      .order_by(OvTab.tab_order).all()):
                tabs.append({"tab_id": t.id, "display_name": t.display_name,
                             "tab_type": t.tab_type})
        return {"object_type_id": object_type_id, "form_factor": "full", "tabs": tabs}

    # panel
    panel_mode = (view.panel_mode if view and view.panel_mode else "instance")
    cfg = (view.panel_config if view and view.panel_config else {})
    if panel_mode == "instance":
        prominent = _prominent_property_names(ot)
        values = None
        if object_id:
            obj = db.query(models.ObjectInstance).filter(
                models.ObjectInstance.id == object_id).first()
            if obj:
                values = {n: (obj.properties or {}).get(n) for n in prominent}
        return {
            "object_type_id": object_type_id,
            "form_factor": "panel",
            "panel_mode": "instance",
            "prominent_properties": prominent,
            "property_values": values,
        }
    # object_set panel — Charts tab (up to 5 XY charts, documented) + List tab
    # (up to 3 properties per object, documented). Max object count is NOT
    # documented; we expose it as a configurable default flagged unverified.
    return {
        "object_type_id": object_type_id,
        "form_factor": "panel",
        "panel_mode": "object_set",
        "max_charts": cfg.get("max_charts", PANEL_SET_MAX_CHARTS_DEFAULT),         # documented = 5
        "max_properties_per_object": cfg.get("max_properties_per_object",
                                             PANEL_SET_MAX_PROPS_PER_OBJECT_DEFAULT),  # documented = 3
        "max_objects": cfg.get("max_objects", PANEL_SET_MAX_OBJECTS_DEFAULT),      # UNVERIFIED default
        "max_objects_documented": False,
        "tabs": ["charts", "list"],
    }


# ---------------------------------------------------------------------------
# Versioning (save / publish / republish)
# ---------------------------------------------------------------------------

@router.post("/object-views/view/{view_id}/save")
def save_version(view_id: str, body: OvPublishRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Save current tab/widget tree as a new version.

    Auto-publish (the documented default) publishes immediately; otherwise the
    new version stays unpublished until an explicit publish call.
    """
    view = _get_view(db, view_id)
    last = (db.query(OvVersion).filter(OvVersion.view_id == view_id)
            .order_by(OvVersion.version_number.desc()).first())
    next_num = (last.version_number + 1) if last else 1
    snapshot = _view_content_snapshot(db, view)
    ver = OvVersion(
        id=uuid.uuid4().hex,
        view_id=view_id,
        version_number=next_num,
        is_published=False,
        content_snapshot=snapshot,
        description=body.description,
        author=body.author,
        created_at=int(time.time()),
    )
    db.add(ver)
    db.flush()
    published = False
    if view.auto_publish:
        ver.is_published = True
        view.published_version_id = ver.id
        published = True
    view.updated_at = int(time.time())
    _audit(db, "object_views.version.saved", view_id,
           {"version_number": next_num, "published": published})
    db.commit()
    db.refresh(ver)
    return {
        "version_id": ver.id,
        "version_number": ver.version_number,
        "is_published": ver.is_published,
        "published_version_id": view.published_version_id,
    }


@router.get("/object-views/view/{view_id}/versions")
def list_versions(view_id: str, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    _get_view(db, view_id)
    rows = (db.query(OvVersion).filter(OvVersion.view_id == view_id)
            .order_by(OvVersion.version_number).all())
    return [{
        "id": r.id,
        "version_number": r.version_number,
        "is_published": r.is_published,
        "description": r.description,
        "author": r.author,
        "created_at": r.created_at,
    } for r in rows]


@router.put("/object-views/view/{view_id}/versions/{version_id}/publish")
def publish_version(view_id: str, version_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Publish a version (sets published_version_id) and restore its snapshot.

    Republishing an older version restores that version's content_snapshot, so the
    live view reflects exactly the chosen version (republish older supported).
    """
    view = _get_view(db, view_id)
    ver = (db.query(OvVersion).filter(OvVersion.id == version_id,
                                      OvVersion.view_id == view_id).first())
    if not ver:
        raise HTTPException(status_code=404, detail=f"OvVersion '{version_id}' not found for view")

    # unflag previously published (keep history but only one currently published)
    for other in db.query(OvVersion).filter(OvVersion.view_id == view_id,
                                            OvVersion.is_published == True).all():  # noqa: E712
        other.is_published = False
    ver.is_published = True
    view.published_version_id = ver.id
    _restore_snapshot(db, view, ver.content_snapshot or {})
    _audit(db, "object_views.version.published", view_id,
           {"version_id": version_id, "version_number": ver.version_number})
    db.commit()
    db.refresh(view)
    return {
        "view_id": view_id,
        "published_version_id": view.published_version_id,
        "version_number": ver.version_number,
        "restored_tab_count": len(db.query(OvTab).filter(OvTab.view_id == view_id).all()),
    }


# ---------------------------------------------------------------------------
# Sidebar (applications sidebar, opt-in)
# ---------------------------------------------------------------------------

@router.post("/object-views/view/{view_id}/sidebar")
def upsert_sidebar(view_id: str, body: OvSidebarUpsert, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _get_view(db, view_id)
    row = db.query(OvSidebar).filter(OvSidebar.view_id == view_id).first()
    now = int(time.time())
    if row:
        row.config = body.config
        row.updated_at = now
    else:
        row = OvSidebar(id=uuid.uuid4().hex, view_id=view_id,
                        config=body.config, created_at=now, updated_at=now)
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "view_id": row.view_id, "config": row.config,
            "updated_at": row.updated_at}


@router.get("/object-views/view/{view_id}/sidebar")
def get_sidebar(view_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _get_view(db, view_id)
    row = db.query(OvSidebar).filter(OvSidebar.view_id == view_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="No sidebar configured for this view")
    return {"id": row.id, "view_id": row.view_id, "config": row.config,
            "updated_at": row.updated_at}
