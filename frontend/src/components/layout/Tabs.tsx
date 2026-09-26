import type { KeyboardEvent, ReactNode } from "react";
import { classNames } from "../../utils/format";

export interface TabOption<T extends string> {
  id: T;
  label: ReactNode;
}

/**
 * Tabs (GOAL_FOUNDATIONS A8): the original's underline tabs. A 40px bar ruled by the
 * divider, 14px labels at 400 set 20px apart, and the selected one in --text-selected
 * over a 3px indicator; only the colour changes. They stay buttons in a named nav,
 * the selected one marked with aria-current (decision N, option (a)), and keep the
 * `active` class screens and tests read.
 *
 * `variant="tint"` is the bottom-panel kind: a 35px bar, the selected tab on the
 * --surface-selected tint in --text-selected, no indicator. UI_CONFIG's pill and
 * vertical kinds come with the first screen that needs each.
 *
 * `semantics="tablist"` keeps an ARIA tablist where one already exists and its
 * locators read `role="tab"` (the artifact review, decision N): tabs with
 * aria-selected, one tab stop, and the arrow keys moving the selection.
 */
export function Tabs<T extends string>({ items, value, onChange, label, className, variant = "underline", semantics = "nav" }: {
  items: ReadonlyArray<TabOption<T>>;
  value: T;
  onChange: (id: T) => void;
  label: string;
  className?: string;
  variant?: "underline" | "tint";
  semantics?: "nav" | "tablist";
}) {
  const classes = classNames("tabs", variant === "tint" && "tabs-tint", className);
  if (semantics === "tablist") {
    const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
      const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      const next = (index + step + items.length) % items.length;
      onChange(items[next].id);
      (event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role='tab']")[next])?.focus();
    };
    return (
      <div className={classes} role="tablist" aria-label={label}>
        {items.map((item, index) => (
          <button key={item.id} type="button" role="tab" className={classNames("tab", item.id === value && "active")}
                  aria-selected={item.id === value} tabIndex={item.id === value ? 0 : -1}
                  onClick={() => onChange(item.id)} onKeyDown={(event) => move(event, index)}>
            {item.label}
          </button>
        ))}
      </div>
    );
  }
  return (
    <nav className={classes} aria-label={label}>
      {items.map((item) => (
        <button key={item.id} type="button" className={classNames("tab", item.id === value && "active")}
                aria-current={item.id === value ? "true" : undefined} onClick={() => onChange(item.id)}>
          {item.label}
        </button>
      ))}
    </nav>
  );
}

/**
 * SegmentedControl (GOAL_FOUNDATIONS A8): 30px; the selected option white with the
 * default button's ring, the others transparent in --text-muted. Each option says
 * whether it is pressed (decision N, option (a)).
 */
export function SegmentedControl<T extends string>({ options, value, onChange, label, className }: {
  options: ReadonlyArray<TabOption<T>>;
  value: T;
  onChange: (id: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div className={classNames("segmented-control", className)} role="group" aria-label={label}>
      {options.map((option) => (
        <button key={option.id} type="button" className={classNames(option.id === value && "active")}
                aria-pressed={option.id === value} onClick={() => onChange(option.id)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}
