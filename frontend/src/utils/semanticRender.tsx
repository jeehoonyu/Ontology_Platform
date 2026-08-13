/**
 * Render property values by the base type the ontology declares for them.
 *
 * The ontology records 21 base types and a render hint per property, and until
 * now the product read none of it: every value reached the user through a
 * generic stringifier, so a geoshape arrived as raw GeoJSON text, a marking as
 * its identifier and a decimal without its unit. The model knew more than the
 * product showed.
 *
 * This is the consumption half of that. A renderer is chosen from the declared
 * base type, so a new object type carrying a geopoint is drawn as a location
 * without anyone editing a component. That is the point: the cost of the next
 * object type should not include UI work.
 *
 * Unknown or undeclared types fall through to the existing formatter rather
 * than erroring, because most properties in a legacy bag have no declared type
 * and must keep rendering exactly as they did.
 */
import type { ReactNode } from "react";
import { formatValue } from "./format";

export interface PropertySpec {
  base_type?: string;
  unit?: string;
  render_hint?: string;
  display_name?: string;
  sensitive?: boolean;
}

const NUMBER_FORMAT = new Intl.NumberFormat();

function coordinatePair(value: unknown): [number, number] | null {
  if (Array.isArray(value) && value.length >= 2) {
    const [lon, lat] = value;
    if (typeof lon === "number" && typeof lat === "number") return [lon, lat];
  }
  return null;
}

/** Degrees with a hemisphere letter reads as a place; a raw array does not. */
function formatPoint(lon: number, lat: number): string {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(5)}° ${ns}, ${Math.abs(lon).toFixed(5)}° ${ew}`;
}

function geoPoint(value: unknown): ReactNode {
  const direct = coordinatePair(value);
  if (direct) return <span className="semantic-geo">{formatPoint(direct[0], direct[1])}</span>;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const fromGeoJson = coordinatePair(record.coordinates);
    if (fromGeoJson) return <span className="semantic-geo">{formatPoint(fromGeoJson[0], fromGeoJson[1])}</span>;
    const lat = record.lat ?? record.latitude;
    const lon = record.lon ?? record.lng ?? record.longitude;
    if (typeof lat === "number" && typeof lon === "number") {
      return <span className="semantic-geo">{formatPoint(lon, lat)}</span>;
    }
  }
  return null;
}

function geoShape(value: unknown): ReactNode {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const kind = typeof record.type === "string" ? record.type : null;
  if (!kind) return null;
  if (kind === "Point") return geoPoint(record);
  // A polygon's vertex list is not information a reader can use; its shape and
  // size are. Counting positions keeps the summary honest without dumping it.
  const positions = countPositions(record.coordinates);
  const label = positions === null ? kind : `${kind}, ${NUMBER_FORMAT.format(positions)} points`;
  return <span className="semantic-geo">{label}</span>;
}

function countPositions(coordinates: unknown): number | null {
  if (!Array.isArray(coordinates)) return null;
  if (coordinatePair(coordinates)) return 1;
  let total = 0;
  for (const entry of coordinates) {
    const nested = countPositions(entry);
    if (nested === null) return null;
    total += nested;
  }
  return total;
}

function temporal(value: unknown, withTime: boolean): ReactNode {
  const date =
    typeof value === "number"
      ? new Date(value > 1e12 ? value : value * 1000)
      : typeof value === "string"
        ? new Date(value)
        : null;
  if (!date || Number.isNaN(date.getTime())) return null;
  // Rendered in the viewer's zone. An epoch integer is not a time to a reader.
  const text = withTime ? date.toLocaleString() : date.toLocaleDateString();
  return (
    <time className="semantic-time" dateTime={date.toISOString()}>
      {text}
    </time>
  );
}

function quantity(value: unknown, unit?: string): ReactNode {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  const text = NUMBER_FORMAT.format(value);
  return <span className="semantic-quantity">{unit ? `${text} ${unit}` : text}</span>;
}

function marking(value: unknown): ReactNode {
  const label = typeof value === "string" ? value : formatValue(value);
  if (!label) return null;
  // A classification marking is a control, not a string. Rendering it as a chip
  // makes it visible as one.
  return <span className="semantic-marking">{label.toUpperCase()}</span>;
}

function reference(value: unknown, kind: string): ReactNode {
  if (!value) return null;
  const record = typeof value === "object" ? (value as Record<string, unknown>) : null;
  const label = record
    ? String(record.display_name ?? record.name ?? record.filename ?? record.id ?? kind)
    : String(value);
  return (
    <span className="semantic-reference" title={kind}>
      {label}
    </span>
  );
}

function vector(value: unknown): ReactNode {
  if (!Array.isArray(value)) return null;
  // An embedding is not readable and pasting hundreds of floats into a table
  // destroys the row. Its dimensionality is the useful fact.
  return <span className="semantic-vector">{`${NUMBER_FORMAT.format(value.length)}-dim vector`}</span>;
}

function collection(value: unknown): ReactNode {
  if (Array.isArray(value)) {
    return <span className="semantic-collection">{`${NUMBER_FORMAT.format(value.length)} items`}</span>;
  }
  if (value && typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>);
    return <span className="semantic-collection">{`${NUMBER_FORMAT.format(keys.length)} fields`}</span>;
  }
  return null;
}

/**
 * Choose a renderer from the declared base type.
 *
 * Returns null when the type is unknown or the value does not match it, so the
 * caller falls back to the generic formatter instead of showing nothing.
 */
export function renderByBaseType(value: unknown, spec?: PropertySpec): ReactNode | null {
  if (value === null || value === undefined) return null;
  const baseType = spec?.base_type;
  if (!baseType) return null;

  switch (baseType) {
    case "geopoint":
      return geoPoint(value);
    case "geoshape":
    case "geometry":
    case "geojson":
      return geoShape(value) ?? geoPoint(value);
    case "timestamp":
      return temporal(value, true);
    case "date":
      return temporal(value, false);
    case "decimal":
    case "double":
    case "float":
      return quantity(value, spec?.unit);
    case "integer":
    case "long":
    case "short":
    case "byte":
      return spec?.unit ? quantity(value, spec.unit) : null;
    case "marking":
      return marking(value);
    case "attachment":
      return reference(value, "attachment");
    case "mediaReference":
      return reference(value, "media");
    case "timeSeries":
      return reference(value, "time series");
    case "vector":
      return vector(value);
    case "struct":
    case "array":
      return collection(value);
    case "cipherText":
      // Ciphertext is deliberately unreadable; showing the blob invites someone
      // to try to read it and widens what a screenshot leaks.
      return <span className="semantic-cipher">encrypted</span>;
    default:
      return null;
  }
}

/** Render a property value, falling back to the generic formatter. */
export function renderPropertyValue(value: unknown, spec?: PropertySpec): ReactNode {
  return renderByBaseType(value, spec) ?? formatValue(value);
}

/**
 * Legacy JSON-schema type names mapped onto the ontology base vocabulary.
 *
 * Mirrors _LEGACY_TO_BASE in ontology_interfaces_ops.py. Object types that
 * predate a normalized profile still carry a JSON-schema style type, and
 * translating it here means those types render semantically too rather than
 * waiting for every object type in a deployment to be normalized.
 */
const LEGACY_TYPE_TO_BASE: Record<string, string> = {
  string: "string",
  integer: "integer",
  number: "double",
  boolean: "boolean",
  array: "array",
  object: "struct",
  json: "struct",
  geometry: "geoshape",
  geojson: "geoshape",
};

/**
 * Build a property-name to spec map from whatever the caller has.
 *
 * The normalized profile is authoritative because it records real base types,
 * units and render hints. The legacy bag is the fallback. Callers pass whichever
 * they hold; a surface with neither renders exactly as it did before.
 */
export function propertySpecs(
  legacyProperties?: Record<string, unknown> | null,
  profileProperties?: Record<string, unknown> | null,
): Record<string, PropertySpec> {
  const specs: Record<string, PropertySpec> = {};
  for (const [name, raw] of Object.entries(legacyProperties || {})) {
    const declared = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
    const legacy = typeof declared.type === "string" ? declared.type.toLowerCase() : "";
    const baseType = LEGACY_TYPE_TO_BASE[legacy];
    if (baseType) {
      specs[name] = { base_type: baseType, unit: typeof declared.unit === "string" ? declared.unit : undefined };
    }
  }
  for (const [name, raw] of Object.entries(profileProperties || {})) {
    const declared = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
    if (typeof declared.base_type === "string" && declared.base_type) {
      specs[name] = {
        base_type: declared.base_type,
        unit: typeof declared.unit === "string" ? declared.unit : undefined,
        render_hint: typeof declared.render_hint === "string" ? declared.render_hint : undefined,
        sensitive: declared.sensitive === true,
      };
    }
  }
  return specs;
}
