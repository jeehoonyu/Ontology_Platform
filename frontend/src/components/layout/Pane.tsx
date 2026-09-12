import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useDraggable, useDroppable, type DragEndEvent } from "@dnd-kit/core";
import { DragHandle, PANE_PREFIX, SLOT_PREFIX, isPaneDrag, isSlot } from "../dnd/DragKit";
import {
  DEFAULT_SLOT_PX,
  MAX_SLOT_PX,
  MIN_SLOT_PX,
  SLOTS,
  WIDTH_PRESETS,
  clearLayout,
  loadLayout,
  movePane,
  saveLayout,
  setSize,
  toggleCollapsed,
  toggleHidden,
  type PaneLayout,
  type PaneSpec,
  type SlotName
} from "../../lib/paneLayout";

/**
 * A pane a person can move, collapse and hide.
 *
 * M2 of `GOAL_PANES_2026-09-11.md`. Twenty-one pane regions existed across
 * thirteen screens and not one of them could be rearranged by the person using
 * it; `oms/audit_pane_layout.py` counts them and refuses the number falling.
 *
 * **Every pane offers two ways to move, and the second is not a courtesy.** The
 * grip is `DragHandle` from `DragKit`, so the drag census counts it and the gate
 * refuses a hand-rolled one. Beside it is a `Move to…` select, which is the
 * control a finger and a keyboard use — the same shape every other drag in this
 * product already carries, for the reason `GOAL_DRAG_2026-08-19.md` measured:
 * a drag that is the only way in is a feature only a mouse has.
 *
 * **The grip alone carries the drag listeners, never the pane body.** That is
 * what lets a pane share a screen with a canvas that drags nodes and a list that
 * sorts rows: a pointer landing on a node belongs to the inner context and this
 * one never sees it. Condition M4 tests exactly that, including with this wiring
 * removed.
 */
// Not exported. `PaneHost` is the entry point a screen uses, and a primitive
// exported for a caller that does not exist yet is a claim about the future.
// M7 exports it if a screen needs a pane outside a host.
function Pane({ id, title, collapsed, anchored, hidden, actions, onMove, onCollapse,
                       onHide, children }: {
  id: string;
  title: string;
  collapsed: boolean;
  anchored?: boolean;
  hidden?: boolean;
  actions?: ReactNode;
  onMove: (slot: SlotName) => void;
  onCollapse: () => void;
  onHide: () => void;
  children: ReactNode;
}) {
  const draggable = useDraggable({ id: `${PANE_PREFIX}${id}`, disabled: anchored });
  if (hidden) return null;
  return (
    <section
      ref={draggable.setNodeRef}
      className={`pane${collapsed ? " pane-collapsed" : ""}`}
      aria-label={title}
      // M2 shipped a pane that faded while dragging and never moved: the
      // transform was computed and thrown away, so a dragged pane sat still
      // under the pointer. M4 found it from the other end -- with the element
      // physically in its old slot, a re-render mid-drag re-measured it there
      // and the drop reported the slot it had never left, so a keyboard move
      // that announced `slot:center` committed `slot:left`.
      style={draggable.transform
        ? { transform: `translate3d(${draggable.transform.x}px, ${draggable.transform.y}px, 0)`,
            opacity: 0.6, zIndex: 4, position: "relative" }
        : undefined}
    >
      <header className="pane-header">
        {anchored ? <span className="pane-grip pane-grip-anchored" aria-hidden="true">⋮⋮</span>
                  : <DragHandle label={title} grip={draggable} className="pane-grip" />}
        <strong>{title}</strong>
        <div className="pane-controls">
          {actions}
          <button
            type="button"
            aria-label={`${collapsed ? "Expand" : "Collapse"} ${title}`}
            onClick={onCollapse}
          >{collapsed ? "+" : "−"}</button>
          {anchored ? null : (
            <>
              <select
                aria-label={`Move ${title} to`}
                value=""
                onChange={(event) => {
                  if (event.target.value) onMove(event.target.value as SlotName);
                }}
              >
                <option value="">Move to…</option>
                {SLOTS.map((slot) => <option key={slot} value={slot}>{slot}</option>)}
              </select>
              <button type="button" aria-label={`Hide ${title}`} onClick={onHide}>×</button>
            </>
          )}
        </div>
      </header>
      {collapsed ? null : <div className="pane-body">{children}</div>}
    </section>
  );
}

/**
 * The boundary between two slots.
 *
 * M3 of `GOAL_PANES_2026-09-11.md`. A `role="separator"` with `aria-valuenow`,
 * so a screen reader reads the width it holds, and arrow keys that change it —
 * which is the whole point. A splitter that only a pointer can move is the same
 * defect the drag migration spent a goal removing, one layer up.
 *
 * It drags with the pointer sensor rather than `useDraggable`, because a
 * splitter is not going anywhere: it has no droppable to land on, and modelling
 * it as a drag between containers would be dishonest about what it does. The
 * gate agrees — it counts dnd hooks and contexts, and this is neither.
 *
 * **A pointer resize previews until it is released, and Escape takes it back.**
 * V2 of `GOAL_MOVEMENT_2026-09-12.md`. This listened for `pointermove` and
 * `pointerup` and nothing else, and wrote the layout on every move, so Escape did
 * nothing and a width reached by accident was already stored: measured 220 → 382
 * during a live resize, 382 after Escape, 382 in `localStorage`. The DragKit drags
 * beside it restore on Escape because dnd-kit does; this is the one control not on
 * dnd-kit, so it has to do it itself. `pointercancel` is the same cancel arriving
 * from the system — a touch taken over by a scroll or a gesture — and without it
 * the splitter kept resizing after the finger had gone.
 */
function Splitter({ slot, size, onResize, onStart, onPreview, onCommit, onCancel }: {
  slot: SlotName;
  size: number;
  /** A keyboard step: one deliberate change, committed at once. */
  onResize: (px: number) => void;
  onStart: () => void;
  onPreview: (px: number) => void;
  onCommit: () => void;
  onCancel: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  // The direction the pointer has to travel to make this slot wider: a right
  // slot grows when the pointer moves left. Getting this backwards makes the
  // control feel broken rather than look broken.
  const sign = slot === "right" ? -1 : 1;

  useEffect(() => {
    if (!dragging) return;
    const move = (event: PointerEvent) => {
      const host = document.querySelector(`.pane-slot-${slot}`);
      if (!host) return;
      const rect = host.getBoundingClientRect();
      onPreview(sign > 0 ? event.clientX - rect.left : rect.right - event.clientX);
    };
    const stop = () => {
      setDragging(false);
      onCommit();
    };
    const cancel = () => {
      setDragging(false);
      onCancel();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      cancel();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("keydown", escape);
    };
  }, [dragging, slot, sign, onPreview, onCommit, onCancel]);

  return (
    <button
      type="button"
      className="pane-splitter"
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${slot} pane`}
      aria-valuenow={size}
      aria-valuemin={MIN_SLOT_PX}
      aria-valuemax={MAX_SLOT_PX}
      onPointerDown={() => {
        onStart();
        setDragging(true);
      }}
      onKeyDown={(event) => {
        const step = event.shiftKey ? 48 : 16;
        if (event.key === "ArrowRight") onResize(size + sign * step);
        else if (event.key === "ArrowLeft") onResize(size - sign * step);
        else if (event.key === "Home") onResize(MIN_SLOT_PX);
        else if (event.key === "End") onResize(MAX_SLOT_PX);
        else return;
        event.preventDefault();
      }}
    />
  );
}

function Slot({ name, size, children }: {
  name: SlotName;
  size?: number;
  children: ReactNode;
}) {
  const droppable = useDroppable({ id: `${SLOT_PREFIX}${name}` });
  return (
    <div
      ref={droppable.setNodeRef}
      className={`pane-slot pane-slot-${name}${droppable.isOver ? " drag-active" : ""}`}
      data-slot={name}
      style={name === "center" || !size ? undefined
                                        : { flexBasis: `${size}px`, width: `${size}px` }}
    >{children}</div>
  );
}

/**
 * The layout state for one screen, and the pane half of its drag handling.
 *
 * The screen owns the `DndContext`, not this. The first version put one context
 * inside `PaneHost` for the panes and left each screen's canvas context inside a
 * pane — and the pipeline palette stopped working, because the palette entry sat
 * in one pane and the canvas droppable in another, so `useDraggable` and
 * `useDroppable` resolved to different contexts and the drop never fired. Found
 * by `evaluator.spec.ts::pipeline creates a graph and accepts a dragged node`.
 *
 * Nesting cannot fix that: grips and palette entries are intermixed across
 * panes, so whichever context is nearer captures both. One context per screen,
 * dispatching on the id prefix, is the shape that works — and it makes M4's
 * "none steals the other's pointer" a property of the dispatch rather than a
 * hope about the tree.
 */
export function usePaneLayout(screen: string, panes: PaneSpec[]) {
  const [layout, setLayout] = useState<PaneLayout | null>(null);

  useEffect(() => {
    setLayout(loadLayout(screen, panes));
    // `panes` is a literal rebuilt each render; the screen is what identifies it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen]);

  const update = useCallback((next: PaneLayout) => {
    setLayout(next);
    saveLayout(screen, next);
  }, [screen]);

  /** Shown, not stored: a live resize that has not been released yet. */
  const preview = useCallback((next: PaneLayout) => {
    setLayout(next);
  }, []);

  const reset = useCallback(() => {
    clearLayout(screen);
    setLayout(loadLayout(screen, panes));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen]);

  /** True when this drag was a pane moving, so the screen can stop there. */
  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const active = String(event.active.id);
    if (!isPaneDrag(active)) return false;
    const over = event.over ? String(event.over.id) : "";
    if (layout && isSlot(over)) {
      update(movePane(layout, active.slice(PANE_PREFIX.length),
                      over.slice(SLOT_PREFIX.length) as SlotName));
    }
    return true;
  }, [layout, update]);

  return { screen, panes, layout, update, preview, reset, handleDragEnd };
}

export type PaneLayoutState = ReturnType<typeof usePaneLayout>;

export function PaneHost({ state, render }: {
  state: PaneLayoutState;
  render: (id: string) => ReactNode;
}) {
  const { panes, layout, update, preview, reset } = state;
  // The arrangement a pointer resize started from, so Escape can put it back
  // exactly -- including a slot that had no stored width at all.
  const before = useRef<PaneLayout | null>(null);
  if (!layout) return null;
  const byId = new Map(panes.map((pane) => [pane.id, pane]));
  const hiddenPanes = layout.hidden.map((id) => byId.get(id)).filter(Boolean) as PaneSpec[];
  const occupied = (slot: SlotName) => layout.slots[slot].some((id) => !layout.hidden.includes(id));

  const splitter = (slot: SlotName) => (
    <Splitter
      slot={slot}
      size={layout.sizes[slot] ?? DEFAULT_SLOT_PX}
      onResize={(px) => update(setSize(layout, slot, px))}
      onStart={() => { before.current = layout; }}
      onPreview={(px) => preview(setSize(layout, slot, px))}
      onCommit={() => { update(layout); before.current = null; }}
      onCancel={() => {
        if (before.current) preview(before.current);
        before.current = null;
      }}
    />
  );

  return (
      <div className="pane-host">
        <div className="pane-host-bar">
          {/* Nothing can be lost: a hidden pane is always one control away. */}
          <select
            aria-label="Panes"
            value=""
            onChange={(event) => {
              if (event.target.value) update(toggleHidden(layout, event.target.value));
            }}
          >
            <option value="">Panes{hiddenPanes.length ? ` (${hiddenPanes.length} hidden)` : ""}</option>
            {hiddenPanes.map((pane) => (
              <option key={pane.id} value={pane.id}>Show {pane.title}</option>
            ))}
          </select>
          {/* V3 of GOAL_MOVEMENT_2026-09-12. The splitter resizes by drag and by
              arrow keys, and WCAG 2.5.7 asks for a single pointer with no drag,
              which a keyboard does not satisfy. Every move in the product already
              had one -- `Move to…`, Up and Down, tap to place -- and the resize was
              the one operation that did not. */}
          {(["left", "right"] as SlotName[]).filter(occupied).map((slot) => (
            <select
              key={slot}
              className="pane-width"
              aria-label={`Width of ${slot} pane`}
              value=""
              onChange={(event) => {
                if (event.target.value) update(setSize(layout, slot, Number(event.target.value)));
              }}
            >
              <option value="">{slot === "left" ? "Left" : "Right"} width…</option>
              {WIDTH_PRESETS.map(([label, px]) => (
                <option key={px} value={px}>{label} · {px}px</option>
              ))}
            </select>
          ))}
          {/* Named for what it touches: this screen's panes, in this browser. It was
              `Reset layout`, on a screen where the graph's node positions are also a
              layout and are shared with everyone who opens it. V8 of GOAL_MOVEMENT. */}
          <button type="button" onClick={reset}>Reset panes</button>
        </div>
        <div className="pane-host-row">
          {(["left", "center", "right"] as SlotName[]).map((slot) => (
            <Fragment key={slot}>
            {slot === "right" && occupied("right") ? splitter("right") : null}
            <Slot name={slot} size={layout.sizes[slot]}>
              {layout.slots[slot].filter((id) => !layout.hidden.includes(id)).map((id) => {
                const spec = byId.get(id);
                if (!spec) return null;
                return (
                  <Pane
                    key={id}
                    id={id}
                    title={spec.title}
                    anchored={spec.anchored}
                    collapsed={layout.collapsed.includes(id)}
                    onMove={(to) => update(movePane(layout, id, to))}
                    onCollapse={() => update(toggleCollapsed(layout, id))}
                    onHide={() => update(toggleHidden(layout, id))}
                  >{render(id)}</Pane>
                );
              })}
            </Slot>
            {slot === "left" && occupied("left") ? splitter("left") : null}
            </Fragment>
          ))}
        </div>
        <Slot name="bottom" size={layout.sizes.bottom}>
          {layout.slots.bottom.filter((id) => !layout.hidden.includes(id)).map((id) => {
            const spec = byId.get(id);
            if (!spec) return null;
            return (
              <Pane
                key={id}
                id={id}
                title={spec.title}
                anchored={spec.anchored}
                collapsed={layout.collapsed.includes(id)}
                onMove={(to) => update(movePane(layout, id, to))}
                onCollapse={() => update(toggleCollapsed(layout, id))}
                onHide={() => update(toggleHidden(layout, id))}
              >{render(id)}</Pane>
            );
          })}
        </Slot>
      </div>
  );
}
