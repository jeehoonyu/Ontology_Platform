import {
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates, useSortable } from "@dnd-kit/sortable";
import type { CSSProperties } from "react";

/** What `useSortable` and `useDraggable` hand back for a handle to spread. */
type Grippable = Pick<ReturnType<typeof useSortable>, "attributes" | "listeners">;

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
export function useWorkspaceSensors(kind: "free" | "sortable" = "free") {
  return useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor,
              kind === "sortable" ? { coordinateGetter: sortableKeyboardCoordinates } : undefined)
  );
}

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
