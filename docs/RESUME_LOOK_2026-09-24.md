# Resume here — the Foundry look work

Started 2026-09-24 and updated at the end of each working session. The last update was
2026-09-26, after GOAL_FOUNDATIONS A6 was met. Read this first, then the goal. Check `git status` and `git log` against
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
| `2b87964` | This note, updated |
| `03a3237` | **A2**: `lib/storage.ts` guards storage; `ScreenBoundary` keeps the shell standing; `frontend/tests/trust.spec.ts` begins |
| `d5c8164` | **A3a**: Platform Graph no longer promises to expand neighbourhoods |
| `db24fe8`, `356ec94` | **A3b**: Automate says "disabled", not "paused" (the second commit regenerates a stale reference the first let through) |
| `d999cc3` | **A3c**: the release endpoint refuses a gate-blocked submission; the button reads the Gates tab (`oms/test_model_release_gate.py`) |
| `dfb3056` | **A3d**: Ops' test-event form has its own severity and source |
| `9cd9395` | **A3e**: Vertex draws the server's layouts and the filter's fade; A3 Met |
| `83fd189` | **A4**: both grant forms say they do not govern data access (`oms/test_grants_do_not_govern_reads.py`); A4 Met |
| `d9fe84a` | This note, updated |
| `7cb56ad` | **A9**: `frontend/src/apps.json` is the one app registry; the server's `WORKSPACE_VIEWS` is held to it (`oms/test_workspace_registry.py`); A9 Met |
| `15e664c` | **A8, 1**: `components/layout/Tabs.tsx` (`Tabs`, `SegmentedControl`); Decision and Ontology Health adopt; `Tabs` rides in `dragdrop-vendor` |
| `fcc6104`, `4d8697a`, `088f3e0`, `4e01505`, `59ec98e`, `129dea3` | **A8, 2–7**: Ops, ModelOps, Security and Control Panel, the drawer (tint), the artifact review (tablist), Delivery and the breakpoint; A8 Met |
| `f09a564` | The collaboration WebSocket and both event streams read their logs off the event loop (`oms/test_collaboration_socket_off_loop.py`) |
| `0a6613d` | This note, updated |
| `752572e` | **A7, 1**: `components/layout/Dialog.tsx`; the command palette and Object Explorer's action dialog adopt it (`frontend/tests/overlays.spec.ts`) |
| `108e8bc` | The owner's decisions: N (a), menus stay buttons; A5's existing media sets stay unassigned |
| `2d3bba0` | **A5**: search scopes incidents; media sets gain `project_id` (migration `0048`); the gate reads its checks once; four baselines re-recorded at `0048`; A5 Met |
| `715086b` | This note, updated |
| `294b5c5`, `09fabbe` | Another session's work: Security's grants picker named, every Security and Control Panel tab under axe; Data & Media's upload routes wrap at 375px |
| `f951fda` | **A7, 2**: `components/layout/Menu.tsx` and `placement.ts`, a disclosure that floats; the pipeline strip's unsaved-changes list adopts it; route payload re-baselined in the open |
| `67427c8` | **A7, 3**: `components/layout/Tooltip.tsx`; the canvas's zoom buttons and edge inserts and Workshop's Layout, Duplicate and Delete node adopt it; `Tooltip` and `placement` ride in `dragdrop-vendor` |
| `7b83488` | This note; `audit_ratchet_motion` locked at 0 (all 20 ratchets have fallen at least once) |
| `bee53c5` | Decisions U–X recorded as assumed (the plan's table) |
| `b0ffc66` | **A6, 1**: `routes.json`, `navigate`/`useRouteParams`/`navigateHref`, `workspace_routes.py`, Ops' `?tab=`, `UnknownResource`, ScreenBoundary cleared by a history step (`frontend/tests/routes.spec.ts`, `oms/test_workspace_routes.py`) |
| `8f243a7` | The shell-widths strip tests unroute with `ignoreErrors`, so a late canvas answer cannot fail them |
| `2dc19ba` | **A6, 2**: Data & Media's `?dataset=`; answers carry their id; quarantine and imports links from the table |
| `ccd7afb` | Another session: the evaluator's sweep covers every registered workspace and measures `main.workspace`'s scroll; it lands with 14 known failures |
| `fa8b6c7` | **A6, 3**: Pipeline Builder's `?graph=`; outputs, contracts and failures carry their pipeline; late creates never open over a move; the Command Center's newest pipeline scoped to the viewer |
| `82385c0` | This note, updated |
| `bf50b82`, `f634ead` | **A6, 4**: the builders' `?artifact=`; the list asked again before an id is called unknown; undo history cleared per artifact |
| `c2c0d2f` | **A6, 5**: Object Explorer's `?type=&object=`; latest-only queries tied to the type; the profile tied to its object and refreshable |
| `64738d4` | Another session: a long pipeline name wraps in the header |
| `ac32af8` | **A6, 6**: Ontology Manager's `?type=&section=&page=`; no hand-built workspace link left; route payload re-baselined |
| `98d896d` | **A6, 7**: Object Explorer's `?q=`, the first filter, replaced and never pushed |
| `e567069` | **A6 Met**: the final spec fails 22 of 24 at `38b096a`; default tier 27 of 27 |

GOAL_LOOK: **Met, U1–U11.** Nothing has been pushed. Never push tags. The work continues in
[`GOAL_FOUNDATIONS_2026-09-25.md`](GOAL_FOUNDATIONS_2026-09-25.md): A1–A6, A8 and A9 are Met; A7
is Open. A6 is Met. A7's Dialog, Menu and Tooltip are all in and adopted; it stays Open only as the
owner of `raw_colour_ceiling` (see Next).

**Decided 2026-09-26:** N (a), tabs and menus stay buttons; and for A5, existing media sets stay
unassigned until someone assigns them.

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
   | `python oms/test_style_tokens_audit.py` | 51 assertions (0 undefined names, 0 references, 563 raw colours, no alias used or defined) |
   | `python oms/test_route_payload_audit.py` | 41 assertions, shared closure 511 KB |
   | `python oms/audit_route_payload.py` | 17 routes, shared 516 KB measured against a 523,573 B record (re-baselined at `f951fda`) |
   | `python oms/audit_route_cost.py` | passes; no route issues more requests than it did |
   | `python oms/audit_frontier.py` | every gap owned; the largest is `raw_colour_ceiling` 563, held by GOAL_FOUNDATIONS A7 |
   | `python oms/audit_ratchet_motion.py` | 0 ≤ 0 |
   | `cd frontend && PYTHON_BIN=python npx playwright test look.spec.ts --project=desktop-1280` | 29 passed (needs a current build); `trust.spec.ts` 12 passed; `overlays.spec.ts` 22 passed |

3. If `frontend/dist` is stale, rebuild it with `python oms/measure_browser_evidence.py --build`.
   Check first that port 8010 is free, since another session may be serving it.

## Next: the owner's decisions, then A7's last question

1. **Decisions U–X are assumed, not decided** (the plan's owner-decisions table, 2026-09-26):
   `page` names an ontology-level panel (U a); old spellings are not read (V a); the server
   keeps a copy of the route table (W a); the node context menu's look waits for Y15, so A7
   stays Open as `raw_colour_ceiling`'s owner (X b). Ask the owner. A6 is built on U, V and W;
   each is cheap to change.
   **2026-10-01:** the next goal is stated, at the owner's request:
   [`GOAL_HOME_2026-10-01.md`](GOAL_HOME_2026-10-01.md), the plan's wave 2 (H1–H16 and A10),
   re-read against `27cc953`. Its H7 names `raw_colour_ceiling`, so the ceiling now has two
   open owners and A7 can be marked Met on the owner's word. It assumes H (b) as H7b, T, X (b)
   and a new decision Z (Home replaces Command Center as the default route). Committed as `1270d0c`.
2. **A7** closes when `raw_colour_ceiling` has another open owner: either X (a), the node context
   menu's look inside A7 (563 → 556, then A7 can be marked with the ceiling passed on), or the
   next goal taking the ceiling. With A7 the only open condition, GOAL_FOUNDATIONS is otherwise
   done; the plan's next wave (H, home and shell) is where the next goal would come from, and
   stating it is the owner's call.
3. **The evaluator sweep's sixteen failures** (another session's `ccd7afb`) are that thread's;
   two of them, which need a used database, are filed as their own task. Don't re-record the
   browser-evidence baseline while they stand: it would record them as known.
4. The default tier suggests re-measuring `tier-a-baseline.json` (32.8 days old).
5. **The Platform Graph retry is fixed.** The test at 1366 timed out because
   `/project/readiness` built the whole project snapshot on every page load. That was 1.0 s of
   Python per call late in a run, and calls queued two dozen deep. Readiness now reads only the
   snapshot's collection names, and the test takes 0.6 s with no retry. The details are in
   `GOAL_FOUNDATIONS_2026-09-25.md` under A8. It was not the WebSocket (`f09a564`), the SQLite
   lock wait or the thread limit.
6. **A migration re-records four baselines.** Adding one stamps query-bounds, request-cost,
   suite-cost and browser-evidence as past their life. Re-record them:
   `audit_query_bounds.py --set-baseline`, `audit_request_cost.py --write-baseline`,
   `measure_suite_cost.py` (about 20 minutes) and then `audit_suite_cost.py --write-baseline`,
   and a full run. The suite-cost census is also the only check that sees repeated query
   shapes: run it after any backend change.

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
- **Gate commits on the fast tier's exit code**, not on `| tail`. Piping swallowed a failure
  once (`db24fe8`). Use `python oms/verify.py --fast > log; rc=$?`.
- **The route-cost measurement clears `frontend/test-results`.** Copy a run's failure
  artifacts (traces, error context) before measuring route cost.
- **Scratch specs** in `frontend/tests/` get picked up by full runs. Delete them, and their
  `.git/info/exclude` line, before measuring.
- **Git Bash** rewrites `/route` arguments (`MSYS_NO_PATHCONV=1`). Heredocs can mangle
  backslashes; write regex scripts with the Write tool.
- **A negative run that fails in setup proves nothing.** Four Menu mutations first failed at
  "typing into a node's form did not count as unsaved": editing a second node raced the form
  switching over. Read where each failure lands, fix the setup, and run the mutation again.
- **The pipeline page at 1280×900:** the strip sits in no scroll box; the pane host scrolls, and
  typing into the node form scrolls it away from the canvas (call the canvas back before a
  lasso). The zoom buttons sit at the canvas's foot, below the pane host's fold, so
  `scrollIntoViewIfNeeded` before any `mouse.move` onto them. The selected node's context menu
  opens to its right, tall enough at 1.35 zoom to cover both edge inserts; select d.
- **A lasso covers what it crosses.** Its rectangle lies over the canvas, so a test that ends
  a lasso on a button proves nothing about that button's pointer handling; hold a button down
  from bare page instead.
- **Late-run backend stalls** can fail a test whose route handler fetches after the test ends
  (the shell-widths strip test once, teardown past 45 s). It passed alone and in the next run;
  the stall was readiness's queue, fixed with the retry (item 5).
- **The evaluator sweep fails 14 to 16 tests on master** since `ccd7afb` (another session's):
  control-panel and security at 375, data-media and analytics in axe, and, with a well-used
  database, Imports' metric overflow and an Automate scroll box (filed as a task). Compare a
  full run's failures against that list before calling anything a regression.
- **Playwright can orphan its web server on Windows.** A later run then fails with "port 8021
  is already used". Find the uvicorn on the port (`Get-NetTCPConnection -LocalPort 8021`), check
  its command line is this session's, and stop it. Never touch 8010.
- **A test that relies on data it did not make passes in a full run and fails alone.** Negative
  runs start from a fresh database, so they find it: create what the test reads.
- **The original** is signed in only in the user's Chrome. Use Claude in Chrome read-only and
  never type credentials. The JS tool returns about 1,000 characters; write results into an
  `<article>` and read them with `get_page_text`.

## Numbers to hold on to

| Measure | Value after U11 |
| --- | --- |
| Route payload | re-baselined at `ac32af8` (A6's table and navigation in the entry chunk, and `64738d4`'s CSS); earlier at `f951fda` for the Menu |
| Route cost | 266 requests on open across 16 routes. One reading taken straight after a full run once gave Automate 8, and it read 13 when measured again |
| Six-project run | 483 passed at `98d896d`, with the evaluator sweep's 16 known failures (another session's). 432 passed at `67427c8`, 0 failed, none flaky. Earlier: 399 passed, 1,239 skipped, 0 failed; baseline re-recorded at A5, migration head `0048` (1,638 entries). The Platform Graph test at 1366 usually retries once | Known single retries under full-run load: movement-contract, the evaluator's Ctrl+K, the map's feature count, and `net::ERR_NO_BUFFER_SPACE` on a reload. Each was clean when repeated |
| Style tokens | 0 undefined names and references; 0 legacy alias uses (the block is gone) |
| Raw colours outside `tokens.css` | 563 (661 at U1's census); held by GOAL_FOUNDATIONS A7 |
| Raw empty states | 7 (`audit_ui_states`), from 32 |
| Look tests | 29 in `look.spec.ts`, 12 in `trust.spec.ts`, 22 in `overlays.spec.ts` (Dialog 2, Menu 7, Tooltip 13), 24 in `routes.spec.ts`, each shown to fail with what it defends removed |
| Tenancy | `unscoped_reads_ceiling` 344, `tenant_orphan_ceiling` 50 (from 52 at A5) |

## Other open threads

Three security findings noticed along the way were filed as separate tasks in the desktop app:
Object Explorer masking; Object Explorer action binding and the search cut; and search
incidents and media-set scoping.
