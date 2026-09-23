/**
 * Where each pane on a screen sits, and how that survives a reload.
 *
 * M2 of `GOAL_PANES_2026-09-11.md`. Before this, no pane on any screen could be
 * moved, collapsed or hidden by the person using it: every one was a fixed CSS
 * grid track decided at build time. `oms/audit_pane_layout.py` counted 21 of
 * them, 0 movable.
 *
 * A layout is a **viewing preference**. It is never shared through
 * collaboration, never sent to the server, and never part of an artifact
 * revision. That is a decision rather than a deferral: two people looking at the
 * same pipeline should be able to arrange their own screens differently, and a
 * layout that travelled with the document would make one person's tidy-up
 * everyone's.
 *
 * The part worth reading is `reconcile`. A stored layout is written by an older
 * build than the one reading it, so it names panes that may be gone and omits
 * panes that did not exist yet. Trusting it would mean a release that adds a
 * pane ships it invisible to everyone who had ever arranged that screen — the
 * bug is silent, it only affects people who used the feature, and it looks like
 * the pane was never built.
 */

export type SlotName = "left" | "center" | "right" | "bottom";

export const SLOTS: SlotName[] = ["left", "center", "right", "bottom"];

export interface PaneSpec {
  id: string;
  title: string;
  /** Where it sits until the person moves it. */
  slot: SlotName;
  /** The canvas. It may be resized around, never moved or hidden. */
  anchored?: boolean;
  /**
   * Starting width of this pane's side slot, before anyone resizes it. M7: the
   * artifact canvases' library and inspector were 238 and 310 pixels as fixed
   * tracks, and dropping them to the 220 default on the way onto `Pane` would
   * have squeezed the inspector's forms to fit a number chosen for another screen.
   *
   * A ceiling, not a promise: `sideWidth` gives a side slot at most a third of the
   * row until someone chooses a width, so the canvas stays the widest pane.
   */
  width?: number;
}

export interface PaneLayout {
  slots: Record<SlotName, string[]>;
  /**
   * Pixels per slot that a person chose, clamped. The splitter and the width
   * presets write these; M3 and V3. A slot nobody sized has no entry, and takes
   * its declared width through `sideWidth`.
   */
  sizes: Partial<Record<SlotName, number>>;
  collapsed: string[];
  hidden: string[];
}

export const DEFAULT_SLOT_PX = 220;
export const MIN_SLOT_PX = 160;
export const MAX_SLOT_PX = 640;

/** The widths a slot can be given with one choice and no drag. V3 of GOAL_MOVEMENT. */
export const WIDTH_PRESETS: Array<[string, number]> = [
  ["Narrow", MIN_SLOT_PX],
  ["Default", DEFAULT_SLOT_PX],
  ["Wide", 400],
  ["Widest", MAX_SLOT_PX],
];

const KEY_PREFIX = "ontology.panes.";

export function clampSize(px: number): number {
  return Math.max(MIN_SLOT_PX, Math.min(MAX_SLOT_PX, Math.round(px)));
}

export function defaultLayout(panes: PaneSpec[]): PaneLayout {
  const slots = { left: [], center: [], right: [], bottom: [] } as Record<SlotName, string[]>;
  for (const pane of panes) slots[pane.slot].push(pane.id);
  return { slots, sizes: {}, collapsed: [], hidden: [] };
}

/** The width a screen declares for a side slot: its first pane's, or the default. */
export function declaredWidth(panes: PaneSpec[], slot: SlotName): number {
  const declared = panes.find((pane) => pane.slot === slot && pane.width);
  return declared?.width ? clampSize(declared.width) : DEFAULT_SLOT_PX;
}

/**
 * What the row spends besides the three slots: two 7px splitters and four 8px
 * gaps with both sides occupied, or one splitter, three gaps and the 14px strip
 * of an empty side. 48 covers both.
 */
export const ROW_OVERHEAD_PX = 48;

/**
 * The width a side slot takes, given the row it sits in.
 *
 * S3 of `GOAL_SHELL_2026-09-23.md`. A chosen width is kept exactly: the person
 * asked for it. A declared width is a ceiling, capped at a third of what the row
 * has after its splitters and gaps, which leaves the canvas at least as wide as
 * either side. Measured before this: Workshop's canvas was 205px beside a 310px
 * inspector at 1101, and 150px at 760. `rowWidth` is 0 until the row is measured,
 * and then nothing is capped.
 */
export function sideWidth(layout: PaneLayout, panes: PaneSpec[], slot: SlotName, rowWidth: number): number {
  const chosen = layout.sizes[slot];
  if (typeof chosen === "number") return chosen;
  const declared = declaredWidth(panes, slot);
  if (rowWidth <= 0) return declared;
  const third = Math.floor((rowWidth - ROW_OVERHEAD_PX) / 3);
  return Math.min(declared, Math.max(MIN_SLOT_PX, third));
}

/**
 * A stored layout, made safe against the panes this build actually has.
 *
 * Unknown ids are dropped, known ids appear exactly once, and a pane the stored
 * layout never heard of lands in the slot its spec declares rather than
 * nowhere. An anchored pane cannot be hidden however the stored value got that
 * way, because a canvas nobody can bring back is not a layout, it is a dead end.
 */
export function reconcile(stored: Partial<PaneLayout> | null, panes: PaneSpec[]): PaneLayout {
  const base = defaultLayout(panes);
  if (!stored || typeof stored !== "object") return base;

  const known = new Map(panes.map((pane) => [pane.id, pane]));
  const placed = new Set<string>();
  const slots = { left: [], center: [], right: [], bottom: [] } as Record<SlotName, string[]>;

  for (const slot of SLOTS) {
    for (const id of stored.slots?.[slot] || []) {
      if (!known.has(id) || placed.has(id)) continue;
      const spec = known.get(id) as PaneSpec;
      // An anchored pane keeps its declared slot; only its neighbours move.
      slots[spec.anchored ? spec.slot : slot].push(id);
      placed.add(id);
    }
  }
  for (const pane of panes) {
    if (!placed.has(pane.id)) slots[pane.slot].push(pane.id);
  }

  // A stored layout that never resized a slot keeps the screen's declared width.
  // Builds before S3 stored the declared width itself whenever they saved, which
  // reads the same as a choice; a stored width equal to the declared one is taken
  // as no choice, so it keeps the cap a declared width has.
  const sizes: Partial<Record<SlotName, number>> = {};
  for (const slot of SLOTS) {
    const value = stored.sizes?.[slot];
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    if (clampSize(value) === declaredWidth(panes, slot)) continue;
    sizes[slot] = clampSize(value);
  }

  const keep = (ids: unknown) => (Array.isArray(ids) ? ids : [])
    .filter((id): id is string => typeof id === "string" && known.has(id));

  return {
    slots,
    sizes,
    collapsed: keep(stored.collapsed),
    hidden: keep(stored.hidden).filter((id) => !known.get(id)?.anchored),
  };
}

export function loadLayout(screen: string, panes: PaneSpec[]): PaneLayout {
  try {
    const raw = window.localStorage.getItem(KEY_PREFIX + screen);
    return reconcile(raw ? JSON.parse(raw) : null, panes);
  } catch {
    // A private window, cleared site data, or a browser that throws on access.
    // A layout nobody can store is still a layout that renders.
    return defaultLayout(panes);
  }
}

export function saveLayout(screen: string, layout: PaneLayout): void {
  try {
    window.localStorage.setItem(KEY_PREFIX + screen, JSON.stringify(layout));
  } catch {
    /* not being able to remember the arrangement must not break using it */
  }
}

export function clearLayout(screen: string): void {
  try {
    window.localStorage.removeItem(KEY_PREFIX + screen);
  } catch {
    /* as above */
  }
}

export function movePane(layout: PaneLayout, id: string, to: SlotName): PaneLayout {
  const slots = { left: [], center: [], right: [], bottom: [] } as Record<SlotName, string[]>;
  for (const slot of SLOTS) slots[slot] = layout.slots[slot].filter((item) => item !== id);
  slots[to].push(id);
  return { ...layout, slots, hidden: layout.hidden.filter((item) => item !== id) };
}

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}

export function toggleCollapsed(layout: PaneLayout, id: string): PaneLayout {
  return { ...layout, collapsed: toggle(layout.collapsed, id) };
}

export function toggleHidden(layout: PaneLayout, id: string): PaneLayout {
  return { ...layout, hidden: toggle(layout.hidden, id) };
}

export function setSize(layout: PaneLayout, slot: SlotName, px: number): PaneLayout {
  return { ...layout, sizes: { ...layout.sizes, [slot]: clampSize(px) } };
}

export function slotOf(layout: PaneLayout, id: string): SlotName {
  return SLOTS.find((slot) => layout.slots[slot].includes(id)) || "center";
}
