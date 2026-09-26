# Resume here — the Foundry look work

Started 2026-09-24 and updated at the end of each working session. The last update was
2026-09-25, after U11: GOAL_LOOK is Met. Read this first, then the goal. Check `git status` and `git log` against
it before trusting it.

## Where things stand

| Commit | What |
| --- | --- |
| `c08a73a` | [`UI_CONFIG.md`](UI_CONFIG.md), [`FOUNDRY_UI_PLAN_2026-09-24.md`](FOUNDRY_UI_PLAN_2026-09-24.md), [`GOAL_LOOK_2026-09-24.md`](GOAL_LOOK_2026-09-24.md), [`frontend/src/tokens.css`](../frontend/src/tokens.css) |
| `2b2e0c3` | **U1**: `oms/audit_style_tokens.py` counts undefined custom properties and raw colours |
| `836a67d` | **U2**: the route-payload gate weighs fonts |
| `20b5f20` | The census "before U1" ([`look-census-before-u1.json`](look-census-before-u1.json)), and the owner's decisions J, G, L, K and H |
| `e81cf4e` | Route cost fixed: the 663-byte `graphLayout` chunk folded into `dragdrop-vendor`, so graph and pipeline are back at their request ceilings |
| `4302225` | **U3**: `tokens.css` imported before `styles.css`; the seven undefined names resolve; `frontend/tests/look.spec.ts` begins |
| `00a620d` | **U4**: Source Sans 3 (400, 400 italic, 600) bundled from `@fontsource/source-sans-3@5.3.0` in `frontend/src/assets/fonts/`, with `fonts.css`, the preloads and `var(--font-family)` |
| `32d53a0` | This note |
| `0133bd8` | **U5**: body text 14px on an 18px line |
| `5e4bbdb` | The narrow top bar kept to its contents on short pages (`.app-shell` rows `auto 1fr`), found while measuring U5 |
| `fa95d93` | This note, updated |
| `abd02d3` | **U6, buttons**: `:where(button)` base, the ring as the border, primary and friends, opt-outs, the small canvas toolbar |
| `9797be1` | **U6, fields**: one base rule for text inputs, selects and textareas, a focus halo, disabled fields; U6 Met |
| `8735cf9` | This note, updated |
| `b686e61` | **U7, 1**: card titles 14px/16px 600, panels as ring-shadow cards, the `#f6f7f9` ground |
| `a6246f6` | **U7, 2**: panes and pane headers ruled with the divider |
| `ce87e4d` | **U7, 3**: tables — 30px uppercase muted header, 40px rows, `0 11px` cells, ink rules |
| `48937ed` | **U7, 4**: pane titles 14px 600; U7 Met |
| `1b05324` | This note, updated |
| `2b90ee3` | **U8**: `StatusBadge` takes its intent from the caller (`components/data/intents.ts`); 20px tags; OFFLINE no longer reads as success; warning text `#935610` |
| `17f4ec9` | **U9**: the sidebar in the original's dark gray, 400 labels, 600 on the active item; still 286px |
| `8bd4a56` | `test_route_payload_audit` proves the graph split by the graph screens' own bytes, not `shared < 500 KB`, which U8's re-baseline had broken |
| `ef69159` | This note, updated |
| `0537980` | **U10, 1 (Tag)**: the last hand-made tags use `StatusBadge`; the dead `.status-badge` selectors name `.badge` |
| `f598d63` | **U10, 2 (NonIdealState)**: `EmptyState`'s card centred with a 48px icon and an 18px muted title; 25 raw empty divs through `EmptyState inline` (raw-empty ceiling 32 → 7) |
| `764e10b` | **U10, 3 (SectionCard)**: every `Panel` has a 50px ruled header over a 20px body (`--panel-padding`); Object Explorer's inspector is a focusable region |
| `38b096a` | **U10, 4 (AppHeader)**: `Page`'s name is a 16px 600 `h1` in a 50px white bar running to the workspace's edges (`--workspace-gutter`) |
| `46bc6e3` | **U10, 5**: the 39 legacy alias uses moved to real tokens and the alias block deleted; U10 Met |
| `935f5d8` | **U11**: [`GOAL_FOUNDATIONS_2026-09-25.md`](GOAL_FOUNDATIONS_2026-09-25.md) states the plan's A goal; GOAL_LOOK Met |

GOAL_LOOK: **Met, U1–U11.** Nothing has been pushed. Never push tags. The work continues in
[`GOAL_FOUNDATIONS_2026-09-25.md`](GOAL_FOUNDATIONS_2026-09-25.md): A1 is Met (through U8), and
A2–A9 are Open.

**Decided 2026-09-25**, recorded in the plan with the options offered:
- J (a): `tokens.css` imported whole.
- G (a) and L (a): Source Sans 3 (400, 400 italic, 600), vendored as woff2 with its licence and
  a checksum header.
- K (a): body text 14px on an 18px line.
- H (a): the sidebar takes the original's colours and keeps 286px.

I, M and N are still undecided, and the goal assumes their option (a).

## First ten minutes back

1. Run `git status`. Only this file may show as changed; anything else is new since this was
   written.
2. Re-run the checks:

   | Command | Expected |
   | --- | --- |
   | `python oms/verify.py --fast` | 25 of 25 |
   | `python oms/test_style_tokens_audit.py` | 51 assertions (0 undefined names, 0 references, 599 raw colours, no alias used or defined) |
   | `python oms/test_route_payload_audit.py` | 41 assertions, shared closure 507 KB |
   | `python oms/audit_route_payload.py` | 17 routes, shared 518,923 B, three font lines, all shared |
   | `python oms/audit_route_cost.py` | passes; 266 requests on open across 16 routes |
   | `python oms/audit_frontier.py` | every gap owned; the largest is `raw_colour_ceiling` 599, held by GOAL_FOUNDATIONS A8 |
   | `python oms/audit_ratchet_motion.py` | 1 ≤ 1 |
   | `cd frontend && PYTHON_BIN=python npx playwright test look.spec.ts --project=desktop-1280` | 18 passed (needs a current build) |

3. If `frontend/dist` is stale, rebuild it with `python oms/measure_browser_evidence.py --build`.
   Check first that port 8010 is free, since another session may be serving it.

## Next: GOAL_FOUNDATIONS, starting with A2

GOAL_LOOK is finished. Its successor for the look is the plan's H goal (home and shell), which
is not stated yet. What comes next is
[`GOAL_FOUNDATIONS_2026-09-25.md`](GOAL_FOUNDATIONS_2026-09-25.md), the plan's A goal: wave 0's
trust fixes (A2–A5), then wave 1's foundations (A6–A9). Its "What is true today" table was
re-read against the code at `38b096a`, with file and line for each claim.

1. **A2**: blocked or corrupt storage blanks the app. Five unguarded storage calls, and no error
   boundary. The test goes in a new `frontend/tests/trust.spec.ts`.
2. **A3, a to e**: one commit per screen. A3c (ModelOps) is the serious one: the release
   endpoint marks a gate-blocked submission released before the release is refused, so the fix
   is in `oms/app/modeling.py` as well as on the button.
3. **A4**: the grant forms say they do not govern data access, until decision O.
4. **A5**: search incidents and media sets scoped. It needs a migration, and the owner's choice
   of project for existing media sets (the goal assumes none). A separate task was already filed
   for this. Check whether it landed before starting.
5. **A6–A9**: routes, overlays, Tabs (which own `raw_colour_ceiling`), and the app registry.

Also filed as its own task, found while measuring U10: Control Panel's workspace scrolls
sideways by 125px at 375. It is older than U10.

## How each step is measured

- **The census** is [`look-census-before-u1.json`](look-census-before-u1.json). Its screenshots
  and reports are in `look-census/` at the repo root, which is local and excluded in
  `.git/info/exclude`: `before-u1/`, `after-u3/`, and `noise-u3/` (two runs of one build).
  `look-census/record_census.py` writes a record from a step's folder.
- **The full six-project run:**
  `PYTHON_BIN=python python oms/measure_browser_evidence.py --run --out <abs path>`, then
  `python oms/audit_browser_evidence.py <path>`. It takes about 8 minutes, and Playwright wipes
  `frontend/test-results/` each run, so copy the screenshots out straight away.
- **Route cost:** `PYTHON_BIN=python python oms/measure_route_cost.py`, then
  `python oms/audit_route_cost.py`.
- **Screenshots are noisy.** Two runs of one build differ on 15 of 55: map, models, object
  explorer, ontology, pipeline, workshop and the industrial report. Decision and Ops are stable.
  The census's tablet-768 pipeline image was taken mid-load. Before any screenshot comparison
  (U5), take the before set twice just before the change and mask what moves between the two.
- **Negative runs rebuild dist:** fix, see green, break, build, see red, restore, build, see
  green. Check that the restored files are byte-identical and that the source hash matches.

## House rules this work follows

- **Condition bullets:** `- **U4 — Title.** **Open|Met** — …`. `audit_frontier` reads only the
  title and the first 120 characters of the body when deciding who owns a ceiling.
- **Negative runs:** every test is shown to fail with the thing it defends removed, with its own
  message, and the goal quotes the messages.
- **K8:** a lowered ceiling is re-recorded in the same change. `audit_ratchet_motion` allows one
  ceiling recorded twice without falling, and that allowance is used (1 ≤ 1). It reads only
  top-level `*_ceiling` keys.
- **A new audit** touches seven places; the template is commit `27d4045`, and U1 follows it.
- **Commits:** one per step, each measured, on `master`, only when the user asks, never pushed,
  with the `Co-Authored-By` trailer.
- **Test hooks stay:** panels keep `section.panel > header.panel-header > h2`; the classes tests
  use stay on the root element; control heights are `min-height`.

## Gotchas met so far

- **Python:** `oms/venv` is broken; it points at a Python 3.13 under another user. Use the
  system Python 3.12 with `PYTHON_BIN=python`, because the Playwright config otherwise falls to
  the Windows Store `python3` stub.
- **Port 8010** may be another session's; don't kill it. The memory note has the port-8011
  override recipe.
- **Line endings:** files are CRLF in the working tree (`core.autocrlf=true`). A scripted edit
  that matches `\n` silently misses. This happened once in a U3 negative run, which had to be
  redone.
- **Throwaway worktrees for measuring builds:** link `node_modules` with `cmd //c mklink //J`,
  and remove the link with `cmd //c rmdir` *before* `git worktree remove --force`.
- **The fast tier runs no `oms/test_*.py`.** A baseline change can break one unseen, as U8's
  payload re-baseline broke `test_route_payload_audit`. After re-baselining anything, run that
  baseline's own test, and run the default tier (about 25 minutes) before believing a step.
  Don't rebuild `dist` while it runs.
- **Scratch specs** in `frontend/tests/` get picked up by full runs. Delete them, and their
  `.git/info/exclude` line, before measuring.
- **Git Bash** rewrites `/route` arguments (`MSYS_NO_PATHCONV=1`). Heredocs can mangle
  backslashes; write regex scripts with the Write tool.
- **The original** is signed in only in the user's Chrome. Use Claude in Chrome read-only and
  never type credentials. The JS tool returns about 1,000 characters; write results into an
  `<article>` and read them with `get_page_text`.

## Numbers to hold on to

| Measure | Value after U11 |
| --- | --- |
| Route payload | shared closure 518,923 B at its ceiling, re-baselined at U8; measured 508 KB after U10 (inside the 8 KB tolerance) |
| Route cost | 266 requests on open across 16 routes. One reading taken straight after a full run once gave Automate 8, and it read 13 when measured again |
| Six-project run | 375 passed, 1,119 skipped, 0 failed, 0 flaky; baseline re-recorded at U10's last commit (1,494 entries). Known single retries under full-run load: movement-contract, the evaluator's Ctrl+K, the map's feature count, and `net::ERR_NO_BUFFER_SPACE` on a reload. Each was clean when repeated |
| Style tokens | 0 undefined names and references; 0 legacy alias uses (the block is gone) |
| Raw colours outside `tokens.css` | 599 (661 at U1's census); held by GOAL_FOUNDATIONS A8 |
| Raw empty states | 7 (`audit_ui_states`), from 32 |
| Look tests | 18 in `look.spec.ts`, each shown to fail with what it defends removed |

## Other open threads

Three security findings noticed along the way were filed as separate tasks in the desktop app:
Object Explorer masking; Object Explorer action binding and the search cut; and search
incidents and media-set scoping.
