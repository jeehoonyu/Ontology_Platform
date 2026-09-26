import { useEffect, useRef, type ReactNode } from "react";
import { classNames } from "../../utils/format";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), '
  + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Dialog (GOAL_FOUNDATIONS A7): a modal that holds focus while it is open, closes on
 * Escape and on its backdrop, and gives focus back to whatever opened it. Escape is
 * taken in the capture phase and goes no further, so it never also cancels something
 * behind the dialog, such as a drag on the canvas. The look is UI_CONFIG's light
 * dialog: white, radius 4, the overlay shadow, over the backdrop.
 *
 * The opener is read during the first render, before a child's autoFocus moves focus
 * into the dialog.
 */
export function Dialog({ label, labelledBy, onClose, className, backdropClassName, children }: {
  label?: string;
  labelledBy?: string;
  onClose: () => void;
  className?: string;
  backdropClassName?: string;
  children: ReactNode;
}) {
  const panel = useRef<HTMLElement>(null);
  const opener = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const node = panel.current;
    if (!node) return undefined;
    if (!node.contains(document.activeElement)) (node.querySelector<HTMLElement>(FOCUSABLE) ?? node).focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((item) => item.offsetParent !== null);
      if (!items.length) {
        event.preventDefault();
        node.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const inside = node.contains(document.activeElement);
      if (event.shiftKey && (!inside || document.activeElement === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || document.activeElement === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    const returnTo = opener.current;
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (returnTo?.isConnected) returnTo.focus();
    };
  }, []);

  return (
    <div className={classNames("dialog-backdrop", backdropClassName)} role="presentation" onMouseDown={() => close.current()}>
      <section ref={panel} className={classNames("dialog", className)} role="dialog" aria-modal="true"
               aria-label={labelledBy ? undefined : label} aria-labelledby={labelledBy} tabIndex={-1}
               onMouseDown={(event) => event.stopPropagation()}>
        {children}
      </section>
    </div>
  );
}
