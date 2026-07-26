import base64
import copy
import hashlib
import json
import math
import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, models_action


def now_ts() -> int:
    return int(time.time())


def create_audit_log(
    db: Session,
    *,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> models_action.AuditLog:
    log = models_action.AuditLog(
        id=str(uuid.uuid4()),
        actor=actor,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload or {},
        created_at=now_ts(),
    )
    db.add(log)
    return log


def _schema_type(definition: Any) -> Optional[str]:
    if isinstance(definition, dict):
        return definition.get("type")
    if isinstance(definition, str):
        return definition
    return None


def _schema_required(definition: Any) -> bool:
    return bool(isinstance(definition, dict) and definition.get("required"))


def _matches_type(value: Any, declared_type: Optional[str]) -> bool:
    if declared_type in (None, "any"):
        return True
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "array":
        return isinstance(value, list)
    if declared_type == "object":
        return isinstance(value, dict)
    if declared_type == "json":
        return isinstance(value, (dict, list, str, int, float, bool)) or value is None
    if declared_type in {"geometry", "geojson"}:
        return validate_geojson_geometry(value)
    return True


def validate_object_properties(object_type: models.ObjectType, properties: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    schema = object_type.properties or {}

    for field, definition in schema.items():
        if _schema_required(definition) and field not in properties:
            errors.append(f"Missing required property '{field}'")

    for field, value in properties.items():
        if field not in schema:
            continue
        declared_type = _schema_type(schema[field])
        if not _matches_type(value, declared_type):
            errors.append(f"Property '{field}' expected {declared_type}, got {type(value).__name__}")

    return errors


def validate_action_parameters(action_type: models.ActionType, parameters: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    schema = action_type.parameters or {}

    for field, definition in schema.items():
        required = _schema_required(definition) or not isinstance(definition, dict)
        if required and field not in parameters:
            errors.append(f"Missing required parameter '{field}'")
            continue
        if field not in parameters:
            continue
        declared_type = _schema_type(definition)
        if not _matches_type(parameters[field], declared_type):
            errors.append(f"Parameter '{field}' expected {declared_type}, got {type(parameters[field]).__name__}")

    return errors


EARTH_RADIUS_METERS = 6371008.8
WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
UTM_K0 = 0.9996
LATITUDE_BANDS = "CDEFGHJKLMNPQRSTUVWX"
MGRS_EASTING_SETS = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")
MGRS_NORTHING_LETTERS = "ABCDEFGHJKLMNPQRSTUV"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_lon_lat_pair(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return False
    lon, lat = value[0], value[1]
    return _is_number(lon) and _is_number(lat) and -180 <= float(lon) <= 180 and -90 <= float(lat) <= 90


def _iter_positions(coordinates: Any) -> Iterable[Tuple[float, float]]:
    if _is_lon_lat_pair(coordinates):
        yield float(coordinates[0]), float(coordinates[1])
        return
    if isinstance(coordinates, list):
        for item in coordinates:
            yield from _iter_positions(item)


def validate_geojson_geometry(geometry: Any) -> bool:
    if not isinstance(geometry, dict):
        return False

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        return _is_lon_lat_pair(coordinates)
    if geometry_type == "LineString":
        return isinstance(coordinates, list) and len(coordinates) >= 2 and all(_is_lon_lat_pair(item) for item in coordinates)
    if geometry_type == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            return False
        for ring in coordinates:
            if not isinstance(ring, list) or len(ring) < 4 or not all(_is_lon_lat_pair(item) for item in ring):
                return False
            if ring[0][:2] != ring[-1][:2]:
                return False
        return True
    if geometry_type == "MultiPoint":
        return isinstance(coordinates, list) and all(_is_lon_lat_pair(item) for item in coordinates)
    if geometry_type == "MultiLineString":
        return isinstance(coordinates, list) and all(
            isinstance(line, list) and len(line) >= 2 and all(_is_lon_lat_pair(item) for item in line)
            for line in coordinates
        )
    if geometry_type == "MultiPolygon":
        return isinstance(coordinates, list) and all(
            validate_geojson_geometry({"type": "Polygon", "coordinates": polygon})
            for polygon in coordinates
        )
    return False


def make_geo_point(longitude: Any, latitude: Any) -> Optional[Dict[str, Any]]:
    if not _is_lon_lat_pair([longitude, latitude]):
        return None
    return {"type": "Point", "coordinates": [float(longitude), float(latitude)]}


def normalize_geometry(value: Any) -> Optional[Dict[str, Any]]:
    if validate_geojson_geometry(value):
        return value
    if _is_lon_lat_pair(value):
        return make_geo_point(value[0], value[1])
    if isinstance(value, dict):
        longitude = value.get("longitude", value.get("lon", value.get("lng")))
        latitude = value.get("latitude", value.get("lat"))
        point = make_geo_point(longitude, latitude)
        if point:
            return point
    return None


def extract_geometry(properties: Dict[str, Any], geometry_field: str = "geometry") -> Optional[Dict[str, Any]]:
    if not isinstance(properties, dict):
        return None

    for candidate in [geometry_field, "geometry", "location", "geojson"]:
        if candidate in properties:
            geometry = normalize_geometry(properties.get(candidate))
            if geometry:
                return geometry

    longitude = properties.get("longitude", properties.get("lon", properties.get("lng")))
    latitude = properties.get("latitude", properties.get("lat"))
    return make_geo_point(longitude, latitude)


def geometry_bbox(geometry: Dict[str, Any]) -> Optional[List[float]]:
    points = list(_iter_positions((geometry or {}).get("coordinates")))
    if not points:
        return None
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return [min(lons), min(lats), max(lons), max(lats)]


def geometry_reference_point(geometry: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    if not validate_geojson_geometry(geometry):
        return None
    if geometry.get("type") == "Point":
        lon, lat = geometry["coordinates"][:2]
        return float(lon), float(lat)

    bbox = geometry_bbox(geometry)
    if not bbox:
        return None
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def haversine_distance_meters(point_a: Tuple[float, float], point_b: Tuple[float, float]) -> float:
    lon1, lat1 = point_a
    lon2, lat2 = point_b
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bbox_intersects(left: List[float], right: List[float]) -> bool:
    return not (
        left[2] < right[0]
        or left[0] > right[2]
        or left[3] < right[1]
        or left[1] > right[3]
    )


def _point_in_bbox(point: Tuple[float, float], bbox: List[float]) -> bool:
    lon, lat = point
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _point_in_ring(point: Tuple[float, float], ring: List[List[float]]) -> bool:
    lon, lat = point
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        lon_i, lat_i = float(ring[i][0]), float(ring[i][1])
        lon_j, lat_j = float(ring[j][0]), float(ring[j][1])
        crosses = (lat_i > lat) != (lat_j > lat)
        if crosses:
            intersect_lon = (lon_j - lon_i) * (lat - lat_i) / ((lat_j - lat_i) or 1e-12) + lon_i
            if lon < intersect_lon:
                inside = not inside
        j = i
    return inside


def point_in_polygon(point: Tuple[float, float], polygon: Dict[str, Any]) -> bool:
    if not validate_geojson_geometry(polygon) or polygon.get("type") != "Polygon":
        return False
    rings = polygon["coordinates"]
    if not _point_in_ring(point, rings[0]):
        return False
    return not any(_point_in_ring(point, hole) for hole in rings[1:])


def bbox_to_polygon(bbox: List[float]) -> Dict[str, Any]:
    west, south, east, north = [float(item) for item in bbox]
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]],
    }


def _utm_zone_for_lon_lat(longitude: float, latitude: float) -> int:
    zone = int((longitude + 180) / 6) + 1
    zone = max(1, min(zone, 60))
    if 56 <= latitude < 64 and 3 <= longitude < 12:
        return 32
    if 72 <= latitude < 84:
        if 0 <= longitude < 9:
            return 31
        if 9 <= longitude < 21:
            return 33
        if 21 <= longitude < 33:
            return 35
        if 33 <= longitude < 42:
            return 37
    return zone


def _latitude_band(latitude: float) -> str:
    if not -80 <= latitude <= 84:
        raise ValueError("MGRS latitude must be between -80 and 84 degrees")
    index = min(int((latitude + 80) / 8), len(LATITUDE_BANDS) - 1)
    return LATITUDE_BANDS[index]


def _latitude_band_min(band: str) -> float:
    band = band.upper()
    if band not in LATITUDE_BANDS:
        raise ValueError(f"Invalid MGRS latitude band '{band}'")
    return -80 + LATITUDE_BANDS.index(band) * 8


def _utm_central_meridian(zone: int) -> float:
    return math.radians((zone - 1) * 6 - 180 + 3)


def latlon_to_utm(latitude: float, longitude: float, zone: Optional[int] = None) -> Dict[str, Any]:
    if not -80 <= latitude <= 84:
        raise ValueError("UTM/MGRS latitude must be between -80 and 84 degrees")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180 degrees")

    zone = zone or _utm_zone_for_lon_lat(longitude, latitude)
    e2 = WGS84_F * (2 - WGS84_F)
    ep2 = e2 / (1 - e2)
    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)
    lon0 = _utm_central_meridian(zone)

    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    tan_lat = math.tan(lat_rad)
    n = WGS84_A / math.sqrt(1 - e2 * sin_lat * sin_lat)
    t = tan_lat * tan_lat
    c = ep2 * cos_lat * cos_lat
    a = cos_lat * (lon_rad - lon0)
    m = WGS84_A * (
        (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256) * lat_rad
        - (3 * e2 / 8 + 3 * e2 * e2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * lat_rad)
        + (15 * e2 * e2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * lat_rad)
        - (35 * e2 ** 3 / 3072) * math.sin(6 * lat_rad)
    )

    easting = UTM_K0 * n * (
        a
        + (1 - t + c) * a ** 3 / 6
        + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * a ** 5 / 120
    ) + 500000
    northing = UTM_K0 * (
        m
        + n * tan_lat * (
            a * a / 2
            + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
            + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * a ** 6 / 720
        )
    )
    southern = latitude < 0
    if southern:
        northing += 10000000

    return {"zone": zone, "easting": easting, "northing": northing, "southern": southern}


def utm_to_latlon(zone: int, easting: float, northing: float, southern: bool = False) -> Tuple[float, float]:
    e2 = WGS84_F * (2 - WGS84_F)
    ep2 = e2 / (1 - e2)
    x = easting - 500000
    y = northing - (10000000 if southern else 0)

    m = y / UTM_K0
    mu = m / (WGS84_A * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    j1 = 3 * e1 / 2 - 27 * e1 ** 3 / 32
    j2 = 21 * e1 * e1 / 16 - 55 * e1 ** 4 / 32
    j3 = 151 * e1 ** 3 / 96
    j4 = 1097 * e1 ** 4 / 512
    fp = mu + j1 * math.sin(2 * mu) + j2 * math.sin(4 * mu) + j3 * math.sin(6 * mu) + j4 * math.sin(8 * mu)

    sin_fp = math.sin(fp)
    cos_fp = math.cos(fp)
    tan_fp = math.tan(fp)
    c1 = ep2 * cos_fp * cos_fp
    t1 = tan_fp * tan_fp
    n1 = WGS84_A / math.sqrt(1 - e2 * sin_fp * sin_fp)
    r1 = WGS84_A * (1 - e2) / ((1 - e2 * sin_fp * sin_fp) ** 1.5)
    d = x / (n1 * UTM_K0)

    lat = fp - (n1 * tan_fp / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720
    )
    lon = _utm_central_meridian(zone) + (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120
    ) / cos_fp

    return math.degrees(lat), math.degrees(lon)


def encode_mgrs(latitude: float, longitude: float, precision: int = 5) -> Dict[str, Any]:
    precision = max(0, min(int(precision), 5))
    utm = latlon_to_utm(latitude, longitude)
    zone = int(utm["zone"])
    band = _latitude_band(latitude)
    easting = float(utm["easting"])
    northing = float(utm["northing"])
    easting_set = MGRS_EASTING_SETS[(zone - 1) % 3]
    easting_index = int(easting / 100000) - 1
    easting_index = max(0, min(easting_index, len(easting_set) - 1))
    column_letter = easting_set[easting_index]
    northing_offset = 5 if zone % 2 == 0 else 0
    row_letter = MGRS_NORTHING_LETTERS[(int(northing / 100000) + northing_offset) % 20]

    scale = 10 ** (5 - precision)
    easting_remainder = int(easting % 100000)
    northing_remainder = int(northing % 100000)
    easting_digits = str(easting_remainder // scale).zfill(precision) if precision else ""
    northing_digits = str(northing_remainder // scale).zfill(precision) if precision else ""
    compact = f"{zone}{band}{column_letter}{row_letter}{easting_digits}{northing_digits}"
    formatted = f"{zone}{band} {column_letter}{row_letter}"
    if precision:
        formatted = f"{formatted} {easting_digits} {northing_digits}"

    return {
        "mgrs": compact,
        "formatted": formatted,
        "zone": zone,
        "band": band,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "precision": precision,
        "utm": {
            "zone": zone,
            "easting": round(easting, 3),
            "northing": round(northing, 3),
            "southern": bool(utm["southern"]),
        },
    }


def decode_mgrs(mgrs: str, *, center: bool = True) -> Dict[str, Any]:
    compact = re.sub(r"\s+", "", mgrs or "").upper()
    match = re.fullmatch(r"(\d{1,2})([C-HJ-NP-X])([A-HJ-NP-Z]{2})(\d*)", compact)
    if not match:
        raise ValueError("MGRS value must start with zone, latitude band, and 100km square letters")

    zone = int(match.group(1))
    if zone < 1 or zone > 60:
        raise ValueError("MGRS zone must be between 1 and 60")
    band = match.group(2)

    column_letter = match.group(3)[0]
    row_letter = match.group(3)[1]
    digits = match.group(4)
    if column_letter in {"I", "O"} or row_letter in {"I", "O"}:
        raise ValueError("MGRS square letters cannot contain I or O")
    if not digits.isdigit() or len(digits) % 2 != 0 or len(digits) > 10:
        raise ValueError("MGRS numeric precision must contain an even number of up to 10 digits")

    easting_set = MGRS_EASTING_SETS[(zone - 1) % 3]
    if column_letter not in easting_set:
        raise ValueError(f"MGRS column letter '{column_letter}' is not valid for zone {zone}")
    if row_letter not in MGRS_NORTHING_LETTERS:
        raise ValueError(f"MGRS row letter '{row_letter}' is not valid")

    precision = len(digits) // 2
    resolution = 10 ** (5 - precision)
    easting_digits = digits[:precision]
    northing_digits = digits[precision:]
    easting = (easting_set.index(column_letter) + 1) * 100000
    northing_offset = 5 if zone % 2 == 0 else 0
    northing = ((MGRS_NORTHING_LETTERS.index(row_letter) - northing_offset) % 20) * 100000
    if precision:
        easting += int(easting_digits) * resolution
        northing += int(northing_digits) * resolution
    if center and resolution:
        easting += resolution / 2
        northing += resolution / 2

    band_min_lat = _latitude_band_min(band)
    band_min_utm = latlon_to_utm(band_min_lat, (zone - 1) * 6 - 180 + 3, zone=zone)
    min_northing = float(band_min_utm["northing"])
    while northing < min_northing:
        northing += 2000000

    southern = band < "N"
    latitude, longitude = utm_to_latlon(zone, easting, northing, southern=southern)
    bbox = None
    if resolution:
        sw_lat, sw_lon = utm_to_latlon(zone, easting - (resolution / 2 if center else 0), northing - (resolution / 2 if center else 0), southern=southern)
        ne_lat, ne_lon = utm_to_latlon(zone, easting + (resolution / 2 if center else resolution), northing + (resolution / 2 if center else resolution), southern=southern)
        bbox = [min(sw_lon, ne_lon), min(sw_lat, ne_lat), max(sw_lon, ne_lon), max(sw_lat, ne_lat)]

    encoded = encode_mgrs(latitude, longitude, precision=precision)
    return {
        "mgrs": compact,
        "formatted": encoded["formatted"],
        "zone": zone,
        "band": band,
        "latitude": latitude,
        "longitude": longitude,
        "precision": precision,
        "bbox": bbox,
        "utm": {
            "zone": zone,
            "easting": round(easting, 3),
            "northing": round(northing, 3),
            "southern": southern,
        },
    }


def _record_value(record: Dict[str, Any], field: str) -> Any:
    if field in record:
        return record.get(field)

    if field.startswith("properties."):
        value: Any = record.get("properties", {})
        path = field.split(".")[1:]
    elif field.startswith("lineage."):
        value = record.get("lineage", {})
        path = field.split(".")[1:]
    else:
        value = record.get("properties", {})
        path = field.split(".")

    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _normalize_filters(filters: Any) -> List[Dict[str, Any]]:
    if not filters:
        return []

    normalized: List[Dict[str, Any]] = []
    if isinstance(filters, list):
        for item in filters:
            if not isinstance(item, dict) or "field" not in item:
                continue
            if "op" in item:
                normalized.append({
                    "field": item["field"],
                    "op": item.get("op", "equals"),
                    "value": item.get("value"),
                })
                continue
            for op in ("equals", "not_equals", "contains", "exists", "gt", "gte", "lt", "lte", "in", "regex"):
                if op in item:
                    normalized.append({"field": item["field"], "op": op, "value": item[op]})
                    break
        return normalized

    if isinstance(filters, dict):
        for field, expression in filters.items():
            if isinstance(expression, dict):
                for op, value in expression.items():
                    normalized.append({"field": field, "op": op, "value": value})
            else:
                normalized.append({"field": field, "op": "equals", "value": expression})

    return normalized


def _compare_filter(value: Any, op: str, expected: Any) -> bool:
    if op in {"equals", "eq", "=="}:
        return value == expected
    if op in {"not_equals", "neq", "!="}:
        return value != expected
    if op == "contains":
        if isinstance(value, list):
            return expected in value
        return str(expected).lower() in str(value or "").lower()
    if op == "exists":
        return (value is not None) == bool(expected)
    if op == "in":
        return value in (expected or [])
    if op == "regex":
        return bool(re.search(str(expected), str(value or "")))

    try:
        left = float(value)
        right = float(expected)
    except (TypeError, ValueError):
        return False

    if op in {"gt", ">"}:
        return left > right
    if op in {"gte", ">="}:
        return left >= right
    if op in {"lt", "<"}:
        return left < right
    if op in {"lte", "<="}:
        return left <= right
    return False


def _object_to_dict(obj: models.ObjectInstance, *, include_lineage: bool = True) -> Dict[str, Any]:
    payload = {
        "id": obj.id,
        "project_id": obj.project_id,
        "object_type_id": obj.object_type_id,
        "properties": obj.properties or {},
        "source_asset_id": obj.source_asset_id,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }
    if include_lineage:
        payload["lineage"] = obj.lineage or {}
    return payload


def _link_to_dict(link: models.LinkInstance) -> Dict[str, Any]:
    return {
        "id": link.id,
        "project_id": link.project_id,
        "link_type_id": link.link_type_id,
        "source_object_id": link.source_object_id,
        "target_object_id": link.target_object_id,
        "properties": link.properties or {},
        "created_at": link.created_at,
    }


# Fields that live at the top level of an object row (not inside `properties`),
# and a conservative identifier pattern — used to decide which equality predicates
# can be safely narrowed in SQL.
_SAFE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_TOP = {"id", "object_type_id", "source_asset_id", "created_at", "updated_at", "lineage", "properties"}


def _pushdown_equalities(db: Session, normalized_filters: List[Dict[str, Any]]):
    """SQLAlchemy conditions that narrow the candidate set for simple top-level
    equality predicates via SQLite ``json_extract``.

    This is ONLY a pre-filter: the Python pass in ``_query_object_rows`` re-checks
    every candidate with ``_compare_filter``, so the returned rows are identical to a
    pure-Python filter no matter what the pre-filter returns. Because a row that
    matches in Python also satisfies these equality conditions (consistent scalar
    semantics between Python ``==`` and SQLite ``json_extract`` equality), the
    pre-filter is always a superset of the true matches. Non-SQLite dialects skip it
    (correct, just unoptimized) — Postgres JSONB pushdown is a later hardening step.
    """
    try:
        dialect = db.get_bind().dialect.name
    except Exception:
        dialect = None
    if dialect != "sqlite":
        return []
    conds = []
    for item in normalized_filters:
        if item["op"] not in {"equals", "eq", "=="}:
            continue
        field = item["field"]
        value = item.get("value")
        if not isinstance(field, str) or not _SAFE_FIELD.match(field) or field in _RESERVED_TOP:
            continue
        if not isinstance(value, (str, int, float, bool)):  # excludes None / list / dict
            continue
        conds.append(func.json_extract(models.ObjectInstance.properties, "$." + field) == value)
    return conds


def _query_object_rows(
    db: Session,
    *,
    object_type_id: str,
    project_id: Optional[str] = None,
    filters: Optional[Any] = None,
) -> List[models.ObjectInstance]:
    object_type_query = db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id)
    if project_id is not None:
        object_type_query = object_type_query.filter(models.ObjectType.project_id == project_id)
    object_type = object_type_query.first()
    if not object_type:
        raise ValueError(f"ObjectType '{object_type_id}' not found")

    normalized_filters = _normalize_filters(filters)

    query = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == object_type_id
    )
    if project_id is not None:
        query = query.filter(models.ObjectInstance.project_id == project_id)
    # Narrow candidates in SQL for simple equality predicates; Python confirms below.
    for cond in _pushdown_equalities(db, normalized_filters):
        query = query.filter(cond)
    rows = query.all()

    if not normalized_filters:
        return rows

    matched = []
    for row in rows:
        record = _object_to_dict(row, include_lineage=True)
        if all(
            _compare_filter(
                _record_value(record, item["field"]),
                item["op"],
                item.get("value"),
            )
            for item in normalized_filters
        ):
            matched.append(row)
    return matched


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{int(offset)}".encode()).decode()


def _decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        if raw.startswith("o:"):
            return max(0, int(raw[2:]))
    except Exception:
        pass
    return 0


def query_object_set(
    db: Session,
    *,
    object_type_id: str,
    project_id: Optional[str] = None,
    filters: Optional[Any] = None,
    limit: int = 100,
    offset: int = 0,
    cursor: Optional[str] = None,
    with_total: bool = True,
    include_lineage: bool = True,
) -> Dict[str, Any]:
    start = _decode_cursor(cursor) if cursor else max(0, int(offset or 0))
    bounded_limit = max(0, min(int(limit), 10000))
    normalized = _normalize_filters(filters)

    if not normalized:
        # No residual predicates -> paginate in SQL. Order-free offset/limit on SQLite
        # returns rowid (insertion) order, matching the previous ``.all()[:limit]`` output
        # for the default call, so results stay backward compatible.
        type_query = db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id)
        if project_id is not None:
            type_query = type_query.filter(models.ObjectType.project_id == project_id)
        if not type_query.first():
            raise ValueError(f"ObjectType '{object_type_id}' not found")
        base = db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == object_type_id
        )
        if project_id is not None:
            base = base.filter(models.ObjectInstance.project_id == project_id)
        total = base.count() if with_total else None
        selected = base.offset(start).limit(bounded_limit).all() if bounded_limit else []
    else:
        rows = _query_object_rows(db, object_type_id=object_type_id, project_id=project_id, filters=filters)
        total = len(rows) if with_total else None
        selected = rows[start:start + bounded_limit] if bounded_limit else []

    next_cursor = (
        _encode_cursor(start + len(selected))
        if bounded_limit and len(selected) == bounded_limit
        and (total is None or start + len(selected) < total)
        else None
    )
    response: Dict[str, Any] = {
        "object_type_id": object_type_id,
        "filters": filters or {},
        "count": len(selected),
        "objects": [_object_to_dict(row, include_lineage=include_lineage) for row in selected],
        "next_cursor": next_cursor,
    }
    if with_total:
        response["total"] = total
    return response


def aggregate_object_set(
    db: Session,
    *,
    object_type_id: str,
    project_id: Optional[str] = None,
    filters: Optional[Any] = None,
    group_by: Optional[str] = None,
    metrics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    rows = _query_object_rows(db, object_type_id=object_type_id, project_id=project_id, filters=filters)
    grouped: Dict[str, List[models.ObjectInstance]] = {}
    for row in rows:
        record = _object_to_dict(row, include_lineage=True)
        raw_key = _record_value(record, group_by) if group_by else "all"
        key = str(raw_key if raw_key is not None else "null")
        grouped.setdefault(key, []).append(row)

    requested_metrics = metrics or []
    groups: List[Dict[str, Any]] = []
    for key, items in sorted(grouped.items(), key=lambda pair: pair[0]):
        aggregate: Dict[str, Any] = {
            "group": key,
            "count": len(items),
        }
        for metric in requested_metrics:
            if not isinstance(metric, dict):
                continue
            field = metric.get("field")
            operation = str(metric.get("operation", "count")).lower()
            alias = metric.get("alias") or f"{operation}_{field or 'rows'}"
            values = [
                _record_value(_object_to_dict(item, include_lineage=True), field)
                for item in items
                if field
            ]
            numeric_values = [
                float(value) for value in values
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ]
            if operation == "count":
                aggregate[alias] = len([value for value in values if value is not None]) if field else len(items)
            elif operation == "sum":
                aggregate[alias] = sum(numeric_values)
            elif operation == "avg":
                aggregate[alias] = sum(numeric_values) / len(numeric_values) if numeric_values else None
            elif operation == "min":
                aggregate[alias] = min(numeric_values) if numeric_values else None
            elif operation == "max":
                aggregate[alias] = max(numeric_values) if numeric_values else None
        groups.append(aggregate)

    return {
        "object_type_id": object_type_id,
        "filters": filters or {},
        "group_by": group_by,
        "total": len(rows),
        "groups": groups,
    }


def search_around_objects(
    db: Session,
    *,
    object_ids: List[str],
    project_id: Optional[str] = None,
    link_type_id: Optional[str] = None,
    direction: str = "both",
    target_object_type_id: Optional[str] = None,
    depth: int = 1,
) -> Dict[str, Any]:
    direction = direction.lower()
    if direction not in {"incoming", "outgoing", "both"}:
        raise ValueError("direction must be incoming, outgoing, or both")
    link_type_query = db.query(models.LinkType).filter(models.LinkType.id == link_type_id) if link_type_id else None
    if link_type_query is not None and project_id is not None:
        link_type_query = link_type_query.filter(models.LinkType.project_id == project_id)
    if link_type_id and not link_type_query.first():
        raise ValueError(f"LinkType '{link_type_id}' not found")
    target_query = db.query(models.ObjectType).filter(models.ObjectType.id == target_object_type_id) if target_object_type_id else None
    if target_query is not None and project_id is not None:
        target_query = target_query.filter(models.ObjectType.project_id == project_id)
    if target_object_type_id and not target_query.first():
        raise ValueError(f"ObjectType '{target_object_type_id}' not found")

    bounded_depth = max(1, min(int(depth), 6))
    seed_ids = [str(object_id) for object_id in object_ids]
    frontier: Set[str] = set(seed_ids)
    visited: Set[str] = set(seed_ids)
    node_ids: Set[str] = set(seed_ids)
    edge_ids: Set[str] = set()

    for _ in range(bounded_depth):
        if not frontier:
            break
        next_frontier: Set[str] = set()
        query = db.query(models.LinkInstance)
        if project_id is not None:
            query = query.filter(models.LinkInstance.project_id == project_id)
        if link_type_id:
            query = query.filter(models.LinkInstance.link_type_id == link_type_id)
        links = query.all()
        for link in links:
            candidates: List[Tuple[str, str]] = []
            if direction in {"outgoing", "both"} and link.source_object_id in frontier:
                candidates.append((link.source_object_id, link.target_object_id))
            if direction in {"incoming", "both"} and link.target_object_id in frontier:
                candidates.append((link.target_object_id, link.source_object_id))
            for _, neighbor_id in candidates:
                neighbor_query = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == neighbor_id)
                if project_id is not None:
                    neighbor_query = neighbor_query.filter(models.ObjectInstance.project_id == project_id)
                neighbor = neighbor_query.first()
                if not neighbor:
                    continue
                if target_object_type_id and neighbor.object_type_id != target_object_type_id:
                    continue
                edge_ids.add(link.id)
                node_ids.add(link.source_object_id)
                node_ids.add(link.target_object_id)
                if neighbor_id not in visited:
                    next_frontier.add(neighbor_id)
        visited.update(next_frontier)
        frontier = next_frontier

    nodes = [
        _object_to_dict(row, include_lineage=True)
        for row in db.query(models.ObjectInstance).filter(
            models.ObjectInstance.id.in_(node_ids),
            *([models.ObjectInstance.project_id == project_id] if project_id is not None else []),
        ).all()
    ] if node_ids else []
    edges = [
        _link_to_dict(row)
        for row in db.query(models.LinkInstance).filter(
            models.LinkInstance.id.in_(edge_ids),
            *([models.LinkInstance.project_id == project_id] if project_id is not None else []),
        ).all()
    ] if edge_ids else []

    return {
        "seed_object_ids": seed_ids,
        "depth": bounded_depth,
        "direction": direction,
        "nodes": nodes,
        "edges": edges,
    }


def spatial_query_objects(
    db: Session,
    *,
    object_type_id: str,
    project_id: Optional[str] = None,
    filters: Optional[Any] = None,
    geometry_field: str = "geometry",
    near: Optional[Dict[str, Any]] = None,
    radius_meters: Optional[float] = None,
    bbox: Optional[List[float]] = None,
    polygon: Optional[Dict[str, Any]] = None,
    limit: int = 100,
    include_lineage: bool = True,
) -> Dict[str, Any]:
    rows = _query_object_rows(db, object_type_id=object_type_id, project_id=project_id, filters=filters)
    bounded_limit = max(0, min(int(limit), 10000))
    near_point = geometry_reference_point(normalize_geometry(near) or {}) if near else None
    normalized_polygon = normalize_geometry(polygon) if polygon else None
    normalized_bbox = [float(item) for item in bbox] if bbox else None
    if normalized_bbox and len(normalized_bbox) != 4:
        raise ValueError("bbox must be [west, south, east, north]")
    if polygon and (not normalized_polygon or normalized_polygon.get("type") != "Polygon"):
        raise ValueError("polygon must be a GeoJSON Polygon")

    matches: List[Dict[str, Any]] = []
    for row in rows:
        geometry = extract_geometry(row.properties or {}, geometry_field)
        if not geometry:
            continue

        ref_point = geometry_reference_point(geometry)
        geom_bbox = geometry_bbox(geometry)
        if normalized_bbox and (not geom_bbox or not _bbox_intersects(geom_bbox, normalized_bbox)):
            continue
        if normalized_polygon and (not ref_point or not point_in_polygon(ref_point, normalized_polygon)):
            continue

        distance = None
        if near_point:
            if not ref_point:
                continue
            distance = haversine_distance_meters(near_point, ref_point)
            if radius_meters is not None and distance > float(radius_meters):
                continue

        payload = _object_to_dict(row, include_lineage=include_lineage)
        mgrs = encode_mgrs(ref_point[1], ref_point[0])["mgrs"] if ref_point else None
        payload["geometry"] = geometry
        payload["spatial"] = {
            "bbox": geom_bbox,
            "reference_point": {"longitude": ref_point[0], "latitude": ref_point[1]} if ref_point else None,
            "distance_meters": round(distance, 3) if distance is not None else None,
            "mgrs": mgrs,
        }
        matches.append(payload)

    if near_point:
        matches.sort(key=lambda item: item["spatial"]["distance_meters"] if item["spatial"]["distance_meters"] is not None else float("inf"))

    return {
        "object_type_id": object_type_id,
        "filters": filters or {},
        "geometry_field": geometry_field,
        "query": {
            "near": near,
            "radius_meters": radius_meters,
            "bbox": bbox,
            "polygon": polygon,
        },
        "total": len(matches),
        "count": len(matches[:bounded_limit]) if bounded_limit else 0,
        "objects": matches[:bounded_limit] if bounded_limit else [],
    }


def object_to_geojson_feature(obj: Dict[str, Any], *, geometry_field: str = "geometry", include_properties: bool = True) -> Optional[Dict[str, Any]]:
    geometry = obj.get("geometry") or extract_geometry(obj.get("properties") or {}, geometry_field)
    if not geometry:
        return None

    properties = {
        "object_id": obj["id"],
        "object_type_id": obj["object_type_id"],
        "source_asset_id": obj.get("source_asset_id"),
    }
    if include_properties:
        object_properties = dict(obj.get("properties") or {})
        object_properties.pop(geometry_field, None)
        object_properties.pop("geometry", None)
        properties.update(object_properties)
    if obj.get("spatial"):
        properties["spatial"] = obj["spatial"]

    return {
        "type": "Feature",
        "id": obj["id"],
        "geometry": geometry,
        "properties": properties,
    }


def object_set_feature_collection(
    db: Session,
    *,
    object_type_id: str,
    project_id: Optional[str] = None,
    filters: Optional[Any] = None,
    geometry_field: str = "geometry",
    limit: int = 1000,
    include_properties: bool = True,
) -> Dict[str, Any]:
    query = spatial_query_objects(
        db,
        object_type_id=object_type_id,
        project_id=project_id,
        filters=filters,
        geometry_field=geometry_field,
        limit=limit,
        include_lineage=False,
    )
    features = [
        feature for feature in (
            object_to_geojson_feature(obj, geometry_field=geometry_field, include_properties=include_properties)
            for obj in query["objects"]
        )
        if feature
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "object_type_id": object_type_id,
            "filters": filters or {},
            "geometry_field": geometry_field,
            "feature_count": len(features),
        },
    }


def evaluate_saved_object_set(
    db: Session,
    *,
    saved_object_set: models.SavedObjectSet,
    limit: int = 100,
    include_lineage: bool = True,
) -> Dict[str, Any]:
    return query_object_set(
        db,
        object_type_id=saved_object_set.object_type_id,
        project_id=saved_object_set.project_id,
        filters=saved_object_set.filters or {},
        limit=limit,
        include_lineage=include_lineage,
    )


def render_map_layer(
    db: Session,
    *,
    layer: models.MapLayerDefinition,
    limit: int = 1000,
) -> Dict[str, Any]:
    filters = layer.filters or {}
    object_type_id = layer.object_type_id
    if layer.saved_object_set_id:
        saved = db.query(models.SavedObjectSet).filter(
            models.SavedObjectSet.id == layer.saved_object_set_id,
            models.SavedObjectSet.project_id == layer.project_id,
        ).first()
        if not saved:
            raise ValueError(f"SavedObjectSet '{layer.saved_object_set_id}' not found")
        object_type_id = saved.object_type_id
        filters = {**(saved.filters or {}), **filters}

    collection = object_set_feature_collection(
        db,
        object_type_id=object_type_id,
        project_id=layer.project_id,
        filters=filters,
        geometry_field=layer.geometry_field,
        limit=limit,
        include_properties=True,
    )
    collection["layer"] = {
        "id": layer.id,
        "display_name": layer.display_name,
        "description": layer.description,
        "object_type_id": object_type_id,
        "saved_object_set_id": layer.saved_object_set_id,
        "geometry_field": layer.geometry_field,
        "filters": filters,
        "style": layer.style or {},
        "visible": layer.visible,
        "owner": layer.owner,
    }
    collection["metadata"]["layer_id"] = layer.id
    collection["metadata"]["style"] = layer.style or {}
    return collection


def build_object_profile(
    db: Session,
    *,
    object_type_id: str,
    object_id: str,
    project_id: Optional[str] = None,
    linked_limit: int = 50,
) -> Dict[str, Any]:
    obj = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.id == object_id,
        models.ObjectInstance.object_type_id == object_type_id,
        *([models.ObjectInstance.project_id == project_id] if project_id is not None else []),
    ).first()
    if not obj:
        raise ValueError(f"ObjectInstance '{object_id}' not found")
    object_type = db.query(models.ObjectType).filter(
        models.ObjectType.id == object_type_id,
        *([models.ObjectType.project_id == project_id] if project_id is not None else []),
    ).first()
    if not object_type:
        raise ValueError(f"ObjectType '{object_type_id}' not found")

    project_filters = [models.LinkInstance.project_id == project_id] if project_id is not None else []
    outbound_links = db.query(models.LinkInstance).filter(models.LinkInstance.source_object_id == object_id, *project_filters).all()
    inbound_links = db.query(models.LinkInstance).filter(models.LinkInstance.target_object_id == object_id, *project_filters).all()
    neighbor_ids = [link.target_object_id for link in outbound_links] + [link.source_object_id for link in inbound_links]
    linked_objects = [
        _object_to_dict(row, include_lineage=True)
        for row in db.query(models.ObjectInstance).filter(
            models.ObjectInstance.id.in_(neighbor_ids),
            *([models.ObjectInstance.project_id == project_id] if project_id is not None else []),
        ).limit(linked_limit).all()
    ] if neighbor_ids else []

    geometry = extract_geometry(obj.properties or {})
    spatial = None
    if geometry:
        ref_point = geometry_reference_point(geometry)
        spatial = {
            "geometry": geometry,
            "bbox": geometry_bbox(geometry),
            "reference_point": {"longitude": ref_point[0], "latitude": ref_point[1]} if ref_point else None,
            "mgrs": encode_mgrs(ref_point[1], ref_point[0])["mgrs"] if ref_point else None,
        }

    return {
        "object": {**_object_to_dict(obj, include_lineage=True), "spatial": spatial},
        "object_type": {
            "id": object_type.id,
            "display_name": object_type.display_name,
            "description": object_type.description,
            "properties": object_type.properties,
        },
        "inbound_links": [_link_to_dict(link) for link in inbound_links],
        "outbound_links": [_link_to_dict(link) for link in outbound_links],
        "linked_objects": linked_objects,
        "metrics": {
            "inbound_link_count": len(inbound_links),
            "outbound_link_count": len(outbound_links),
            "linked_object_count": len(linked_objects),
            "has_geometry": bool(geometry),
        },
    }


def evaluate_geofence(
    db: Session,
    *,
    object_type_id: str,
    project_id: Optional[str] = None,
    geofence: Optional[Dict[str, Any]] = None,
    bbox: Optional[List[float]] = None,
    filters: Optional[Any] = None,
    geometry_field: str = "geometry",
    limit: int = 1000,
) -> Dict[str, Any]:
    if geofence:
        polygon = normalize_geometry(geofence)
        if not polygon or polygon.get("type") != "Polygon":
            raise ValueError("geofence must be a GeoJSON Polygon")
    elif bbox:
        if len(bbox) != 4:
            raise ValueError("bbox must be [west, south, east, north]")
        polygon = bbox_to_polygon(bbox)
    else:
        raise ValueError("geofence or bbox is required")

    query = spatial_query_objects(
        db,
        object_type_id=object_type_id,
        project_id=project_id,
        filters=filters,
        geometry_field=geometry_field,
        limit=limit,
        include_lineage=False,
    )
    inside: List[Dict[str, Any]] = []
    outside: List[Dict[str, Any]] = []
    for obj in query["objects"]:
        reference_point = (obj.get("spatial") or {}).get("reference_point")
        if not reference_point:
            outside.append(obj)
            continue
        point = (reference_point["longitude"], reference_point["latitude"])
        if point_in_polygon(point, polygon):
            inside.append(obj)
        else:
            outside.append(obj)

    return {
        "object_type_id": object_type_id,
        "geometry_field": geometry_field,
        "geofence": polygon,
        "summary": {
            "total": len(query["objects"]),
            "inside": len(inside),
            "outside": len(outside),
        },
        "inside": inside,
        "outside": outside,
    }


def validate_link_instance_candidate(
    db: Session,
    *,
    link_type: models.LinkType,
    source: models.ObjectInstance,
    target: models.ObjectInstance,
    exclude_link_id: Optional[str] = None,
) -> List[str]:
    errors: List[str] = []
    if source.object_type_id != link_type.source_object_type_id:
        errors.append(
            f"Source object '{source.id}' has type '{source.object_type_id}', expected '{link_type.source_object_type_id}'"
        )
    if target.object_type_id != link_type.target_object_type_id:
        errors.append(
            f"Target object '{target.id}' has type '{target.object_type_id}', expected '{link_type.target_object_type_id}'"
        )

    cardinality = (link_type.cardinality or "MANY_TO_MANY").upper()
    query = db.query(models.LinkInstance).filter(
        models.LinkInstance.link_type_id == link_type.id,
        models.LinkInstance.project_id == link_type.project_id,
    )
    if exclude_link_id:
        query = query.filter(models.LinkInstance.id != exclude_link_id)
    existing_links = query.all()
    if cardinality in {"ONE_TO_ONE", "MANY_TO_ONE"} and any(
        item.source_object_id == source.id for item in existing_links
    ):
        errors.append(f"Cardinality {cardinality} allows at most one target for source '{source.id}'")
    if cardinality in {"ONE_TO_ONE", "ONE_TO_MANY"} and any(
        item.target_object_id == target.id for item in existing_links
    ):
        errors.append(f"Cardinality {cardinality} allows at most one source for target '{target.id}'")
    return errors


def resolve_value(expression: Any, source: Dict[str, Any]) -> Any:
    if isinstance(expression, str) and expression.startswith("$"):
        return source.get(expression[1:])
    if isinstance(expression, dict):
        if "from" in expression:
            return source.get(expression["from"])
        if "value" in expression:
            return expression["value"]
        if "template" in expression:
            return str(expression["template"]).format(**source)
    return expression


def stable_object_id(object_type_id: str, record: Dict[str, Any]) -> str:
    encoded = json.dumps(record, sort_keys=True, default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{object_type_id}:{digest}"


def _filter_records(records: List[Dict[str, Any]], step: Dict[str, Any]) -> List[Dict[str, Any]]:
    field = step.get("field")
    if not field:
        return records

    if "equals" in step:
        return [record for record in records if record.get(field) == step["equals"]]
    if "not_equals" in step:
        return [record for record in records if record.get(field) != step["not_equals"]]
    if "contains" in step:
        needle = str(step["contains"]).lower()
        return [record for record in records if needle in str(record.get(field, "")).lower()]
    if "exists" in step:
        exists = bool(step["exists"])
        return [record for record in records if (field in record and record[field] is not None) == exists]
    return records


def _project_records(records: List[Dict[str, Any]], fields: Iterable[str]) -> List[Dict[str, Any]]:
    field_set = list(fields)
    return [{field: record.get(field) for field in field_set if field in record} for record in records]


def _normalize_records(records: List[Dict[str, Any]], fields: Iterable[str]) -> List[Dict[str, Any]]:
    normalized = []
    for record in records:
        next_record = dict(record)
        for field in fields:
            if isinstance(next_record.get(field), str):
                next_record[field] = re.sub(r"\s+", " ", next_record[field].strip())
        normalized.append(next_record)
    return normalized


def _classify_records(records: List[Dict[str, Any]], step: Dict[str, Any]) -> List[Dict[str, Any]]:
    field = step.get("field")
    target_field = step.get("target_field", f"{field}_class")
    labels = step.get("labels", {})
    default_label = step.get("default", "unclassified")

    classified = []
    for record in records:
        text = str(record.get(field, "")).lower()
        label = default_label
        for candidate, keywords in labels.items():
            if any(str(keyword).lower() in text for keyword in keywords):
                label = candidate
                break
        next_record = dict(record)
        next_record[target_field] = label
        classified.append(next_record)
    return classified


def _summarize_records(records: List[Dict[str, Any]], step: Dict[str, Any]) -> List[Dict[str, Any]]:
    field = step.get("field")
    target_field = step.get("target_field", f"{field}_summary")
    max_chars = int(step.get("max_chars", 160))

    summarized = []
    for record in records:
        text = str(record.get(field, ""))
        summary = text[:max_chars].strip()
        if len(text) > max_chars:
            summary = f"{summary}..."
        next_record = dict(record)
        next_record[target_field] = summary
        summarized.append(next_record)
    return summarized


def _derive_geo_points(records: List[Dict[str, Any]], step: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    target_field = step.get("target_field", "geometry")
    longitude_field = step.get("longitude_field", "longitude")
    latitude_field = step.get("latitude_field", "latitude")
    longitude_expr = step.get("longitude")
    latitude_expr = step.get("latitude")
    created = 0
    skipped = 0
    output = []

    for record in records:
        longitude = resolve_value(longitude_expr, record) if longitude_expr is not None else record.get(longitude_field)
        latitude = resolve_value(latitude_expr, record) if latitude_expr is not None else record.get(latitude_field)
        geometry = make_geo_point(longitude, latitude)
        next_record = dict(record)
        if geometry:
            next_record[target_field] = geometry
            created += 1
        else:
            skipped += 1
            if step.get("strict"):
                raise ValueError(f"derive_geo_point could not build geometry for record '{record.get('id')}'")
        output.append(next_record)

    return output, {"geometries_created": created, "geometries_skipped": skipped}


def _derive_mgrs(records: List[Dict[str, Any]], step: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    geometry_field = step.get("geometry_field", "geometry")
    target_field = step.get("target_field", "mgrs")
    precision = int(step.get("precision", 5))
    created = 0
    skipped = 0
    output = []

    for record in records:
        geometry = normalize_geometry(record.get(geometry_field))
        ref_point = geometry_reference_point(geometry or {}) if geometry else None
        next_record = dict(record)
        if ref_point:
            next_record[target_field] = encode_mgrs(ref_point[1], ref_point[0], precision=precision)["mgrs"]
            created += 1
        else:
            skipped += 1
            if step.get("strict"):
                raise ValueError(f"derive_mgrs could not resolve geometry for record '{record.get('id')}'")
        output.append(next_record)

    return output, {"mgrs_created": created, "mgrs_skipped": skipped}


def hydrate_objects(
    db: Session,
    records: List[Dict[str, Any]],
    step: Dict[str, Any],
    *,
    pipeline_id: str,
    run_id: str,
    source_asset_id: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    object_type_id = step["object_type_id"]
    object_type = db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id).first()
    if not object_type:
        raise ValueError(f"ObjectType '{object_type_id}' not found")

    object_id_field = step.get("object_id_field")
    object_id_expr = step.get("object_id")
    property_map = step.get("property_map") or {}
    upsert = bool(step.get("upsert", True))
    hydrated_records: List[Dict[str, Any]] = []
    materialized = 0
    updated = 0
    from . import decision_intelligence

    for record in records:
        if object_id_expr is not None:
            object_id = resolve_value(object_id_expr, record)
        elif object_id_field:
            object_id = record.get(object_id_field)
        else:
            object_id = stable_object_id(object_type_id, record)
        if not object_id:
            raise ValueError("map_to_ontology step could not resolve object id")

        properties = {
            target: resolve_value(source_expr, record)
            for target, source_expr in property_map.items()
        } if property_map else dict(record)

        errors = validate_object_properties(object_type, properties)
        if errors:
            raise ValueError("; ".join(errors))

        existing = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == str(object_id)).first()
        lineage = {
            "source_asset_id": source_asset_id,
            "pipeline_id": pipeline_id,
            "pipeline_run_id": run_id,
            "operation": "map_to_ontology",
        }
        if existing:
            if existing.project_id != object_type.project_id:
                raise ValueError(f"ObjectInstance '{object_id}' belongs to another project")
            if not upsert:
                raise ValueError(f"ObjectInstance '{object_id}' already exists")
            existing.properties = {**(existing.properties or {}), **properties}
            existing.source_asset_id = source_asset_id
            existing.lineage = {**(existing.lineage or {}), **lineage}
            existing.updated_at = now_ts()
            decision_intelligence.record_object_snapshot(
                db,
                existing,
                event_type="pipeline.object.updated",
                actor="pipeline",
                source_type="pipeline_run",
                source_id=run_id,
            )
            updated += 1
        else:
            created = models.ObjectInstance(
                id=str(object_id),
                project_id=object_type.project_id,
                object_type_id=object_type_id,
                properties=properties,
                source_asset_id=source_asset_id,
                lineage=lineage,
                created_at=now_ts(),
                updated_at=now_ts(),
            )
            db.add(created)
            decision_intelligence.record_object_snapshot(
                db,
                created,
                event_type="pipeline.object.created",
                actor="pipeline",
                source_type="pipeline_run",
                source_id=run_id,
            )
            materialized += 1

        next_record = dict(record)
        next_record["_ontology_object_id"] = str(object_id)
        hydrated_records.append(next_record)

    return hydrated_records, {"materialized_objects": materialized, "updated_objects": updated}


def hydrate_links(
    db: Session,
    records: List[Dict[str, Any]],
    step: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    link_type_id = step["link_type_id"]
    link_type = db.query(models.LinkType).filter(models.LinkType.id == link_type_id).first()
    if not link_type:
        raise ValueError(f"LinkType '{link_type_id}' not found")

    source_field = step["source_object_id_field"]
    target_field = step["target_object_id_field"]
    property_map = step.get("property_map") or {}
    created = 0
    skipped = 0

    for record in records:
        source_id = record.get(source_field)
        target_id = record.get(target_field)
        if not source_id or not target_id:
            skipped += 1
            continue
        source = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == str(source_id)).first()
        target = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == str(target_id)).first()
        if not source or not target:
            skipped += 1
            continue
        if source.project_id != link_type.project_id or target.project_id != link_type.project_id:
            raise ValueError("Link hydration crosses a project boundary")
        link_id = str(step.get("link_id") or f"{link_type_id}:{source_id}:{target_id}")
        link_errors = validate_link_instance_candidate(
            db,
            link_type=link_type,
            source=source,
            target=target,
            exclude_link_id=link_id,
        )
        if link_errors:
            skipped += 1
            continue
        existing = db.query(models.LinkInstance).filter(models.LinkInstance.id == link_id).first()
        if existing:
            continue
        properties = {
            target_prop: resolve_value(source_expr, record)
            for target_prop, source_expr in property_map.items()
        }
        db.add(models.LinkInstance(
            id=link_id,
            project_id=link_type.project_id,
            link_type_id=link_type_id,
            source_object_id=str(source_id),
            target_object_id=str(target_id),
            properties=properties,
            created_at=now_ts(),
        ))
        created += 1

    return records, {"materialized_links": created, "skipped_links": skipped}


def _aggregate_pipeline_records(records: List[Dict[str, Any]], step: Dict[str, Any]) -> List[Dict[str, Any]]:
    group_by = step.get("group_by", [])
    aggregations = step.get("aggregations", [])
    groups: Dict[Tuple, List[Dict[str, Any]]] = {}
    for record in records:
        key = tuple(record.get(g) for g in group_by)
        groups.setdefault(key, []).append(record)
    output: List[Dict[str, Any]] = []
    for key, rows in groups.items():
        row: Dict[str, Any] = {g: k for g, k in zip(group_by, key)}
        for agg in aggregations:
            op = agg.get("op", "count")
            field = agg.get("field")
            alias = agg.get("as", f"{op}_{field}" if field else "count")
            nums = [
                r.get(field) for r in rows
                if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)
            ]
            if op == "count":
                row[alias] = len(rows)
            elif op == "sum":
                row[alias] = sum(nums)
            elif op == "avg":
                row[alias] = sum(nums) / len(nums) if nums else 0
            elif op == "min":
                row[alias] = min(nums) if nums else None
            elif op == "max":
                row[alias] = max(nums) if nums else None
            else:
                row[alias] = None
        output.append(row)
    return output


def _join_pipeline_records(left: List[Dict[str, Any]], right: List[Dict[str, Any]], step: Dict[str, Any]) -> List[Dict[str, Any]]:
    left_on = step.get("left_on") or step.get("on")
    right_on = step.get("right_on") or step.get("on")
    how = step.get("how", "inner")
    prefix = step.get("prefix", "")
    index: Dict[Any, Dict[str, Any]] = {}
    for r in right:
        index.setdefault(r.get(right_on), r)
    output: List[Dict[str, Any]] = []
    for row in left:
        match = index.get(row.get(left_on))
        if match:
            merged = dict(row)
            for k, v in match.items():
                if k == right_on:
                    continue
                merged[f"{prefix}{k}"] = v
            output.append(merged)
        elif how == "left":
            output.append(dict(row))
    return output


def _dedupe_pipeline_records(records: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    seen: Set = set()
    output: List[Dict[str, Any]] = []
    for record in records:
        marker = tuple(record.get(k) for k in keys) if keys else json.dumps(record, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            output.append(record)
    return output


def _cast_value(value: Any, to: str) -> Any:
    try:
        if to == "string":
            return None if value is None else str(value)
        if to in ("integer", "int", "long"):
            return int(value)
        if to in ("double", "float", "number"):
            return float(value)
        if to == "boolean":
            return value if isinstance(value, bool) else str(value).strip().lower() in {"true", "1", "yes"}
    except (ValueError, TypeError):
        return None
    return value


def _pipeline_sort_key(value: Any):
    is_num = isinstance(value, (int, float)) and not isinstance(value, bool)
    return (value is None, not is_num, value if is_num else str(value))


def execute_pipeline_steps(
    db: Session,
    *,
    pipeline: models.PipelineDefinition,
    run_id: str,
    input_asset: models.DataAsset,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    records = copy.deepcopy(input_asset.records or [])
    step_lineage: List[Dict[str, Any]] = []
    aggregate_metrics: Dict[str, Any] = {
        "steps": len(pipeline.steps or []),
        "materialized_objects": 0,
        "updated_objects": 0,
        "materialized_links": 0,
        "skipped_links": 0,
        "geometries_created": 0,
        "geometries_skipped": 0,
        "mgrs_created": 0,
        "mgrs_skipped": 0,
    }

    for index, step in enumerate(pipeline.steps or []):
        operation = step.get("operation") or step.get("type")
        if not operation:
            raise ValueError(f"Pipeline step {index} is missing an operation")

        records_in = len(records)
        metrics: Dict[str, Any] = {}

        if operation == "filter":
            records = _filter_records(records, step)
        elif operation in {"project", "select"}:
            records = _project_records(records, step.get("fields", []))
        elif operation == "derive":
            target_field = step["target_field"]
            records = [
                {**record, target_field: resolve_value(step.get("value"), record)}
                for record in records
            ]
        elif operation == "derive_geo_point":
            records, metrics = _derive_geo_points(records, step)
        elif operation == "derive_mgrs":
            records, metrics = _derive_mgrs(records, step)
        elif operation == "normalize":
            records = _normalize_records(records, step.get("fields", []))
        elif operation == "classify":
            records = _classify_records(records, step)
        elif operation == "summarize":
            records = _summarize_records(records, step)
        elif operation == "map_to_ontology":
            records, metrics = hydrate_objects(
                db,
                records,
                step,
                pipeline_id=pipeline.id,
                run_id=run_id,
                source_asset_id=input_asset.id,
            )
        elif operation == "link_objects":
            records, metrics = hydrate_links(db, records, step)
        elif operation == "join":
            right_asset = db.query(models.DataAsset).filter(models.DataAsset.id == step["right_asset_id"]).first()
            if not right_asset:
                raise ValueError(f"join right_asset_id '{step.get('right_asset_id')}' not found")
            records = _join_pipeline_records(records, right_asset.records or [], step)
            metrics = {"joined_with": right_asset.id, "right_rows": len(right_asset.records or [])}
        elif operation == "union":
            other = db.query(models.DataAsset).filter(models.DataAsset.id == step["asset_id"]).first()
            if not other:
                raise ValueError(f"union asset_id '{step.get('asset_id')}' not found")
            records = records + copy.deepcopy(other.records or [])
            metrics = {"unioned_with": other.id, "added_rows": len(other.records or [])}
        elif operation in {"aggregate", "group_by"}:
            records = _aggregate_pipeline_records(records, step)
            metrics = {"groups": len(records)}
        elif operation in {"dedupe", "distinct"}:
            records = _dedupe_pipeline_records(records, step.get("keys", []))
        elif operation == "cast":
            field = step["field"]
            to = step["to"]
            records = [{**record, field: _cast_value(record.get(field), to)} for record in records]
        elif operation == "rename":
            mapping = step.get("mapping", {})
            records = [{mapping.get(k, k): v for k, v in record.items()} for record in records]
        elif operation == "sort":
            field = step["field"]
            records = sorted(records, key=lambda r: _pipeline_sort_key(r.get(field)), reverse=bool(step.get("desc")))
        elif operation == "limit":
            records = records[: int(step.get("count", len(records)))]
        else:
            raise ValueError(f"Unsupported pipeline operation '{operation}'")

        for key, value in metrics.items():
            if isinstance(value, int):
                aggregate_metrics[key] = aggregate_metrics.get(key, 0) + value

        step_lineage.append({
            "index": index,
            "operation": operation,
            "records_in": records_in,
            "records_out": len(records),
            "metrics": metrics,
        })

    lineage = {
        "input_asset_id": input_asset.id,
        "pipeline_id": pipeline.id,
        "pipeline_run_id": run_id,
        "steps": step_lineage,
    }
    return records, lineage, aggregate_metrics


def _expectation_result(name: str, failures: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "name": name,
        "status": "FAIL" if failures else "PASS",
        "failure_count": len(failures),
        "failures": failures[:50],
    }


def _expectation_items(expectations: Any) -> List[Dict[str, Any]]:
    if isinstance(expectations, list):
        return [item for item in expectations if isinstance(item, dict)]
    if not isinstance(expectations, dict):
        return []

    items: List[Dict[str, Any]] = []
    for key, value in expectations.items():
        if key in {"row_count_min", "row_count_max"}:
            items.append({"type": key, "value": value})
        elif key in {"required_fields", "non_null", "unique"}:
            items.append({"type": key, "fields": value})
        elif key in {"allowed_values", "regex", "min", "max", "type"}:
            for field, rule in (value or {}).items():
                items.append({"type": key, "field": field, "value": rule})
    return items


def evaluate_data_expectations(records: List[Dict[str, Any]], expectations: Any) -> Dict[str, Any]:
    rows = records or []
    checks: List[Dict[str, Any]] = []

    for item in _expectation_items(expectations):
        check_type = item.get("type")
        failures: List[Dict[str, Any]] = []

        if check_type == "row_count_min":
            threshold = int(item.get("value", 0))
            if len(rows) < threshold:
                failures.append({"message": f"Expected at least {threshold} rows, got {len(rows)}"})
            checks.append(_expectation_result("row_count_min", failures))
            continue

        if check_type == "row_count_max":
            threshold = int(item.get("value", 0))
            if len(rows) > threshold:
                failures.append({"message": f"Expected at most {threshold} rows, got {len(rows)}"})
            checks.append(_expectation_result("row_count_max", failures))
            continue

        if check_type in {"required_fields", "non_null", "unique"}:
            fields = item.get("fields", [])
            if isinstance(fields, str):
                fields = [fields]
        else:
            fields = [item.get("field")]

        if check_type == "required_fields":
            for row_index, row in enumerate(rows):
                for field in fields:
                    if field not in row:
                        failures.append({"row_index": row_index, "field": field, "message": "Missing required field"})
        elif check_type == "non_null":
            for row_index, row in enumerate(rows):
                for field in fields:
                    if row.get(field) is None:
                        failures.append({"row_index": row_index, "field": field, "message": "Field is null"})
        elif check_type == "unique":
            for field in fields:
                seen: Dict[str, int] = {}
                for row_index, row in enumerate(rows):
                    marker = json.dumps(row.get(field), sort_keys=True, default=str)
                    if marker in seen:
                        failures.append({
                            "row_index": row_index,
                            "field": field,
                            "message": f"Duplicate value first seen at row {seen[marker]}",
                            "value": row.get(field),
                        })
                    else:
                        seen[marker] = row_index
        elif check_type == "allowed_values":
            field = item.get("field")
            allowed = set(item.get("value") or [])
            for row_index, row in enumerate(rows):
                if row.get(field) not in allowed:
                    failures.append({
                        "row_index": row_index,
                        "field": field,
                        "message": "Value is not allowed",
                        "value": row.get(field),
                    })
        elif check_type == "regex":
            field = item.get("field")
            pattern = str(item.get("value", ""))
            for row_index, row in enumerate(rows):
                if not re.search(pattern, str(row.get(field) or "")):
                    failures.append({
                        "row_index": row_index,
                        "field": field,
                        "message": "Value does not match regex",
                        "value": row.get(field),
                    })
        elif check_type in {"min", "max"}:
            field = item.get("field")
            threshold = float(item.get("value", 0))
            for row_index, row in enumerate(rows):
                value = row.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    failures.append({"row_index": row_index, "field": field, "message": "Value is not numeric", "value": value})
                    continue
                if check_type == "min" and value < threshold:
                    failures.append({"row_index": row_index, "field": field, "message": f"Value is below {threshold}", "value": value})
                if check_type == "max" and value > threshold:
                    failures.append({"row_index": row_index, "field": field, "message": f"Value is above {threshold}", "value": value})
        elif check_type == "type":
            field = item.get("field")
            declared_type = item.get("value")
            for row_index, row in enumerate(rows):
                if not _matches_type(row.get(field), declared_type):
                    failures.append({
                        "row_index": row_index,
                        "field": field,
                        "message": f"Expected {declared_type}, got {type(row.get(field)).__name__}",
                        "value": row.get(field),
                    })

        checks.append(_expectation_result(str(check_type), failures))

    failure_count = sum(check["failure_count"] for check in checks)
    return {
        "status": "FAIL" if failure_count else "PASS",
        "records_checked": len(rows),
        "summary": {
            "checks": len(checks),
            "passed": sum(1 for check in checks if check["status"] == "PASS"),
            "failed": sum(1 for check in checks if check["status"] == "FAIL"),
            "failure_count": failure_count,
        },
        "checks": checks,
    }


def _validation_issue(
    issues: List[Dict[str, Any]],
    *,
    severity: str,
    code: str,
    resource_type: str,
    resource_id: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    issues.append({
        "severity": severity,
        "code": code,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "message": message,
        "details": details or {},
    })


def validate_ontology_integrity(db: Session, project_id: Optional[str] = None) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    def project_rows(model: Any) -> List[Any]:
        query = db.query(model)
        if project_id is not None and hasattr(model, "project_id"):
            query = query.filter(model.project_id == project_id)
        return query.all()

    object_types = {item.id: item for item in project_rows(models.ObjectType)}
    link_types = {item.id: item for item in project_rows(models.LinkType)}
    objects = {item.id: item for item in project_rows(models.ObjectInstance)}
    actions = {item.id: item for item in db.query(models.ActionType).all()}
    data_assets = {item.id: item for item in project_rows(models.DataAsset)}
    pipelines = {item.id: item for item in project_rows(models.PipelineDefinition)}
    agents = {item.id: item for item in db.query(models.AgentDefinition).all()}
    saved_object_sets = {item.id: item for item in project_rows(models.SavedObjectSet)}
    map_layers = {item.id: item for item in project_rows(models.MapLayerDefinition)}

    for object_type in object_types.values():
        if not isinstance(object_type.properties, dict):
            _validation_issue(
                issues,
                severity="ERROR",
                code="object_type_schema_not_dict",
                resource_type="object_type",
                resource_id=object_type.id,
                message="Object type properties must be a schema dictionary.",
            )
            continue
        for field, definition in (object_type.properties or {}).items():
            declared_type = _schema_type(definition)
            if declared_type and declared_type not in {"any", "string", "integer", "number", "boolean", "array", "object", "json", "geometry", "geojson"}:
                _validation_issue(
                    issues,
                    severity="WARN",
                    code="object_type_unknown_field_type",
                    resource_type="object_type",
                    resource_id=object_type.id,
                    message=f"Property '{field}' uses unknown type '{declared_type}'.",
                )

    for link_type in link_types.values():
        if link_type.source_object_type_id not in object_types:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_type_missing_source_type",
                resource_type="link_type",
                resource_id=link_type.id,
                message=f"Source object type '{link_type.source_object_type_id}' does not exist.",
            )
        if link_type.target_object_type_id not in object_types:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_type_missing_target_type",
                resource_type="link_type",
                resource_id=link_type.id,
                message=f"Target object type '{link_type.target_object_type_id}' does not exist.",
            )
        if (link_type.cardinality or "").upper() not in {"ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"}:
            _validation_issue(
                issues,
                severity="WARN",
                code="link_type_unknown_cardinality",
                resource_type="link_type",
                resource_id=link_type.id,
                message=f"Cardinality '{link_type.cardinality}' is not one of the supported cardinalities.",
            )

    for obj in objects.values():
        object_type = object_types.get(obj.object_type_id)
        if not object_type:
            _validation_issue(
                issues,
                severity="ERROR",
                code="object_missing_type",
                resource_type="object_instance",
                resource_id=obj.id,
                message=f"Object type '{obj.object_type_id}' does not exist.",
            )
            continue
        if not isinstance(obj.properties, dict):
            _validation_issue(
                issues,
                severity="ERROR",
                code="object_properties_not_dict",
                resource_type="object_instance",
                resource_id=obj.id,
                message="Object instance properties must be a dictionary.",
            )
            continue
        for error in validate_object_properties(object_type, obj.properties or {}):
            _validation_issue(
                issues,
                severity="ERROR",
                code="object_property_validation_failed",
                resource_type="object_instance",
                resource_id=obj.id,
                message=error,
            )
        if obj.source_asset_id and obj.source_asset_id not in data_assets:
            _validation_issue(
                issues,
                severity="WARN",
                code="object_missing_source_asset",
                resource_type="object_instance",
                resource_id=obj.id,
                message=f"Source asset '{obj.source_asset_id}' does not exist.",
            )

    links = project_rows(models.LinkInstance)
    source_counts: Dict[Tuple[str, str], int] = {}
    target_counts: Dict[Tuple[str, str], int] = {}
    for link in links:
        link_type = link_types.get(link.link_type_id)
        source = objects.get(link.source_object_id)
        target = objects.get(link.target_object_id)
        if not link_type:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_missing_type",
                resource_type="link_instance",
                resource_id=link.id,
                message=f"Link type '{link.link_type_id}' does not exist.",
            )
            continue
        if not source:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_missing_source_object",
                resource_type="link_instance",
                resource_id=link.id,
                message=f"Source object '{link.source_object_id}' does not exist.",
            )
        if not target:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_missing_target_object",
                resource_type="link_instance",
                resource_id=link.id,
                message=f"Target object '{link.target_object_id}' does not exist.",
            )
        if source and source.object_type_id != link_type.source_object_type_id:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_source_type_mismatch",
                resource_type="link_instance",
                resource_id=link.id,
                message=f"Source object type '{source.object_type_id}' does not match link source type '{link_type.source_object_type_id}'.",
            )
        if target and target.object_type_id != link_type.target_object_type_id:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_target_type_mismatch",
                resource_type="link_instance",
                resource_id=link.id,
                message=f"Target object type '{target.object_type_id}' does not match link target type '{link_type.target_object_type_id}'.",
            )
        source_counts[(link.link_type_id, link.source_object_id)] = source_counts.get((link.link_type_id, link.source_object_id), 0) + 1
        target_counts[(link.link_type_id, link.target_object_id)] = target_counts.get((link.link_type_id, link.target_object_id), 0) + 1

    for (link_type_id, source_id), count in source_counts.items():
        cardinality = (link_types.get(link_type_id).cardinality if link_types.get(link_type_id) else "").upper()
        if cardinality in {"ONE_TO_ONE", "MANY_TO_ONE"} and count > 1:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_cardinality_source_violation",
                resource_type="link_type",
                resource_id=link_type_id,
                message=f"Source object '{source_id}' has {count} links but cardinality is {cardinality}.",
            )
    for (link_type_id, target_id), count in target_counts.items():
        cardinality = (link_types.get(link_type_id).cardinality if link_types.get(link_type_id) else "").upper()
        if cardinality in {"ONE_TO_ONE", "ONE_TO_MANY"} and count > 1:
            _validation_issue(
                issues,
                severity="ERROR",
                code="link_cardinality_target_violation",
                resource_type="link_type",
                resource_id=link_type_id,
                message=f"Target object '{target_id}' has {count} links but cardinality is {cardinality}.",
            )

    for action in actions.values():
        if not isinstance(action.parameters, dict):
            _validation_issue(issues, severity="ERROR", code="action_parameters_not_dict", resource_type="action_type", resource_id=action.id, message="Action parameters must be a dictionary.")
        if not isinstance(action.rules, dict):
            _validation_issue(issues, severity="ERROR", code="action_rules_not_dict", resource_type="action_type", resource_id=action.id, message="Action rules must be a dictionary.")
            continue
        for mutation in (action.rules or {}).get("object_mutations", []):
            object_type_id = mutation.get("object_type_id")
            object_type = object_types.get(object_type_id)
            if not object_type:
                _validation_issue(
                    issues,
                    severity="ERROR",
                    code="action_mutation_missing_object_type",
                    resource_type="action_type",
                    resource_id=action.id,
                    message=f"Mutation references missing object type '{object_type_id}'.",
                )
                continue
            if mutation.get("object_id_param") and mutation["object_id_param"] not in (action.parameters or {}):
                _validation_issue(
                    issues,
                    severity="WARN",
                    code="action_mutation_unknown_object_id_param",
                    resource_type="action_type",
                    resource_id=action.id,
                    message=f"Mutation object_id_param '{mutation['object_id_param']}' is not declared in action parameters.",
                )
            for field, expression in (mutation.get("set") or {}).items():
                if field not in (object_type.properties or {}):
                    _validation_issue(
                        issues,
                        severity="WARN",
                        code="action_mutation_unknown_property",
                        resource_type="action_type",
                        resource_id=action.id,
                        message=f"Mutation sets '{field}', which is not declared on object type '{object_type_id}'.",
                    )
                    continue
                if isinstance(expression, dict) and "value" in expression:
                    declared_type = _schema_type((object_type.properties or {}).get(field))
                    if not _matches_type(expression.get("value"), declared_type):
                        _validation_issue(
                            issues,
                            severity="ERROR",
                            code="action_mutation_literal_type_mismatch",
                            resource_type="action_type",
                            resource_id=action.id,
                            message=f"Mutation literal for '{field}' does not match declared type '{declared_type}'.",
                        )

    supported_pipeline_ops = {"filter", "project", "select", "derive", "derive_geo_point", "derive_mgrs", "normalize", "classify", "summarize", "map_to_ontology", "link_objects"}
    for pipeline in pipelines.values():
        if pipeline.input_asset_id not in data_assets:
            _validation_issue(issues, severity="ERROR", code="pipeline_missing_input_asset", resource_type="pipeline", resource_id=pipeline.id, message=f"Input asset '{pipeline.input_asset_id}' does not exist.")
        if pipeline.output_asset_id and pipeline.output_asset_id not in data_assets:
            _validation_issue(issues, severity="WARN", code="pipeline_missing_output_asset", resource_type="pipeline", resource_id=pipeline.id, message=f"Output asset '{pipeline.output_asset_id}' does not exist yet.")
        if not isinstance(pipeline.steps, list):
            _validation_issue(issues, severity="ERROR", code="pipeline_steps_not_list", resource_type="pipeline", resource_id=pipeline.id, message="Pipeline steps must be a list.")
            continue
        for index, step in enumerate(pipeline.steps or []):
            operation = step.get("operation") or step.get("type") if isinstance(step, dict) else None
            if operation not in supported_pipeline_ops:
                _validation_issue(issues, severity="ERROR", code="pipeline_unknown_operation", resource_type="pipeline", resource_id=pipeline.id, message=f"Step {index} uses unsupported operation '{operation}'.")
            if operation == "map_to_ontology":
                object_type_id = step.get("object_type_id")
                object_type = object_types.get(object_type_id)
                if not object_type:
                    _validation_issue(issues, severity="ERROR", code="pipeline_missing_object_type", resource_type="pipeline", resource_id=pipeline.id, message=f"Step {index} references missing object type '{object_type_id}'.")
                    continue
                for field in (step.get("property_map") or {}).keys():
                    if field not in (object_type.properties or {}):
                        _validation_issue(issues, severity="WARN", code="pipeline_unknown_object_property", resource_type="pipeline", resource_id=pipeline.id, message=f"Step {index} maps unknown property '{field}' for object type '{object_type_id}'.")
            if operation == "link_objects" and step.get("link_type_id") not in link_types:
                _validation_issue(issues, severity="ERROR", code="pipeline_missing_link_type", resource_type="pipeline", resource_id=pipeline.id, message=f"Step {index} references missing link type '{step.get('link_type_id')}'.")

    for asset in data_assets.values():
        if not isinstance(asset.asset_schema, dict):
            _validation_issue(issues, severity="ERROR", code="data_asset_schema_not_dict", resource_type="data_asset", resource_id=asset.id, message="Data asset schema must be a dictionary.")
        if not isinstance(asset.records, list):
            _validation_issue(issues, severity="ERROR", code="data_asset_records_not_list", resource_type="data_asset", resource_id=asset.id, message="Data asset records must be a list.")

    for agent in agents.values():
        for object_type_id in agent.allowed_object_types or []:
            if object_type_id not in object_types:
                _validation_issue(issues, severity="ERROR", code="agent_missing_allowed_object_type", resource_type="agent", resource_id=agent.id, message=f"Allowed object type '{object_type_id}' does not exist.")
        for action_id in agent.allowed_actions or []:
            if action_id not in actions:
                _validation_issue(issues, severity="ERROR", code="agent_missing_allowed_action", resource_type="agent", resource_id=agent.id, message=f"Allowed action '{action_id}' does not exist.")
        if agent.model_endpoint_id and not db.query(models.ModelEndpoint).filter(models.ModelEndpoint.id == agent.model_endpoint_id).first():
            _validation_issue(issues, severity="ERROR", code="agent_missing_model_endpoint", resource_type="agent", resource_id=agent.id, message=f"Model endpoint '{agent.model_endpoint_id}' does not exist.")

    for saved in saved_object_sets.values():
        if saved.object_type_id not in object_types:
            _validation_issue(
                issues,
                severity="ERROR",
                code="saved_object_set_missing_object_type",
                resource_type="saved_object_set",
                resource_id=saved.id,
                message=f"Saved object set references missing object type '{saved.object_type_id}'.",
            )
        if not isinstance(saved.filters, (dict, list)):
            _validation_issue(
                issues,
                severity="ERROR",
                code="saved_object_set_invalid_filters",
                resource_type="saved_object_set",
                resource_id=saved.id,
                message="Saved object set filters must be a dictionary or list.",
            )

    for layer in map_layers.values():
        if layer.object_type_id not in object_types:
            _validation_issue(
                issues,
                severity="ERROR",
                code="map_layer_missing_object_type",
                resource_type="map_layer",
                resource_id=layer.id,
                message=f"Map layer references missing object type '{layer.object_type_id}'.",
            )
        if layer.saved_object_set_id and layer.saved_object_set_id not in saved_object_sets:
            _validation_issue(
                issues,
                severity="ERROR",
                code="map_layer_missing_saved_object_set",
                resource_type="map_layer",
                resource_id=layer.id,
                message=f"Map layer references missing saved object set '{layer.saved_object_set_id}'.",
            )
        if not isinstance(layer.filters, (dict, list)):
            _validation_issue(
                issues,
                severity="ERROR",
                code="map_layer_invalid_filters",
                resource_type="map_layer",
                resource_id=layer.id,
                message="Map layer filters must be a dictionary or list.",
            )
        if not isinstance(layer.style, dict):
            _validation_issue(
                issues,
                severity="ERROR",
                code="map_layer_invalid_style",
                resource_type="map_layer",
                resource_id=layer.id,
                message="Map layer style must be a dictionary.",
            )

    for logic in db.query(models.LogicFunction).all():
        if not isinstance(logic.blocks, list):
            _validation_issue(issues, severity="ERROR", code="logic_blocks_not_list", resource_type="logic_function", resource_id=logic.id, message="Logic blocks must be a list.")
            continue
        for index, block in enumerate(logic.blocks or []):
            block_type = block.get("type") or block.get("operation") if isinstance(block, dict) else None
            if block_type == "retrieve_context":
                for object_type_id in block.get("object_types", []):
                    if object_type_id not in object_types:
                        _validation_issue(issues, severity="ERROR", code="logic_missing_context_object_type", resource_type="logic_function", resource_id=logic.id, message=f"Block {index} references missing object type '{object_type_id}'.")
            if block_type == "propose_action" and block.get("action_type_id") not in actions:
                _validation_issue(issues, severity="ERROR", code="logic_missing_action", resource_type="logic_function", resource_id=logic.id, message=f"Block {index} references missing action '{block.get('action_type_id')}'.")

    for automation in db.query(models.AutomationDefinition).all():
        condition = automation.condition or {}
        effect = automation.effect or {}
        if condition.get("type") == "object_count" and condition.get("object_type_id") not in object_types:
            _validation_issue(issues, severity="ERROR", code="automation_missing_condition_object_type", resource_type="automation", resource_id=automation.id, message=f"Condition references missing object type '{condition.get('object_type_id')}'.")
        if effect.get("action_type_id") and effect.get("action_type_id") not in actions:
            _validation_issue(issues, severity="ERROR", code="automation_missing_effect_action", resource_type="automation", resource_id=automation.id, message=f"Effect references missing action '{effect.get('action_type_id')}'.")

    for suite in db.query(models.EvalSuite).all():
        if suite.target_agent_id not in agents:
            _validation_issue(issues, severity="ERROR", code="eval_missing_target_agent", resource_type="eval_suite", resource_id=suite.id, message=f"Target agent '{suite.target_agent_id}' does not exist.")

    summary = {
        "errors": sum(1 for issue in issues if issue["severity"] == "ERROR"),
        "warnings": sum(1 for issue in issues if issue["severity"] == "WARN"),
        "checked": {
            "object_types": len(object_types),
            "object_instances": len(objects),
            "link_types": len(link_types),
            "link_instances": len(links),
            "action_types": len(actions),
            "data_assets": len(data_assets),
            "pipelines": len(pipelines),
            "agents": len(agents),
            "saved_object_sets": len(saved_object_sets),
            "map_layers": len(map_layers),
            "logic_functions": db.query(models.LogicFunction).count(),
            "automations": db.query(models.AutomationDefinition).count(),
            "eval_suites": db.query(models.EvalSuite).count(),
        },
    }
    return {
        "status": "FAIL" if summary["errors"] else "PASS",
        "summary": summary,
        "issues": issues,
    }


def apply_action_mutations(
    db: Session,
    *,
    action_type: models.ActionType,
    parameters: Dict[str, Any],
    actor: str,
) -> List[str]:
    rules = action_type.rules or {}
    mutations = rules.get("object_mutations", [])
    mutated_ids: List[str] = []
    from . import decision_intelligence

    for mutation in mutations:
        object_type_id = mutation["object_type_id"]
        object_type = db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id).first()
        if not object_type:
            raise ValueError(f"ObjectType '{object_type_id}' not found")

        object_id = resolve_value(mutation.get("object_id"), parameters)
        if not object_id and mutation.get("object_id_param"):
            object_id = parameters.get(mutation["object_id_param"])
        if not object_id:
            raise ValueError("Action mutation could not resolve object id")

        existing = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == str(object_id)).first()
        if not existing:
            if not mutation.get("create_if_missing"):
                raise ValueError(f"ObjectInstance '{object_id}' not found")
            existing = models.ObjectInstance(
                id=str(object_id),
                project_id=object_type.project_id,
                object_type_id=object_type_id,
                properties={},
                source_asset_id=None,
                lineage={"created_by_action": action_type.id},
                created_at=now_ts(),
                updated_at=now_ts(),
            )
            db.add(existing)
        elif existing.project_id != object_type.project_id:
            raise ValueError(f"ObjectInstance '{object_id}' belongs to another project")

        updates = {
            field: resolve_value(expression, parameters)
            for field, expression in (mutation.get("set") or {}).items()
        }
        next_properties = {**(existing.properties or {}), **updates}
        errors = validate_object_properties(object_type, next_properties)
        if errors:
            raise ValueError("; ".join(errors))

        existing.properties = next_properties
        existing.lineage = {
            **(existing.lineage or {}),
            "last_action_id": action_type.id,
            "last_action_actor": actor,
        }
        existing.updated_at = now_ts()
        decision_intelligence.record_object_snapshot(
            db,
            existing,
            event_type="action.object.mutated",
            actor=actor,
            source_type="action_type",
            source_id=action_type.id,
        )
        mutated_ids.append(existing.id)

    return mutated_ids


def build_context_pack(
    db: Session,
    *,
    allowed_object_types: List[str],
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    filters = filters or {}
    object_type_ids = allowed_object_types
    if not object_type_ids:
        object_type_ids = [row.id for row in db.query(models.ObjectType).all()]

    packs = []
    for object_type_id in object_type_ids:
        objects = db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == object_type_id
        ).all()

        object_filters = filters.get(object_type_id, {}) if isinstance(filters.get(object_type_id), dict) else {}
        if object_filters:
            objects = [
                obj for obj in objects
                if all((obj.properties or {}).get(key) == value for key, value in object_filters.items())
            ]

        packs.append({
            "object_type_id": object_type_id,
            "objects": [
                {
                    "id": obj.id,
                    "properties": obj.properties,
                    "lineage": obj.lineage,
                }
                for obj in objects[:limit]
            ],
        })

    return {"packs": packs, "filters": filters, "limit": limit}


def plan_agent_session(
    db: Session,
    *,
    agent: models.AgentDefinition,
    user_prompt: str,
    filters: Optional[Dict[str, Any]] = None,
    max_context_objects: int = 5,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], str]:
    context = build_context_pack(
        db,
        allowed_object_types=agent.allowed_object_types or [],
        filters=filters,
        limit=max_context_objects,
    )
    try:
        from . import decision_intelligence
        context["decision_intelligence"] = decision_intelligence.build_decision_context(db, context)
    except Exception as exc:
        context["decision_intelligence"] = {"error": str(exc), "object_risk": [], "duplicate_warnings": []}
    prompt = user_prompt.lower()
    action_ids = agent.allowed_actions or []
    proposed_actions: List[Dict[str, Any]] = []
    risk_requires_approval = bool((context.get("decision_intelligence") or {}).get("high_risk_object_ids"))

    for action_id in action_ids:
        action = db.query(models.ActionType).filter(models.ActionType.id == action_id).first()
        if not action:
            continue
        labels = {action.id.lower(), action.id.replace("_", " ").lower(), action.display_name.lower()}
        if any(label in prompt for label in labels):
            parameters = {
                name: None for name in (action.parameters or {}).keys()
            }
            requires_approval = bool(
                agent.approval_required
                or (action.rules or {}).get("requires_approval")
                or risk_requires_approval
            )
            rationale = "Prompt matched an allowed ontology action; parameters must be supplied or confirmed by a user."
            if risk_requires_approval:
                rationale += " Decision intelligence found high-risk context, so the action remains staged for approval."
            proposed_actions.append({
                "action_type_id": action.id,
                "display_name": action.display_name,
                "parameters": parameters,
                "requires_approval": requires_approval,
                "rationale": rationale,
            })

    plan = {
        "steps": [
            {"name": "retrieve_context", "status": "completed"},
            {"name": "inspect_decision_intelligence", "status": "completed"},
            {"name": "inspect_allowed_actions", "status": "completed"},
            {
                "name": "stage_action_for_review" if proposed_actions else "answer_from_context",
                "status": "completed",
            },
        ],
        "guardrails": {
            "allowed_object_types": agent.allowed_object_types,
            "allowed_actions": agent.allowed_actions,
            "approval_required": agent.approval_required,
            "high_risk_object_ids": (context.get("decision_intelligence") or {}).get("high_risk_object_ids", []),
        },
    }
    status = "ACTION_PROPOSED" if proposed_actions else "ANSWERED_WITH_CONTEXT"
    return context, plan, proposed_actions, status


def score_eval_case(session: models.AgentSession, case: Dict[str, Any]) -> Dict[str, Any]:
    expected_actions = set(case.get("expected_actions", []))
    actual_actions = {item.get("action_type_id") for item in (session.proposed_actions or [])}
    expected_context_types = set(case.get("expected_context_object_types", []))
    actual_context_types = {
        pack.get("object_type_id")
        for pack in (session.context or {}).get("packs", [])
        if pack.get("objects")
    }

    action_pass = expected_actions.issubset(actual_actions)
    context_pass = expected_context_types.issubset(actual_context_types)
    checks = [action_pass, context_pass]
    score = int(100 * sum(1 for check in checks if check) / len(checks))

    return {
        "case_id": case.get("id"),
        "prompt": case.get("prompt"),
        "score": score,
        "checks": {
            "expected_actions_found": action_pass,
            "expected_context_found": context_pass,
        },
        "actual_actions": sorted(action for action in actual_actions if action),
        "actual_context_object_types": sorted(item for item in actual_context_types if item),
    }


AIP_TOOL_CATALOG: List[Dict[str, str]] = [
    {
        "id": "aip_assist",
        "display_name": "AIP Assist",
        "public_palantir_equivalent": "AIP Assist sidebar and application integrations",
        "local_endpoint": "/aip/assist/query",
        "status": "implemented_local_equivalent",
        "notes": "Context-aware deterministic helper over local ontology metadata, actions, pipelines, and tool catalog.",
    },
    {
        "id": "aip_chatbot_studio",
        "display_name": "AIP Chatbot Studio",
        "public_palantir_equivalent": "AIP Chatbot Studio / former AIP Agent Studio",
        "local_endpoint": "/agents and /agents/{agent_id}/sessions",
        "status": "implemented_local_equivalent",
        "notes": "Scoped ontology context retrieval with allowed action proposal and approval staging.",
    },
    {
        "id": "aip_logic",
        "display_name": "AIP Logic",
        "public_palantir_equivalent": "No-code AI workflow/function builder",
        "local_endpoint": "/logic-functions and /logic-functions/{logic_id}/run",
        "status": "implemented_local_equivalent",
        "notes": "Block-based deterministic workflow runner over context, assist, document extraction, and action proposal blocks.",
    },
    {
        "id": "aip_evals",
        "display_name": "AIP Evals",
        "public_palantir_equivalent": "Evaluation suites and experiments for Logic/agent workflows",
        "local_endpoint": "/eval-suites and /eval-suites/{suite_id}/run",
        "status": "implemented_local_equivalent",
        "notes": "Deterministic checks for context retrieval and expected action proposal.",
    },
    {
        "id": "aip_threads",
        "display_name": "AIP Threads",
        "public_palantir_equivalent": "Ad-hoc LLM task workspace with documents/resources",
        "local_endpoint": "/threads and /threads/{thread_id}/messages",
        "status": "implemented_local_equivalent",
        "notes": "Stores threaded messages, document snippets, resources, and local assistant responses.",
    },
    {
        "id": "aip_model_catalog",
        "display_name": "AIP Model Catalog",
        "public_palantir_equivalent": "Discovery/orientation for Palantir-provided and custom models",
        "local_endpoint": "/model-endpoints",
        "status": "implemented_local_equivalent",
        "notes": "Governed model/provider metadata registry; local runtime does not call external LLMs by default.",
    },
    {
        "id": "palantir_mcp",
        "display_name": "Palantir MCP",
        "public_palantir_equivalent": "External AI IDE/agent context bridge",
        "local_endpoint": "/mcp/context",
        "status": "implemented_local_equivalent",
        "notes": "Exports ontology, action, pipeline, agent, and tool metadata as agent-consumable context.",
    },
    {
        "id": "document_intelligence",
        "display_name": "AIP Document Intelligence",
        "public_palantir_equivalent": "Document extraction strategies deployable into transforms",
        "local_endpoint": "/aip/document-intelligence/extract",
        "status": "implemented_local_equivalent",
        "notes": "Regex/schema-based extraction for local testing; no proprietary document models.",
    },
    {
        "id": "pipeline_builder_aip",
        "display_name": "AIP in Pipeline Builder",
        "public_palantir_equivalent": "Generate, explain, regex helper, transform assist, LLM node, embeddings",
        "local_endpoint": "/aip/pipeline-builder/generate and /pipelines",
        "status": "implemented_local_equivalent",
        "notes": "Prompt-to-step suggestions plus existing deterministic pipeline runner.",
    },
    {
        "id": "automate_scheduler",
        "display_name": "Automate and Scheduler",
        "public_palantir_equivalent": "Schedule/event automations integrated with Logic and ontology actions",
        "local_endpoint": "/automations, /automations/{automation_id}/run, /scheduler/generate-cron",
        "status": "implemented_local_equivalent",
        "notes": "Object-count conditions, action approval staging, and prompt-to-cron helper.",
    },
    {
        "id": "notepad_aip",
        "display_name": "AIP in Notepad",
        "public_palantir_equivalent": "Spellcheck, shorten, modify, and translate text",
        "local_endpoint": "/aip/notepad/transform",
        "status": "implemented_local_equivalent",
        "notes": "Local deterministic text transforms suitable for tests and demos.",
    },
    {
        "id": "ontology_object_sets",
        "display_name": "Ontology Object Sets",
        "public_palantir_equivalent": "Object Sets, property filters, aggregation, and Search Around graph exploration",
        "local_endpoint": "/object-sets/search, /object-sets/aggregate, and /object-sets/search-around",
        "status": "implemented_local_equivalent",
        "notes": "Generic ontology object filtering, grouped metrics, and bounded graph traversal over links.",
    },
    {
        "id": "data_health_expectations",
        "display_name": "Data Health Expectations",
        "public_palantir_equivalent": "Dataset health checks and transform validation expectations",
        "local_endpoint": "/data-assets/{asset_id}/expectations/run",
        "status": "implemented_local_equivalent",
        "notes": "Required fields, non-null, uniqueness, allowed values, regex, range, type, and row-count checks.",
    },
    {
        "id": "ontology_validator",
        "display_name": "Ontology Integrity Validator",
        "public_palantir_equivalent": "Ontology management validation for objects, links, actions, pipelines, agents, and automation",
        "local_endpoint": "/ontology/validate",
        "status": "implemented_local_equivalent",
        "notes": "Detects broken schemas, dangling graph references, cardinality errors, invalid mutations, and bad tool references.",
    },
    {
        "id": "gis_spatial_intelligence",
        "display_name": "GIS Spatial Intelligence",
        "public_palantir_equivalent": "Geospatial object layers, map-ready feature exports, radius search, and geofence analysis",
        "local_endpoint": "/gis/spatial-query, /gis/feature-collection, and /gis/geofence/evaluate",
        "status": "implemented_local_equivalent",
        "notes": "Stores GeoJSON on ontology objects and provides deterministic spatial queries without proprietary map services.",
    },
    {
        "id": "mgrs_grid_reference",
        "display_name": "MGRS Grid Reference",
        "public_palantir_equivalent": "Military grid/geospatial coordinate support for operational map workflows",
        "local_endpoint": "/gis/mgrs/encode and /gis/mgrs/decode",
        "status": "implemented_local_equivalent",
        "notes": "Encodes WGS84 latitude/longitude to MGRS and decodes MGRS cells back to map-ready coordinates.",
    },
    {
        "id": "foundry_map_layers",
        "display_name": "Foundry-Style Map Layers",
        "public_palantir_equivalent": "Map Layer Editor, ontology object layers, saved object sets, and map templates",
        "local_endpoint": "/object-sets/saved and /gis/map-layers",
        "status": "implemented_local_equivalent",
        "notes": "Persists reusable object-set filters and renders map layer FeatureCollections with style metadata.",
    },
    {
        "id": "object_views",
        "display_name": "Object Views",
        "public_palantir_equivalent": "Object-centric profile with linked objects, metrics, and workflow context",
        "local_endpoint": "/objects/{object_type_id}/{object_id}/profile",
        "status": "implemented_local_equivalent",
        "notes": "Builds a local object profile from object properties, inbound/outbound links, linked objects, and spatial metadata.",
    },
]


def list_aip_tool_catalog() -> List[Dict[str, str]]:
    return AIP_TOOL_CATALOG


def summarize_platform(db: Session) -> Dict[str, Any]:
    return {
        "object_types": db.query(models.ObjectType).count(),
        "object_instances": db.query(models.ObjectInstance).count(),
        "link_types": db.query(models.LinkType).count(),
        "action_types": db.query(models.ActionType).count(),
        "data_assets": db.query(models.DataAsset).count(),
        "pipelines": db.query(models.PipelineDefinition).count(),
        "agents": db.query(models.AgentDefinition).count(),
        "saved_object_sets": db.query(models.SavedObjectSet).count(),
        "map_layers": db.query(models.MapLayerDefinition).count(),
        "logic_functions": db.query(models.LogicFunction).count(),
        "automations": db.query(models.AutomationDefinition).count(),
        "eval_suites": db.query(models.EvalSuite).count(),
        "tools": len(AIP_TOOL_CATALOG),
    }


def build_mcp_context(db: Session) -> Dict[str, Any]:
    return {
        "tools": AIP_TOOL_CATALOG,
        "ontology": {
            "object_types": [
                {
                    "id": item.id,
                    "display_name": item.display_name,
                    "properties": item.properties,
                }
                for item in db.query(models.ObjectType).all()
            ],
            "link_types": [
                {
                    "id": item.id,
                    "display_name": item.display_name,
                    "source_object_type_id": item.source_object_type_id,
                    "target_object_type_id": item.target_object_type_id,
                    "cardinality": item.cardinality,
                }
                for item in db.query(models.LinkType).all()
            ],
            "action_types": [
                {
                    "id": item.id,
                    "display_name": item.display_name,
                    "parameters": item.parameters,
                    "rules": item.rules,
                }
                for item in db.query(models.ActionType).all()
            ],
        },
        "pipelines": [
            {
                "id": item.id,
                "display_name": item.display_name,
                "input_asset_id": item.input_asset_id,
                "output_asset_id": item.output_asset_id,
                "steps": item.steps,
            }
            for item in db.query(models.PipelineDefinition).all()
        ],
        "agents": [
            {
                "id": item.id,
                "display_name": item.display_name,
                "allowed_object_types": item.allowed_object_types,
                "allowed_actions": item.allowed_actions,
            }
            for item in db.query(models.AgentDefinition).all()
        ],
        "saved_object_sets": [
            {
                "id": item.id,
                "display_name": item.display_name,
                "object_type_id": item.object_type_id,
                "filters": item.filters,
            }
            for item in db.query(models.SavedObjectSet).all()
        ],
        "map_layers": [
            {
                "id": item.id,
                "display_name": item.display_name,
                "object_type_id": item.object_type_id,
                "saved_object_set_id": item.saved_object_set_id,
                "geometry_field": item.geometry_field,
                "style": item.style,
            }
            for item in db.query(models.MapLayerDefinition).all()
        ],
        "summary": summarize_platform(db),
    }


def answer_assist_query(
    db: Session,
    *,
    prompt: str,
    application_context: Optional[str] = None,
    include_mcp_context: bool = True,
) -> Dict[str, Any]:
    normalized = prompt.lower()
    matched_tools = [
        tool for tool in AIP_TOOL_CATALOG
        if tool["id"].replace("_", " ") in normalized
        or tool["display_name"].lower() in normalized
        or any(word in normalized for word in tool["display_name"].lower().split())
    ]

    if not matched_tools and application_context:
        context_text = application_context.lower()
        matched_tools = [
            tool for tool in AIP_TOOL_CATALOG
            if tool["id"].split("_")[0] in context_text or tool["display_name"].lower() in context_text
        ]

    if not matched_tools:
        matched_tools = AIP_TOOL_CATALOG[:4]

    summary = summarize_platform(db) if include_mcp_context else {}
    tool_names = ", ".join(tool["display_name"] for tool in matched_tools[:5])
    answer = (
        f"Relevant local AIP tools: {tool_names}. "
        "Use the listed endpoints to inspect ontology context, build pipelines, run logic, stage actions, "
        "and evaluate agent behavior. This helper uses local metadata and does not call external LLMs."
    )

    return {
        "answer": answer,
        "referenced_tools": [tool["id"] for tool in matched_tools],
        "suggested_endpoints": [tool["local_endpoint"] for tool in matched_tools],
        "context_summary": summary,
    }


def suggest_pipeline_from_prompt(prompt: str, sample_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    sample_fields = sample_fields or []
    normalized = prompt.lower()
    steps: List[Dict[str, Any]] = []
    rationale: List[str] = []

    if "open" in normalized or "filter" in normalized:
        field = "status" if "status" in sample_fields or not sample_fields else sample_fields[0]
        steps.append({"operation": "filter", "field": field, "equals": "OPEN"})
        rationale.append("Added a filter step because the prompt references filtering or open work.")

    if "clean" in normalized or "normalize" in normalized or "trim" in normalized:
        fields = [field for field in sample_fields if field not in {"id", "status"}] or sample_fields
        steps.append({"operation": "normalize", "fields": fields})
        rationale.append("Added normalization to trim and collapse whitespace in text fields.")

    if "classify" in normalized or "priority" in normalized or "sentiment" in normalized:
        field = "description" if "description" in sample_fields else (sample_fields[0] if sample_fields else "text")
        steps.append({
            "operation": "classify",
            "field": field,
            "target_field": "classification",
            "labels": {"high": ["urgent", "critical", "production"], "low": ["archive", "minor"]},
            "default": "normal",
        })
        rationale.append("Added a keyword classifier as a local deterministic equivalent to an LLM classification node.")

    if "summary" in normalized or "summarize" in normalized:
        field = "description" if "description" in sample_fields else (sample_fields[0] if sample_fields else "text")
        steps.append({"operation": "summarize", "field": field, "target_field": "summary", "max_chars": 160})
        rationale.append("Added summarization using bounded local text truncation.")

    if "ontology" in normalized or "hydrate" in normalized or "object" in normalized:
        object_id_field = "id" if "id" in sample_fields else None
        steps.append({
            "operation": "map_to_ontology",
            "object_type_id": "replace_with_object_type",
            "object_id_field": object_id_field,
            "property_map": {field: f"${field}" for field in sample_fields},
        })
        rationale.append("Added ontology hydration; replace the object type and property map with your domain schema.")

    if not steps:
        steps = [{"operation": "project", "fields": sample_fields}]
        rationale.append("No specific transform intent was detected, so a projection step was suggested.")

    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")[:48] or "generated_pipeline"
    return {
        "suggested_name": slug,
        "suggested_description": f"Generated pipeline plan from prompt: {prompt[:160]}",
        "steps": steps,
        "rationale": rationale,
    }


def extract_document_intelligence(text: str, extraction_schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    extraction_schema = extraction_schema or {}
    fields: Dict[str, Any] = {}

    for field, definition in extraction_schema.items():
        pattern = definition.get("pattern") if isinstance(definition, dict) else None
        if pattern:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            fields[field] = match.group(1) if match and match.groups() else (match.group(0) if match else None)

    key_value_pattern = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _-]{1,40})\s*[:=]\s*(.+?)\s*$", re.MULTILINE)
    for key, value in key_value_pattern.findall(text):
        fields.setdefault(key.strip().lower().replace(" ", "_"), value.strip())

    entities = {
        "emails": sorted(set(re.findall(r"[\w.\-+]+@[\w.\-]+\.\w+", text))),
        "dates": sorted(set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", text))),
        "money": sorted(set(re.findall(r"\$\s?\d+(?:,\d{3})*(?:\.\d{2})?", text))),
        "ids": sorted(set(re.findall(r"\b[A-Z]{2,}[-_]\d+\b", text))),
    }
    compact_text = re.sub(r"\s+", " ", text).strip()
    summary = compact_text[:240] + ("..." if len(compact_text) > 240 else "")
    populated = sum(1 for value in fields.values() if value)
    confidence = 0.45 + min(0.45, 0.05 * populated + 0.03 * sum(len(values) for values in entities.values()))

    return {
        "fields": fields,
        "entities": entities,
        "summary": summary,
        "confidence": round(confidence, 2),
    }


def transform_notepad_text(
    *,
    text: str,
    operation: str,
    instruction: Optional[str] = None,
    target_language: Optional[str] = None,
) -> Dict[str, str]:
    normalized = operation.lower()
    output = text
    notes = "Applied local deterministic transform."

    if normalized == "shorten":
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        output = " ".join(sentences[:2])[:280]
    elif normalized == "spellcheck":
        replacements = {"teh": "the", "recieve": "receive", "adress": "address", "occurence": "occurrence"}
        output = text
        for wrong, right in replacements.items():
            output = re.sub(rf"\b{wrong}\b", right, output, flags=re.IGNORECASE)
    elif normalized == "modify":
        prefix = f"{instruction.strip()}: " if instruction else ""
        output = f"{prefix}{text.strip()}"
    elif normalized == "translate":
        language = target_language or "requested language"
        output = text
        notes = f"Translation requested for {language}; local runtime records intent but does not call a translation model."
    else:
        notes = f"Unknown operation '{operation}', returned input unchanged."

    return {"operation": operation, "text": output, "notes": notes}


def generate_cron_from_prompt(prompt: str) -> Dict[str, str]:
    normalized = prompt.lower()
    cron = "0 9 * * *"
    explanation = "Defaulted to every day at 09:00 UTC."

    if "hour" in normalized:
        cron = "0 * * * *"
        explanation = "Runs at the start of every hour."
    elif "weekday" in normalized or "business day" in normalized:
        cron = "0 9 * * 1-5"
        explanation = "Runs at 09:00 UTC Monday through Friday."
    elif "weekly" in normalized or "monday" in normalized:
        cron = "0 9 * * 1"
        explanation = "Runs every Monday at 09:00 UTC."
    elif "monthly" in normalized:
        cron = "0 9 1 * *"
        explanation = "Runs on the first day of each month at 09:00 UTC."
    elif "midnight" in normalized:
        cron = "0 0 * * *"
        explanation = "Runs every day at midnight UTC."

    return {"cron": cron, "timezone": "UTC", "explanation": explanation}


def _logic_cmp(op: str, left: Any, right: Any) -> bool:
    """Comparison operators for AIP Logic conditional/condition evaluation."""
    try:
        if op in ("eq", "=="):
            return left == right
        if op in ("ne", "!="):
            return left != right
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
        if op == "in":
            return left in (right or [])
        if op == "contains":
            return str(right) in str(left)
        if op == "not_null":
            return left is not None
        if op == "truthy":
            return bool(left)
    except TypeError:
        return False
    return False


def _logic_object_rows(db: Session, object_type_id: str, filters: Dict[str, Any], limit: int = 1000,
                       project_id: Optional[str] = None):
    """Query an object set with simple equality filters (AIP Logic 'Query Objects')."""
    instances = (
        db.query(models.ObjectInstance)
        .filter(
            models.ObjectInstance.object_type_id == object_type_id,
            *([models.ObjectInstance.project_id == project_id] if project_id is not None else []),
        )
        .all()
    )
    filters = filters or {}
    matched = [
        i for i in instances
        if all((i.properties or {}).get(k) == v for k, v in filters.items())
    ]
    return matched[: int(limit)], len(matched)


def _eval_logic_condition(condition: Dict[str, Any], scope: Dict[str, Any], db: Session) -> bool:
    """Evaluate an AIP Logic condition against the current variable scope."""
    if not condition:
        return True
    if "object_count" in condition:
        spec = condition["object_count"]
        _, count = _logic_object_rows(db, spec.get("object_type_id"), spec.get("filters", {}), limit=10 ** 9)
        return _logic_cmp(condition.get("op", "gt"), count, condition.get("value", 0))
    left = resolve_value(condition.get("left"), scope)
    right = resolve_value(condition.get("right"), scope)
    return _logic_cmp(condition.get("op", "truthy"), left, right)


def _deterministic_llm(block: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    """A local, deterministic stand-in for an AIP Logic 'Use LLM' block.

    No network calls. Supports echo/template/summarize/classify/extract modes so
    Logic functions can be authored and exercised exactly as documented while the
    platform stays deterministic by default.
    """
    mode = block.get("mode", "echo")
    prompt = str(resolve_value(block.get("prompt", "$prompt"), scope) or "")
    if mode == "template":
        try:
            response: Any = str(block.get("template", "")).format(**scope)
        except Exception:
            response = block.get("template", "")
    elif mode == "summarize":
        words = prompt.split()
        max_words = int(block.get("max_words", 30))
        response = " ".join(words[:max_words]) + (" ..." if len(words) > max_words else "")
    elif mode == "classify":
        labels = block.get("labels", [])
        lowered = prompt.lower()
        response = next((lbl for lbl in labels if str(lbl).lower() in lowered), (labels[0] if labels else "unknown"))
    elif mode == "extract":
        response = extract_document_intelligence(prompt, block.get("extraction_schema", {}))
    else:  # echo
        response = prompt
    return {"mode": mode, "prompt": prompt, "response": response}


def _exec_logic_block_list(
    db: Session,
    *,
    logic_function: models.LogicFunction,
    blocks: List[Dict[str, Any]],
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    trace: List[Dict[str, Any]],
    proposed_actions: List[Dict[str, Any]],
    loop_scope: Dict[str, Any],
    depth: int = 0,
) -> None:
    for index, block in enumerate(blocks or []):
        block_type = block.get("type") or block.get("operation")
        # Variable scope chains inputs + loop variables + accumulated block outputs.
        scope = {**inputs, **loop_scope, **outputs}
        result: Dict[str, Any] = {}

        if block_type == "retrieve_context":
            result = build_context_pack(
                db,
                allowed_object_types=block.get("object_types", []),
                filters=block.get("filters", {}),
                limit=int(block.get("limit", 5)),
            )
            outputs[block.get("output", "context")] = result
        elif block_type == "assist":
            prompt = resolve_value(block.get("prompt", "$prompt"), scope) or scope.get("prompt", "")
            result = answer_assist_query(db, prompt=str(prompt), application_context=block.get("application_context"))
            outputs[block.get("output", "assist")] = result
        elif block_type == "document_extract":
            text = resolve_value(block.get("text", "$text"), scope) or ""
            result = extract_document_intelligence(str(text), block.get("extraction_schema", {}))
            outputs[block.get("output", "document")] = result
        elif block_type == "pipeline_suggest":
            prompt = resolve_value(block.get("prompt", "$prompt"), scope) or scope.get("prompt", "")
            result = suggest_pipeline_from_prompt(str(prompt), block.get("sample_fields", []))
            outputs[block.get("output", "pipeline")] = result
        elif block_type == "notepad_transform":
            text = resolve_value(block.get("text", "$text"), scope) or ""
            result = transform_notepad_text(
                text=str(text),
                operation=block.get("operation_name", "shorten"),
                instruction=block.get("instruction"),
                target_language=block.get("target_language"),
            )
            outputs[block.get("output", "text")] = result
        elif block_type == "propose_action":
            action_id = block["action_type_id"]
            action = db.query(models.ActionType).filter(models.ActionType.id == action_id).first()
            if not action:
                raise ValueError(f"ActionType '{action_id}' not found")
            parameters = {
                key: resolve_value(value, scope)
                for key, value in (block.get("parameters") or {}).items()
            }
            proposal = {
                "action_type_id": action.id,
                "display_name": action.display_name,
                "parameters": parameters,
                "requires_approval": bool(logic_function.approval_required or (action.rules or {}).get("requires_approval")),
            }
            proposed_actions.append(proposal)
            result = proposal
            outputs[block.get("output", "proposed_action")] = proposal
        elif block_type in ("set_output", "set_variable"):
            key = block.get("key", "value")
            value = resolve_value(block.get("value"), scope)
            outputs[key] = value
            result = {key: value}
        # --- documented control flow & tool blocks ---
        elif block_type == "llm":
            result = _deterministic_llm(block, scope)
            outputs[block.get("output", "llm")] = result
        elif block_type == "object_query":
            rows, count = _logic_object_rows(
                db, block.get("object_type_id"), block.get("filters", {}), int(block.get("limit", 1000))
            )
            result = {
                "object_type_id": block.get("object_type_id"),
                "count": count,
                "rows": [{"id": i.id, "properties": i.properties} for i in rows],
            }
            outputs[block.get("output", "query")] = result
        elif block_type == "object_aggregate":
            rows, count = _logic_object_rows(
                db, block.get("object_type_id"), block.get("filters", {}), limit=10 ** 9
            )
            op = block.get("op", "count")
            field = block.get("field")
            nums = [
                (i.properties or {}).get(field)
                for i in rows
                if isinstance((i.properties or {}).get(field), (int, float)) and not isinstance((i.properties or {}).get(field), bool)
            ]
            if op == "count":
                value: Any = count
            elif op == "sum":
                value = sum(nums)
            elif op == "avg":
                value = (sum(nums) / len(nums)) if nums else 0
            elif op == "min":
                value = min(nums) if nums else None
            elif op == "max":
                value = max(nums) if nums else None
            else:
                raise ValueError(f"Unsupported aggregate op '{op}'")
            result = {"op": op, "field": field, "value": value, "count": count}
            outputs[block.get("output", "aggregate")] = result
        elif block_type == "explain_object":
            from . import decision_intelligence
            object_type_id = resolve_value(block.get("object_type_id"), scope) or block.get("object_type_id")
            object_id = resolve_value(block.get("object_id"), scope) or block.get("object_id")
            if not object_type_id or not object_id:
                raise ValueError("explain_object requires object_type_id and object_id")
            result = decision_intelligence.explain_object_by_id(db, str(object_type_id), str(object_id))
            outputs[block.get("output", "explanation")] = result
        elif block_type == "score_risk":
            from . import decision_intelligence
            object_type_id = resolve_value(block.get("object_type_id"), scope) or block.get("object_type_id")
            object_id = resolve_value(block.get("object_id"), scope) or block.get("object_id")
            scorecard_ids = block.get("scorecard_ids") or []
            if isinstance(scorecard_ids, str):
                scorecard_ids = [item.strip() for item in scorecard_ids.split(",") if item.strip()]
            if not object_type_id or not object_id:
                raise ValueError("score_risk requires object_type_id and object_id")
            result = decision_intelligence.score_object_by_id(db, str(object_type_id), str(object_id), scorecard_ids=scorecard_ids)
            outputs[block.get("output", "risk")] = result
        elif block_type == "run_scenario":
            from . import decision_intelligence
            seed_object_ids = resolve_value(block.get("seed_object_ids"), scope) or block.get("seed_object_ids") or []
            if isinstance(seed_object_ids, str):
                seed_object_ids = [item.strip() for item in seed_object_ids.split(",") if item.strip()]
            overrides = block.get("overrides") or {}
            propagation_rules = block.get("propagation_rules") or []
            result = decision_intelligence.run_scenario_inline(
                db,
                seed_object_ids=seed_object_ids,
                overrides=overrides,
                propagation_rules=propagation_rules,
            )
            outputs[block.get("output", "scenario")] = result
        elif block_type == "create_incident":
            from . import ops_control
            linked_objects = block.get("linked_objects") or []
            if isinstance(linked_objects, str):
                linked_objects = resolve_value(linked_objects, scope) or []
            incident = ops_control.create_incident_inline(
                db,
                display_name=str(resolve_value(block.get("display_name"), scope) or block.get("display_name") or "Logic Incident"),
                description=resolve_value(block.get("description"), scope) or block.get("description"),
                severity=str(resolve_value(block.get("severity"), scope) or block.get("severity") or "medium"),
                owner=resolve_value(block.get("owner"), scope) or block.get("owner"),
                linked_objects=linked_objects,
                alert_ids=block.get("alert_ids") or [],
                approval_ids=block.get("approval_ids") or [],
                actor=block.get("actor", "logic"),
            )
            result = ops_control._incident_dict(incident)
            outputs[block.get("output", "incident")] = result
        elif block_type == "evaluate_alert_rules":
            from . import ops_control
            result = ops_control.evaluate_alert_rules_inline(
                db,
                limit=int(block.get("limit", 500)),
                source=block.get("source"),
                event_type=block.get("event_type"),
                status=block.get("status"),
            )
            outputs[block.get("output", "alerts")] = result
        elif block_type == "run_runbook":
            from . import ops_control
            runbook_id = resolve_value(block.get("runbook_id"), scope) or block.get("runbook_id")
            if not runbook_id:
                raise ValueError("run_runbook requires runbook_id")
            inputs = {
                key: resolve_value(value, scope)
                for key, value in (block.get("inputs") or {}).items()
            }
            incident_id = resolve_value(block.get("incident_id"), scope) or block.get("incident_id")
            result = ops_control.execute_runbook_inline(
                db,
                runbook_id=str(runbook_id),
                incident_id=incident_id,
                inputs=inputs,
                actor=block.get("actor", "logic"),
            )
            outputs[block.get("output", "runbook")] = result
        elif block_type == "run_data_contract":
            from . import reliability_ops
            contract_id = resolve_value(block.get("contract_id"), scope) or block.get("contract_id")
            asset_id = resolve_value(block.get("asset_id"), scope) or block.get("asset_id")
            if not contract_id:
                raise ValueError("run_data_contract requires contract_id")
            result = reliability_ops.run_data_contract_inline(db, contract_id=str(contract_id), asset_id=asset_id)
            outputs[block.get("output", "data_contract")] = result
        elif block_type == "analyze_lineage_impact":
            from . import reliability_ops
            resource_kind = resolve_value(block.get("resource_kind"), scope) or block.get("resource_kind") or "dataset"
            resource_id = resolve_value(block.get("resource_id"), scope) or block.get("resource_id")
            if not resource_id:
                raise ValueError("analyze_lineage_impact requires resource_id")
            result = reliability_ops.analyze_lineage_impact_inline(
                db,
                resource_kind=str(resource_kind),
                resource_id=str(resource_id),
                direction=block.get("direction", "downstream"),
                max_depth=int(block.get("max_depth", 8)),
            )
            outputs[block.get("output", "lineage_impact")] = result
        elif block_type == "apply_action":
            action_id = block["action_type_id"]
            action = db.query(models.ActionType).filter(models.ActionType.id == action_id).first()
            if not action:
                raise ValueError(f"ActionType '{action_id}' not found")
            parameters = {
                key: resolve_value(value, scope)
                for key, value in (block.get("parameters") or {}).items()
            }
            mutated = apply_action_mutations(
                db, action_type=action, parameters=parameters, actor=block.get("actor", "logic")
            )
            result = {"action_type_id": action.id, "mutated_object_ids": mutated}
            outputs[block.get("output", "applied_action")] = result
        elif block_type == "conditional":
            condition_met = _eval_logic_condition(block.get("condition", {}), scope, db)
            branch = block.get("then", []) if condition_met else block.get("else", [])
            _exec_logic_block_list(
                db, logic_function=logic_function, blocks=branch, inputs=inputs, outputs=outputs,
                trace=trace, proposed_actions=proposed_actions, loop_scope=loop_scope, depth=depth + 1,
            )
            result = {"condition": condition_met, "branch": "then" if condition_met else "else"}
        elif block_type == "for_each":
            items = resolve_value(block.get("items"), scope)
            if items is None and block.get("object_type_id"):
                rows, _ = _logic_object_rows(db, block.get("object_type_id"), block.get("filters", {}), int(block.get("limit", 1000)))
                items = [{"id": i.id, "properties": i.properties} for i in rows]
            item_var = block.get("item_var", "item")
            iterations = 0
            for idx, item in enumerate(items or []):
                nested_loop_scope = {**loop_scope, item_var: item, "loop_index": idx}
                _exec_logic_block_list(
                    db, logic_function=logic_function, blocks=block.get("blocks", []), inputs=inputs,
                    outputs=outputs, trace=trace, proposed_actions=proposed_actions,
                    loop_scope=nested_loop_scope, depth=depth + 1,
                )
                iterations += 1
            result = {"iterations": iterations, "item_var": item_var}
        else:
            raise ValueError(f"Unsupported logic block '{block_type}'")

        trace.append({"index": index, "depth": depth, "type": block_type, "result": result})


def execute_logic_blocks(
    db: Session,
    *,
    logic_function: models.LogicFunction,
    inputs: Dict[str, Any],
) -> Dict[str, Any]:
    outputs: Dict[str, Any] = {}
    trace: List[Dict[str, Any]] = []
    proposed_actions: List[Dict[str, Any]] = []
    _exec_logic_block_list(
        db,
        logic_function=logic_function,
        blocks=logic_function.blocks or [],
        inputs=inputs,
        outputs=outputs,
        trace=trace,
        proposed_actions=proposed_actions,
        loop_scope={},
    )
    return {"outputs": outputs, "trace": trace, "proposed_actions": proposed_actions}


def _compare_count(count: int, operator: str, threshold: int) -> bool:
    if operator == ">":
        return count > threshold
    if operator == ">=":
        return count >= threshold
    if operator == "<":
        return count < threshold
    if operator == "<=":
        return count <= threshold
    if operator in {"=", "=="}:
        return count == threshold
    return False


def evaluate_automation(
    db: Session,
    *,
    automation: models.AutomationDefinition,
    actor: str = "automation",
) -> Dict[str, Any]:
    condition = automation.condition or {}
    effect = automation.effect or {}
    condition_result = False
    effect_result: Dict[str, Any] = {"status": "SKIPPED"}

    if not automation.enabled:
        return {"condition_result": False, "effect_result": {"status": "DISABLED"}}

    if condition.get("type") == "object_count":
        object_type_id = condition["object_type_id"]
        context = build_context_pack(
            db,
            allowed_object_types=[object_type_id],
            filters={object_type_id: condition.get("filters", {})},
            limit=100000,
        )
        count = len(context["packs"][0]["objects"]) if context["packs"] else 0
        condition_result = _compare_count(count, condition.get("operator", ">"), int(condition.get("threshold", 0)))
    elif condition.get("type") in {None, "always"}:
        condition_result = True

    if condition_result:
        if effect.get("type") == "request_approval":
            approval_id = str(uuid.uuid4())
            action = db.get(models.ActionType, effect["action_type_id"])
            if not action:
                raise ValueError(f"ActionType '{effect['action_type_id']}' not found")
            approval = models_action.ApprovalRequest(
                id=approval_id,
                project_id=action.project_id,
                action_type_id=effect["action_type_id"],
                requester=actor,
                parameters=effect.get("parameters", {}),
                status=models_action.ApprovalStatus.PENDING.value,
            )
            db.add(approval)
            effect_result = {"status": "APPROVAL_REQUESTED", "approval_request_id": approval_id}
        elif effect.get("type") == "emit_audit":
            effect_result = {"status": "AUDIT_EMITTED", "payload": effect.get("payload", {})}
        else:
            effect_result = {"status": "NO_EFFECT", "effect": effect}

    return {"condition_result": condition_result, "effect_result": effect_result}
