/**
 * What each status word means, per domain. GOAL_LOOK U8, the plan's A1.
 *
 * StatusBadge used to pick its colour from substrings and default to green, so
 * OFFLINE, DENIED, REJECTED, BLOCKED and BROKEN read as success and "inactive"
 * read as a warning because it contains "active". Now every caller says which
 * vocabulary its value comes from. A word is matched whole (case aside), never
 * by substring, and a word a vocabulary does not know is neutral: it says
 * nothing rather than something false. That is also how an unknown severity is
 * refused (GOAL_HONEST_UI's open item): it does not borrow a colour.
 *
 * The words come from the backend where it has them (oms/app) and from the
 * placeholders the screens make up ("NOT_RUN", "not scored", "CHECKING").
 */

export type Intent = "success" | "warning" | "danger" | "primary" | "neutral";

export type Vocabulary = Readonly<Record<string, Intent>>;

function words(map: Record<Intent, string[]>): Vocabulary {
  const out: Record<string, Intent> = {};
  for (const intent of Object.keys(map) as Intent[]) {
    for (const word of map[intent]) out[word.toLowerCase()] = intent;
  }
  return Object.freeze(out);
}

/** The intent a vocabulary gives a value; neutral when it does not know the word. */
export function intentOf(vocabulary: Vocabulary, value: unknown): Intent {
  if (value === null || value === undefined) return "neutral";
  return vocabulary[String(value).trim().toLowerCase()] ?? "neutral";
}

/** Platform jobs, plugin executions, gateway and ingestion runs. */
export const JOB_STATUS = words({
  success: ["SUCCEEDED", "PUBLISHED", "DELIVERED", "SUCCESS", "SUCCESS_CACHED", "COMPLETED", "EXECUTED"],
  primary: ["RUNNING", "IN_FLIGHT", "RETRYING"],
  warning: ["BLOCKED", "RETRY", "WARN", "PENDING"],
  danger: ["FAILED", "DEAD_LETTER", "DENIED"],
  neutral: ["QUEUED", "CANCELLED", "NOT_EXECUTED", "NOT_RUN"],
});

/** Automation runs (automate_ops.RUN_STATUSES). */
export const AUTOMATION_RUN = words({
  success: ["SUCCEEDED"],
  primary: ["TRIGGERED"],
  warning: ["PARTIALLY_FAILED", "pending_approval"],
  danger: ["FAILED"],
  neutral: ["SKIPPED"],
});

/** An action's result, and a per-output ontology contract run. */
export const ACTION_RESULT = words({
  success: ["SUCCESS", "SUCCESS_CACHED"],
  warning: ["REQUIRES_APPROVAL", "PARTIAL"],
  danger: ["FAILED"],
  neutral: [],
  primary: [],
});

/** Checks, gates and validations that pass, warn or fail. */
export const CHECK_RESULT = words({
  success: ["PASS", "VALID", "VALIDATED", "IMPORTED", "CURRENT", "COMPLETE", "READY"],
  warning: ["WARN", "WARNING"],
  danger: ["FAIL", "INVALID", "BREACHED"],
  neutral: ["NOT_RUN", "not run", "NOT_CONFIGURED", "NOT_AVAILABLE", "UNKNOWN", "COLLECTING", "WAITING",
            "not evaluated", "loading", "LOADING"],
  primary: [],
});

/** The backend bar: READY or NEEDS_ATTENTION from the server; the rest the screen's own. */
export const READINESS = words({
  success: ["READY", "connected"],
  warning: ["NEEDS_ATTENTION"],
  danger: ["OFFLINE"],
  neutral: ["CHECKING", "UNKNOWN", "OPTIONAL", "NOT_CONNECTED"],
  primary: [],
});

/** A pipeline output node. */
export const NODE_STATUS = words({
  success: ["READY"],
  warning: ["CONFIGURE"],
  danger: ["ERROR"],
  neutral: [],
  primary: [],
});

/** Workers: ACTIVE is healthy, not a warning. */
export const WORKER_STATUS = words({
  success: ["ACTIVE"],
  warning: ["DRAINING"],
  danger: ["OFFLINE"],
  neutral: [],
  primary: [],
});

/** Workflow steps and section cards; "active" is the current step. */
export const STEP_STATUS = words({
  success: ["complete", "PASS"],
  primary: ["active"],
  warning: ["blocked", "WARN"],
  danger: ["FAIL"],
  neutral: ["available"],
});

/** Every severity scale the product shows (ops, SLO, rules, health findings, warnings). */
export const SEVERITY = words({
  danger: ["critical", "error", "high"],
  warning: ["medium", "warn", "warning"],
  primary: ["info"],
  neutral: ["low"],
  success: [],
});

/** Risk bands (decision_intelligence): high risk is danger, as the map's markers draw it. */
export const RISK_BAND = words({
  danger: ["critical", "high"],
  warning: ["medium"],
  success: ["low"],
  neutral: ["not_scored", "not scored", "unscored"],
  primary: [],
});

/** Approvals, reviews and the decisions that close them. */
export const APPROVAL = words({
  success: ["APPROVED", "EXECUTED", "ACCEPTED", "APPLIED", "RESOLVED", "QUALIFYING", "eligible", "PUBLISHED",
            "released"],
  primary: ["OPEN", "VALIDATED"],
  warning: ["PENDING", "INCOMPLETE", "CONFLICT", "SUBMITTED"],
  danger: ["REJECTED", "blocked"],
  neutral: ["NOT_STAGED", "NOT_VERIFIED", "DRAFT", "BASELINE", "SUPERSEDED", "not evaluated"],
});

/** Policy decisions: platform, agent tools and actions, access checks. */
export const POLICY = words({
  success: ["ALLOW", "ALLOWED", "ALLOW_WITH_MASKS", "allowed", "within limit"],
  warning: ["REQUIRE_APPROVAL", "APPROVAL_REQUIRED", "REVIEW_REQUIRED"],
  danger: ["DENY", "DENIED", "denied", "FAILED", "over limit"],
  neutral: ["NOT_RUN", "WHAT_IF"],
  primary: [],
});

/** A platform policy decision; any *_BREAK_GLASS decision is allowed only by an override. */
export function policyIntent(value: unknown): Intent {
  const word = String(value ?? "");
  if (/_BREAK_GLASS$/i.test(word)) return "warning";
  return intentOf(POLICY, word);
}

/** Things that are switched on or off, installed, published or saved. */
export const LIFECYCLE = words({
  success: ["enabled", "active", "ACTIVE", "installed", "PUBLISHED", "PRODUCTION", "indexed", "running",
            "success", "applied", "released"],
  primary: ["VERIFIED", "SAVING"],
  warning: ["muted", "UNSAVED", "Example", "experimental"],
  danger: ["REVOKED", "deprecated"],
  neutral: ["paused", "unmuted", "disabled", "DRAFT", "NOT_PUBLISHED", "LOADING", "not_indexed", "locked",
            "unlocked", "auto-upgrade", "manual", "no deployment"],
});

/** Incidents. */
export const INCIDENT = words({
  warning: ["OPEN"],
  success: ["RESOLVED"],
  neutral: ["CLOSED"],
  danger: [],
  primary: [],
});

/** How a contract binding or a change relates to what is published. */
export const COMPATIBILITY = words({
  success: ["CURRENT", "NON_BREAKING", "SAFE"],
  warning: ["COMPATIBLE_STALE", "UNVERSIONED", "REVIEW"],
  danger: ["BROKEN", "NO_ACTIVE_REVISION", "BREAKING"],
  neutral: ["NO_CHANGE"],
  primary: [],
});
