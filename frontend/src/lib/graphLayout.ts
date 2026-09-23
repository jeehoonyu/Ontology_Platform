/**
 * Where nodes go when a graph is laid out for a person rather than by one.
 *
 * X3 of `GOAL_GRAPH_2026-09-23.md`. `PlatformGraph` had `Auto layout` and the
 * pipeline canvas, the one a person builds node by node, did not. Both place nodes
 * in columns, top to bottom; they differ in what decides the column. The platform
 * graph gives each kind of resource a column. A pipeline gives each node the layer
 * its data reaches it in, so a flow reads left to right.
 */

export interface Spacing {
  /** Distance between columns, and between rows in a column. */
  x: number;
  y: number;
  originX?: number;
  originY?: number;
}

/**
 * Items in columns, each column filled top to bottom in the order the items come.
 * The caller orders them; this only places.
 */
export function columnLayout<T>(items: T[], idOf: (item: T) => string, columnOf: (item: T) => number,
                                spacing: Spacing): Map<string, { x: number; y: number }> {
  const rows = new Map<number, number>();
  const placed = new Map<string, { x: number; y: number }>();
  for (const item of items) {
    const column = columnOf(item);
    const row = rows.get(column) || 0;
    rows.set(column, row + 1);
    placed.set(idOf(item), {
      x: (spacing.originX ?? 0) + column * spacing.x,
      y: (spacing.originY ?? 0) + row * spacing.y,
    });
  }
  return placed;
}

/**
 * The layer of every node: 0 for a node nothing flows into, and otherwise one past
 * the deepest node that flows into it, so every edge points to a later column.
 *
 * A pipeline should have no cycle, and one that does must still lay out rather
 * than lose its nodes: a node the ordering never reaches takes one past the deepest
 * node it was reached from, or 0.
 */
export function layersOf(ids: string[], edges: Array<{ source: string; target: string }>): Map<string, number> {
  const known = new Set(ids);
  const inward = new Map(ids.map((id) => [id, 0]));
  const outward = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const edge of edges) {
    if (!known.has(edge.source) || !known.has(edge.target) || edge.source === edge.target) continue;
    outward.get(edge.source)?.push(edge.target);
    inward.set(edge.target, (inward.get(edge.target) || 0) + 1);
  }
  const layer = new Map(ids.map((id) => [id, 0]));
  const ready = ids.filter((id) => !inward.get(id));
  while (ready.length) {
    const id = ready.shift() as string;
    for (const next of outward.get(id) || []) {
      layer.set(next, Math.max(layer.get(next) || 0, (layer.get(id) || 0) + 1));
      const remaining = (inward.get(next) || 0) - 1;
      inward.set(next, remaining);
      if (remaining === 0) ready.push(next);
    }
  }
  return layer;
}
