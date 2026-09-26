import type { ReactNode } from "react";
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
 */
export function Tabs<T extends string>({ items, value, onChange, label, className, variant = "underline" }: {
  items: ReadonlyArray<TabOption<T>>;
  value: T;
  onChange: (id: T) => void;
  label: string;
  className?: string;
  variant?: "underline" | "tint";
}) {
  return (
    <nav className={classNames("tabs", variant === "tint" && "tabs-tint", className)} aria-label={label}>
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
