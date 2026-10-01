export type Side = "top" | "right" | "bottom" | "left";
export type Align = "start" | "center" | "end";

const OPPOSITE: Record<Side, Side> = { top: "bottom", bottom: "top", left: "right", right: "left" };

/**
 * Where an overlay goes beside its anchor, in viewport pixels for position: fixed
 * (GOAL_FOUNDATIONS A7): --overlay-offset from the anchor and as far from the viewport's
 * edge, turned to the other side when it does not fit and that side has more room, and
 * slid along its edge to stay on screen. `room` is the space on the side it took, which a
 * menu uses as its max-height. Null when the anchor is wholly off screen.
 */
export function placeOverlay(anchor: DOMRect, overlay: HTMLElement, want: Side, align: Align):
    { top: number; left: number; side: Side; room: number } | null {
  const gap = parseFloat(getComputedStyle(overlay).getPropertyValue("--overlay-offset")) || 8;
  const width = document.documentElement.clientWidth;
  const height = document.documentElement.clientHeight;
  if (anchor.bottom <= 0 || anchor.top >= height || anchor.right <= 0 || anchor.left >= width) return null;
  const w = overlay.offsetWidth;
  const h = overlay.offsetHeight;
  const room: Record<Side, number> = {
    top: anchor.top - 2 * gap, bottom: height - anchor.bottom - 2 * gap,
    left: anchor.left - 2 * gap, right: width - anchor.right - 2 * gap,
  };
  const vertical = want === "top" || want === "bottom";
  const side = (vertical ? h : w) > room[want] && room[OPPOSITE[want]] > room[want] ? OPPOSITE[want] : want;
  const clamp = (value: number, extent: number, limit: number) =>
    Math.min(Math.max(value, gap), Math.max(gap, limit - gap - extent));
  let top: number;
  let left: number;
  if (vertical) {
    top = side === "bottom" ? anchor.bottom + gap : anchor.top - gap - Math.min(h, room[side]);
    left = clamp(align === "start" ? anchor.left : align === "end" ? anchor.right - w
      : anchor.left + (anchor.width - w) / 2, w, width);
  } else {
    left = side === "right" ? anchor.right + gap : anchor.left - gap - Math.min(w, room[side]);
    top = clamp(align === "start" ? anchor.top : align === "end" ? anchor.bottom - h
      : anchor.top + (anchor.height - h) / 2, h, height);
  }
  return { top: Math.round(top), left: Math.round(left), side, room: Math.max(0, Math.floor(room[side])) };
}
