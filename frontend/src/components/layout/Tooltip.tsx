import { cloneElement, useEffect, useId, useLayoutEffect, useRef, useState, type FocusEventHandler,
         type PointerEvent as ReactPointerEvent, type PointerEventHandler, type ReactElement,
         type ReactNode } from "react";
import { createPortal } from "react-dom";
import { placeOverlay, type Side } from "./placement";

// SHIP CHOICE: UI_CONFIG records no delay. The pointer rests 100ms before it opens; 100ms
// after the pointer leaves, so it can cross the gap onto the bubble.
const OPEN_DELAY_MS = 100;
const CLOSE_GRACE_MS = 100;

interface TriggerProps {
  children?: ReactNode;
  "aria-label"?: string;
  "aria-describedby"?: string;
  onPointerEnter?: PointerEventHandler<HTMLElement>;
  onPointerMove?: PointerEventHandler<HTMLElement>;
  onPointerLeave?: PointerEventHandler<HTMLElement>;
  onPointerDown?: PointerEventHandler<HTMLElement>;
  onFocus?: FocusEventHandler<HTMLElement>;
  onBlur?: FocusEventHandler<HTMLElement>;
}

/**
 * Tooltip (GOAL_FOUNDATIONS A7): UI_CONFIG's dark tooltip, the one dark overlay on a light
 * page. It opens when a mouse comes to rest on its one child, and at once when the keyboard
 * focuses it; a finger never opens it.
 *
 * It never supplies a name: the child keeps its own. When the tooltip says more than that
 * name ("Auto-layout nodes" on Layout), the child is described by it at all times, through
 * a hidden copy, as a title would have described it; a screen reader's cursor moves no
 * focus and would otherwise never hear it. When it says the same ("Zoom in"), it describes
 * nothing, so the name is not read twice.
 *
 * A pointer drag never opens it: it does not open while a button is held, and a press,
 * Enter or Space -- the keys that start a keyboard drag -- shut it until the pointer comes
 * back or the keyboard focuses the child again. It opens only on the pointer's own moves,
 * after they stop. The pointer can cross onto it and it stays while hovered or focused
 * (WCAG 1.4.13). It follows its child however the child moves, and hides when the child
 * goes out of sight: off the screen, clipped by a scroll box, or covered.
 *
 * Escape hides it without moving focus or the pointer. With focus on its child, the Escape
 * is the tooltip's alone: taken on window in the capture phase, before a dialog's listener
 * and every drag's, so a tooltip the keyboard opened during a drag hides and the drag goes
 * on. With focus anywhere else, it hides and the Escape goes on to whatever has it -- the
 * pipeline search, a dialog, or the canvas clearing its selection.
 *
 * The bubble is portalled to the body with position: fixed, since a child can sit in a
 * scaled canvas stage or a scroll box, which would scale or clip it.
 */
export function Tooltip({ content, placement = "top", children }: {
  content: string;
  placement?: Side;
  children: ReactElement<TriggerProps>;
}) {
  const id = useId();
  const described = `${id}-description`;
  const anchor = useRef<HTMLElement | null>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const openTimer = useRef(0);
  const closeTimer = useRef(0);
  // Set by a press, Enter, Space or Escape; shut until the pointer comes in again or the
  // keyboard focuses the child.
  const dismissed = useRef(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const visible = hovered || focused;
  const own = children.props;
  // The child's name: its aria-label, or its text when that is all it holds.
  const name = own["aria-label"] ?? (typeof own.children === "string" ? own.children : undefined);
  const describes = name?.trim() !== content;

  const clearTimers = () => {
    window.clearTimeout(openTimer.current);
    window.clearTimeout(closeTimer.current);
    openTimer.current = 0;
    closeTimer.current = 0;
  };
  const show = (element: HTMLElement, how: "hover" | "focus") => {
    anchor.current = element;
    if (how === "hover") setHovered(true);
    else setFocused(true);
  };
  const hide = () => {
    clearTimers();
    setHovered(false);
    setFocused(false);
  };
  const dismiss = () => {
    dismissed.current = true;
    hide();
  };
  const leave = () => {
    window.clearTimeout(openTimer.current);
    openTimer.current = 0;
    window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setHovered(false), CLOSE_GRACE_MS);
  };

  useEffect(() => clearTimers, []);

  useLayoutEffect(() => {
    const node = bubble.current;
    const element = anchor.current;
    if (!visible || !node || !element) return undefined;
    let frame = 0;
    let placedFor = "";
    const boxOf = (rect: DOMRect) =>
      `${rect.left} ${rect.top} ${rect.width} ${rect.height} ${window.innerWidth} ${window.innerHeight}`;
    // Beside its child, or false when the child is out of sight: what is at its middle,
    // looking through the bubble itself, is not the child.
    const place = () => {
      const rect = element.getBoundingClientRect();
      placedFor = boxOf(rect);
      const spot = placeOverlay(rect, node, placement, "center");
      const hit = spot && document.elementsFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
        .find((each) => !node.contains(each));
      if (!spot || !hit || !element.contains(hit)) return false;
      node.style.top = `${spot.top}px`;
      node.style.left = `${spot.left}px`;
      node.dataset.side = spot.side;
      return true;
    };
    if (!place()) {
      hide();
      return undefined;
    }
    // A scroll, a resize, or the canvas's zoom moving the stage under it: not every move
    // fires an event, so the child's box is read each frame while the bubble shows.
    const follow = () => {
      if (boxOf(element.getBoundingClientRect()) !== placedFor && !place()) {
        hide();
        return;
      }
      frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    return () => cancelAnimationFrame(frame);
  }, [visible, placement]);

  useEffect(() => {
    if (!visible) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.isComposing) return;
      if (event.key === "Escape" && !event.defaultPrevented) {
        if (anchor.current?.contains(event.target as Node | null)) {
          event.preventDefault();
          event.stopPropagation();
        }
        dismiss();
      } else if (event.key === "Enter" || event.key === " ") {
        dismiss();
      }
    };
    const onPress = () => dismiss();
    const onGone = () => hide();
    window.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPress, true);
    window.addEventListener("blur", onGone);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPress, true);
      window.removeEventListener("blur", onGone);
    };
  }, [visible]);

  const trigger = cloneElement(children, {
    "aria-describedby": describes ? [own["aria-describedby"], described].filter(Boolean).join(" ")
                                  : own["aria-describedby"],
    onPointerEnter: (event: ReactPointerEvent<HTMLElement>) => {
      own.onPointerEnter?.(event);
      dismissed.current = false;
      window.clearTimeout(closeTimer.current);
    },
    onPointerMove: (event: ReactPointerEvent<HTMLElement>) => {
      own.onPointerMove?.(event);
      if (event.pointerType !== "mouse" || event.buttons !== 0 || dismissed.current || hovered
          || (event.currentTarget as HTMLButtonElement).disabled) return;
      // Each move starts the wait again: it opens once the pointer rests, not 100ms after
      // it first crossed.
      const element = event.currentTarget;
      window.clearTimeout(openTimer.current);
      openTimer.current = window.setTimeout(() => {
        openTimer.current = 0;
        show(element, "hover");
      }, OPEN_DELAY_MS);
    },
    onPointerLeave: (event: ReactPointerEvent<HTMLElement>) => {
      own.onPointerLeave?.(event);
      dismissed.current = false;
      leave();
    },
    onPointerDown: (event: ReactPointerEvent<HTMLElement>) => {
      own.onPointerDown?.(event);
      dismiss();
    },
    onFocus: (event) => {
      own.onFocus?.(event);
      // The keyboard arriving is a new request, whatever shut it before; the focus a mouse
      // press gives is not :focus-visible, so a press still keeps it shut.
      if (!event.currentTarget.matches(":focus-visible")) return;
      dismissed.current = false;
      show(event.currentTarget, "focus");
    },
    onBlur: (event) => {
      own.onBlur?.(event);
      dismissed.current = false;
      setFocused(false);
    },
  });

  return (
    <>
      {trigger}
      {describes ? <span id={described} hidden>{content}</span> : null}
      {visible ? createPortal(
        <div ref={bubble} id={id} role="tooltip" className="tooltip"
             onPointerEnter={() => window.clearTimeout(closeTimer.current)}
             onPointerLeave={(event) => {
               if (!anchor.current?.contains(event.relatedTarget as Node | null)) leave();
             }}>
          {content}
        </div>,
        document.body,
      ) : null}
    </>
  );
}
