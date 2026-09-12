import {
  KeyboardSensor,
  PointerSensor,
  defaultKeyboardCoordinateGetter,
  pointerWithin,
  rectIntersection,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type KeyboardCoordinateGetter
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates, useSortable } from "@dnd-kit/sortable";
import type { CSSProperties } from "react";

/** What `useSortable` and `useDraggable` hand back for a handle to spread. */
type Grippable = Pick<ReturnType<typeof useSortable>, "attributes" | "listeners">;

/**
 * The two kinds of drag a paned screen carries, told apart by an id prefix.
 *
 * A screen with panes has exactly one `DndContext` — `usePaneLayout` records why
 * nesting does not work — so three separate things have to tell a pane drag from
 * everything else: which droppables it may land on, what its drop means, and how
 * an arrow key moves it. Spelled out three times in three files is how the three
 * drift apart, so the prefix is named once and asked once.
 */
export const PANE_PREFIX = "pane:";
export const SLOT_PREFIX = "slot:";
export const isPaneDrag = (id: unknown): boolean => String(id).startsWith(PANE_PREFIX);
export const isSlot = (id: unknown): boolean => String(id).startsWith(SLOT_PREFIX);

const ARROWS: Record<string, { x: number; y: number }> = {
  ArrowRight: { x: 1, y: 0 },
  ArrowLeft: { x: -1, y: 0 },
  ArrowDown: { x: 0, y: 1 },
  ArrowUp: { x: 0, y: -1 }
};

const centreOf = (rect: DOMRect) => ({ x: rect.left + rect.width / 2,
                                       y: rect.top + rect.height / 2 });

/**
 * Where an arrow key takes a pane mid-drag: the next slot, not 25 pixels.
 *
 * M4 of `GOAL_PANES_2026-09-11.md`. dnd-kit's default getter moves a keyboard
 * drag 25px a press, which is right for a node on a canvas — a node goes wherever
 * it is put — and useless for a pane. Crossing a 1280px screen from the left slot
 * to the right one is roughly forty presses, and a control that works after forty
 * presses does not work.
 *
 * **It dispatches on the active id, and that is forced rather than chosen.** One
 * context per screen means one keyboard sensor and so one coordinate getter,
 * shared by pane drags and node drags alike. Giving the whole context
 * slot-jumping would break `drag-affordances.spec.ts::a pipeline node moves with
 * the keyboard` in exactly the way `GOAL_DRAG` L8 records — the wrong coordinate
 * getter reaching a draggable it was not written for, silently, with every
 * pointer drag still working. A non-pane drag is handed back to dnd-kit's own
 * default rather than to a copy of it, because a copy of a default goes stale
 * without anything saying so.
 *
 * Slot rectangles come from the DOM rather than from `context.droppableRects`.
 * They are the same rectangles, and reading `.pane-slot` keeps this out of
 * dnd-kit's internal container bookkeeping, which is the part of the library
 * most likely to change shape between versions.
 */
export const slotKeyboardCoordinates: KeyboardCoordinateGetter = (event, args) => {
  if (!isPaneDrag(args.active)) return defaultKeyboardCoordinateGetter(event, args);
  const direction = ARROWS[event.code];
  if (!direction) return;
  event.preventDefault();

  const named = Array.from(document.querySelectorAll<HTMLElement>(".pane-slot"))
    .map((element) => ({ id: `${SLOT_PREFIX}${element.dataset.slot ?? ""}`,
                         rect: element.getBoundingClientRect() }))
    .filter(({ rect }) => rect.width > 0 && rect.height > 0);
  if (!named.length) return;
  const slots = named.map(({ rect }) => rect);

  // The slot being left is the one the drag is already *over*, which is what
  // `slotAwareCollision` decided and therefore what the drop will act on.
  //
  // The first version worked this out from `currentCoordinates` instead, by
  // containment and then by nearest centre. Both read a point that is the
  // dragged pane's top-left at drag start, and page scroll moves it out from
  // under the slot it belongs to — measured as the same drag reporting y=392
  // in one run and y=329 in another. The test passed alone and failed inside
  // the suite, which is what that kind of staleness looks like.
  const from = args.currentCoordinates;
  const over = args.context.over ? String(args.context.over.id) : "";
  const holds = (rect: DOMRect) =>
    from.x >= rect.left && from.x <= rect.right && from.y >= rect.top && from.y <= rect.bottom;
  const away = (rect: DOMRect) =>
    Math.hypot(centreOf(rect).x - from.x, centreOf(rect).y - from.y);
  const here = named.find((slot) => slot.id === over)?.rect
    ?? slots.find(holds)
    ?? slots.reduce((best, rect) => (away(rect) < away(best) ? rect : best));
  const anchor = centreOf(here);

  // Strictly in the arrow's direction, and dominant on that axis, so ArrowRight
  // from the centre slot finds the right slot and never the bottom one.
  const ahead = slots.filter((rect) => {
    const offset = { x: centreOf(rect).x - anchor.x, y: centreOf(rect).y - anchor.y };
    return direction.x
      ? Math.sign(offset.x) === direction.x && Math.abs(offset.x) > Math.abs(offset.y)
      : Math.sign(offset.y) === direction.y && Math.abs(offset.y) > Math.abs(offset.x);
  });
  if (!ahead.length) return;

  const gap = (rect: DOMRect) =>
    Math.hypot(centreOf(rect).x - anchor.x, centreOf(rect).y - anchor.y);
  const next = centreOf(ahead.reduce((best, rect) => (gap(rect) < gap(best) ? rect : best)));

  // Translate by the vector between the two slot centres rather than jumping to
  // the target's centre. Setting a top-left to a centre shifts the pane half its
  // own size past the target, so the rect that decides the drop can overlap the
  // slot beyond it more than the one aimed at.
  return { x: from.x + (next.x - anchor.x), y: from.y + (next.y - anchor.y) };
};

/**
 * One drag mechanism, configured once.
 *
 * Four drags in this product were hand-rolled on native HTML5 `draggable` and
 * `dataTransfer`. That mechanism cannot be reached from a keyboard at all, and
 * cannot be reached from touch at all, so every one of them needed a second
 * control beside it doing the same job. This replaces the mechanism rather than
 * the controls: the second controls stay, because they are good, and the drags
 * themselves become operable by keyboard for the first time.
 *
 * The sensor configuration is the part worth having in one place.
 *
 * **`distance: 8` on the pointer sensor.** Every draggable here is also a button
 * that does the same thing on click — tap the palette entry, choose from the
 * select. Without an activation constraint a click reads as a zero-length drag
 * and those controls stop working, which is precisely the failure the browser
 * tests were written to catch.
 *
 * **No `TouchSensor`, and no `touch-action: none` on list items.** A finger on a
 * palette or a property list is scrolling, and blocking that to enable a drag
 * would trade a gesture people use constantly for one they have a button for.
 * Touch reaches these interactions through the second control. The exception is
 * an explicit grip: it is small, nothing scrolls by starting on it, and
 * `.drag-grip` and `.drag-handle` carry `touch-action: none` so a finger can
 * reorder a list — which was measured, and did not work before it was set.
 *
 * **`kind` is not decoration.** `sortableKeyboardCoordinates` derives the next
 * position from the other items in a `SortableContext`; outside one there are no
 * other items, so it returns nothing and every arrow key does nothing. Passing it
 * everywhere made keyboard dragging on the two canvases silently inert while the
 * pointer drag worked perfectly — caught only because the test that claimed the
 * capability was run against a build with the wiring removed, and passed.
 */
export function useWorkspaceSensors(kind: "free" | "sortable" | "slots" = "free") {
  return useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, KEYBOARD_BY_KIND[kind])
  );
}

const KEYBOARD_BY_KIND = {
  free: undefined,
  sortable: { coordinateGetter: sortableKeyboardCoordinates },
  slots: { coordinateGetter: slotKeyboardCoordinates }
};

/**
 * Where a drag ended, in client coordinates.
 *
 * A pointer drag reports its start and how far it moved, never where it is now.
 * A *keyboard* drag has no pointer at all, and the two canvases place a node
 * where the drag ended — so without the second branch, dragging a node onto a
 * canvas with the arrow keys would drop it at the top-left corner of the screen.
 * The centre of the target is where the focus ring visibly landed.
 */
export function dropPointOf(event: DragEndEvent): { x: number; y: number } | null {
  const activator = event.activatorEvent as Partial<PointerEvent> | undefined;
  if (activator && typeof activator.clientX === "number" && typeof activator.clientY === "number") {
    return { x: activator.clientX + event.delta.x, y: activator.clientY + event.delta.y };
  }
  const rect = event.over?.rect;
  return rect ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : null;
}

/**
 * The grip a list row is dragged by.
 *
 * A button, not a decorated span: it takes focus, it takes `Space` to pick the
 * row up and arrow keys to move it, and a screen reader is told what it does.
 * The glyph before this was a `<span>` with a `title` attribute, which announced
 * nothing and could not be reached at all without a mouse.
 */
export function DragHandle({ label, grip, className }: {
  label: string;
  grip: Grippable;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={className || "drag-grip"}
      aria-label={`Reorder ${label}`}
      {...grip.attributes}
      {...grip.listeners}
    >⋮⋮</button>
  );
}

/**
 * A row while it is being dragged or settling back.
 *
 * `useSortable` returns a transform and a transition and expects the caller to
 * apply both; forgetting the transition is why a migrated list snaps rather than
 * slides, and it is the same three lines at every call site.
 */
export function sortableStyle(transform: { x: number; y: number } | null,
                             transition: string | undefined,
                             isDragging: boolean): CSSProperties {
  return {
    transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
    transition,
    opacity: isDragging ? 0.6 : undefined,
    position: isDragging ? "relative" : undefined,
    zIndex: isDragging ? 2 : undefined
  };
}


/**
 * Which droppables a drag is allowed to land on, decided by what is being
 * dragged.
 *
 * A screen with panes has two kinds of target in one context: the four pane
 * slots, and whatever the panes contain — a canvas, a list. They overlap by
 * construction, because a slot *contains* the canvas, so the slot wins any
 * geometric contest and a palette entry dropped on the canvas reports the slot
 * instead. Measured as the palette silently doing nothing:
 * `evaluator.spec.ts::pipeline creates a graph and accepts a dragged node` went
 * from passing to placing zero nodes the moment the panes arrived.
 *
 * Nesting the contexts does not solve it — grips and palette entries are
 * intermixed across panes, so whichever context is nearer captures both. This
 * does: a `pane:` drag sees only slots, and everything else sees everything
 * except slots. "None steals the other's target" becomes a rule rather than a
 * hope about the tree.
 */
export const slotAwareCollision: CollisionDetection = (args) => {
  const movingAPane = isPaneDrag(args.active.id);
  const droppableContainers = args.droppableContainers.filter(
    (container) => isSlot(container.id) === movingAPane);
  const within = pointerWithin({ ...args, droppableContainers });
  // A keyboard drag has no pointer, so `pointerWithin` finds nothing and the
  // drop would be reported over nothing at all.
  return within.length ? within : rectIntersection({ ...args, droppableContainers });
};
