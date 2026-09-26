import { useId, useLayoutEffect, useRef, useState, type FocusEvent, type KeyboardEvent, type MouseEvent,
         type ReactNode } from "react";
import { classNames } from "../../utils/format";
import { placeOverlay } from "./placement";

const ITEM = "button:not(:disabled)";

/**
 * Menu (GOAL_FOUNDATIONS A7): UI_CONFIG's menu, a panel of plain buttons opened from a
 * button. It is a disclosure (decision N, option (a)): the button says whether it is
 * expanded and names the panel while it is open; there is no menu or menuitem role and no
 * aria-haspopup, which a screen reader announces as a menu that is not there.
 *
 * The panel follows its button in the page, so Tab goes from the button into it and a
 * dialog's focus trap still holds it. It floats on position: fixed, 8px from the button,
 * so a pane's edge and a scroll box do not clip it: white, radius 4, the overlay shadow.
 * It moves with its button however the button moves, and closes when the button goes out
 * of sight: off the screen, clipped by a scroll box, or covered.
 *
 * Opening leaves focus on the button; ArrowDown and ArrowUp open onto the first or last
 * item. Inside, the arrows, Home and End move between items and leave a select's arrows to
 * the select. Choosing an item or Escape closes it and gives focus back to the button
 * before anything the item opens renders, so a dialog it opens returns focus there. A
 * press outside, or focus moving outside, closes it where focus is.
 *
 * Escape is taken on window in the capture phase, and only with focus on the button or in
 * the panel: before a dialog's listener and every drag's, so one Escape closes the menu
 * and nothing else, and an Escape pressed elsewhere belongs to whatever has focus.
 *
 * `className` is the button's (always rendered, so the style-scope audit sees it);
 * `panelClassName` is the panel's.
 */
export function Menu({ trigger, triggerLabel, className, label, align = "start", panelClassName, children }: {
  trigger: ReactNode;
  triggerLabel?: string;
  className?: string;
  label?: string;
  align?: "start" | "end";
  panelClassName?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const focusOnOpen = useRef<"first" | "last" | null>(null);

  const items = () => Array.from(panel.current?.querySelectorAll<HTMLButtonElement>(ITEM) ?? []);
  const focusItem = (which: "first" | "last") => {
    const list = items();
    (which === "first" ? list[0] : list[list.length - 1])?.focus();
  };
  const inside = (node: Node | null) =>
    Boolean(node && (button.current?.contains(node) || panel.current?.contains(node)));

  useLayoutEffect(() => {
    const node = panel.current;
    const anchor = button.current;
    if (!open || !node || !anchor) return undefined;
    let frame = 0;
    let closed = false;
    // The button's box and the viewport the panel was last placed against.
    let placedFor = "";
    const boxOf = (rect: DOMRect) =>
      `${rect.left} ${rect.top} ${rect.width} ${rect.height} ${window.innerWidth} ${window.innerHeight}`;
    const close = () => {
      // The button went out of sight; a panel left floating would point at nothing.
      closed = true;
      focusOnOpen.current = null;
      if (node.contains(document.activeElement)) anchor.focus({ preventScroll: true });
      setOpen(false);
    };
    const place = () => {
      const rect = anchor.getBoundingClientRect();
      placedFor = boxOf(rect);
      // Measuring lets the panel grow to its whole height, and a box that stops overflowing
      // forgets how far it was scrolled; the item a keyboard reached stays in view.
      const scrolled = node.scrollTop;
      node.style.maxHeight = "";
      const spot = placeOverlay(rect, node, "bottom", align);
      // Out of sight is off the screen, clipped by a scroll box, or under something drawn
      // over it, such as the sticky bar of the narrow layout: what is at the button's middle
      // is not the button.
      const seen = spot && inside(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2));
      if (!spot || !seen) {
        close();
        return false;
      }
      node.style.top = `${spot.top}px`;
      node.style.left = `${spot.left}px`;
      node.style.maxHeight = `${spot.room}px`;
      node.scrollTop = scrolled;
      return true;
    };
    // Nothing is focused inside a panel that never showed.
    if (!place()) return undefined;
    if (focusOnOpen.current) {
      focusItem(focusOnOpen.current);
      focusOnOpen.current = null;
    }
    // The button moves with a scroll, a resize, or the page laying out again around it (the
    // strip's status changing width), and not every move fires an event: its box is read
    // each frame while the panel is open, and the panel placed again when it has moved.
    const follow = () => {
      if (closed) return;
      if (boxOf(anchor.getBoundingClientRect()) !== placedFor && !place()) return;
      frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.isComposing || event.defaultPrevented) return;
      if (!inside(event.target as Node | null)) return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      anchor.focus({ preventScroll: true });
    };
    const onPress = (event: PointerEvent) => {
      if (!inside(event.target as Node | null)) setOpen(false);
    };
    // Items added or taken away change the panel's height, and with it where it fits.
    const resized = new ResizeObserver(() => {
      if (!closed) place();
    });
    resized.observe(node);
    window.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPress, true);
    return () => {
      closed = true;
      cancelAnimationFrame(frame);
      resized.disconnect();
      window.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPress, true);
    };
  }, [open, align]);

  const onTriggerKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const which = event.key === "ArrowDown" ? "first" : "last";
    if (open) focusItem(which);
    else {
      focusOnOpen.current = which;
      setOpen(true);
    }
  };
  const onPanelKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const { key } = event;
    if (key !== "ArrowDown" && key !== "ArrowUp" && key !== "Home" && key !== "End") return;
    // A select, a field or a text box keeps its own arrows: Chrome changes a closed
    // select's value with them.
    if ((event.target as Element).closest("input, select, textarea")) return;
    const list = items();
    if (!list.length) return;
    event.preventDefault();
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const step = key === "ArrowDown" ? 1 : -1;
    const next = key === "Home" ? 0 : key === "End" ? list.length - 1
      : at < 0 ? (step > 0 ? 0 : list.length - 1) : (at + step + list.length) % list.length;
    list[next].focus();
  };
  const onChoose = (event: MouseEvent<HTMLDivElement>) => {
    // Runs after the item's own onClick, in the same batch, so the button has focus again
    // before a dialog the item opens reads its opener (Dialog.tsx).
    const item = (event.target as Element).closest("button");
    if (!item || item.disabled || !panel.current?.contains(item)) return;
    setOpen(false);
    button.current?.focus({ preventScroll: true });
  };
  const onLeave = (event: FocusEvent<HTMLElement>) => {
    // Null is the window losing focus, or focus dropped to the page: the menu stays. Focus
    // moving to anything outside closes it, so an open panel never covers what now has
    // focus (WCAG 2.4.11).
    const next = event.relatedTarget as Node | null;
    if (next && !inside(next)) setOpen(false);
  };

  return (
    <>
      <button ref={button} type="button" className={className} aria-label={triggerLabel}
              aria-expanded={open} aria-controls={open ? id : undefined}
              onClick={() => setOpen((value) => !value)} onKeyDown={onTriggerKey} onBlur={onLeave}>
        {trigger}
      </button>
      {open ? (
        <div ref={panel} id={id} className={classNames("menu-panel", panelClassName)}
             role={label ? "group" : undefined} aria-label={label}
             onKeyDown={onPanelKey} onClick={onChoose} onBlur={onLeave}>
          {children}
        </div>
      ) : null}
    </>
  );
}
