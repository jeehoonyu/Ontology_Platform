# Resume here — the Foundry look work

Started 2026-09-24 and updated at the end of each working session. The last update was
2026-09-25, after U9. Read this first, then the goal. Check `git status` and `git log` against
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

GOAL_LOOK: **U1–U9 are Met; U10 and U11 are Open.** Nothing has been pushed. Never push
tags.

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
   | `python oms/test_style_tokens_audit.py` | 50 assertions (0 undefined names, 0 references, 606 raw colours) |
   | `python oms/test_route_payload_audit.py` | 41 assertions, shared closure 507 KB |
   | `python oms/audit_route_payload.py` | 17 routes, shared 518,923 B, three font lines, all shared |
   | `python oms/audit_route_cost.py` | passes; 266 requests on open across 16 routes |
   | `python oms/audit_frontier.py` | every gap owned; the largest is `raw_colour_ceiling` 606, held by U10 |
   | `python oms/audit_ratchet_motion.py` | 1 ≤ 1 |
   | `cd frontend && PYTHON_BIN=python npx playwright test look.spec.ts --project=desktop-1280` | 13 passed (needs a current build) |

3. If `frontend/dist` is stale, rebuild it with `python oms/measure_browser_evidence.py --build`.
   Check first that port 8010 is free, since another session may be serving it.

## Next: U10, the primitives take the look

U10 is five commits: one per primitive, then one for the aliases. Each commit gets a
`look.spec.ts` test with UI_CONFIG's values, shown to fail with the primitive's CSS removed. It
deletes the per-screen CSS it replaces and lowers `raw_colour_ceiling` in the same change (K8).
What the survey after U9 found:

1. **Tag.** U8 already gave `.badge` the tag's CSS. What is left:
   - Two hand-rolled tags move onto `StatusBadge` (neutral), and their CSS goes: the agent
     runtime's event strip (`.agent-event-strip span`, `AgentRuntimePanel.tsx:279`) and the
     review tabs' counts (`.artifact-review-tabs button span`, `ArtifactReviewPanel.tsx:100,103`).
   - Three selectors name `.status-badge`, a class nothing renders; they meant `StatusBadge`:
     `.preview-row-list`, `.evaluation-qualification` and `.package-summary-row`.
   - Leave `.workspace-header > div:first-child span` alone. It is also Security's "SG" tile,
     and the resource header is the plan's Q5.
   - The test: a tag is 20px, radius 4, padding 2px 6px, 12px at 400.
2. **NonIdealState.** `EmptyState`'s card (`.state-block.empty-state-card`, 51 call sites; the
   16 `inline` ones stay `.empty`) becomes centred: title `--font-title-empty` (18px/20px 600)
   in `--text-muted`, one 14px muted line, and optionally a 48px muted icon. The CSS is
   `styles.css` ~4662–4736, plus `.empty-state-card span` in the `.hero-summary p` group.
3. **SectionCard** (`Panel`, `DataDisplay.tsx:7`). The header becomes 50px with padding
   `0 20px` and a rule (`--section-header-*`). Keep `section.panel > header.panel-header > h2`.
   Expect layout tests (pane-layout, shell widths) to notice the taller header.
4. **AppHeader** (`Page`, `Workbench.tsx:5`, 11 files). One `h1` at 16px 600
   (`--font-title-app`) in a 50px bar; the subtitle stays visible, since the evaluator reads it.
   `look.spec.ts` U4 already reads `.page-header h1` and `.page-header p`.
5. **Aliases.** The 39 `var(--border|--surface|--surface-strong|--accent|--muted|--text|--line)`
   sites in Decision, Ops and `.runtime-slo-row` move to the names the alias block maps them to
   (`tokens.css` ~522–540), and the block is deleted. `audit_style_tokens` must read 0 alias
   uses.

After U10: U11, writing the plan's A goal document.

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

| Measure | Value after U9 |
| --- | --- |
| Route payload | shared closure 518,923 B at its ceiling, re-baselined at U8 (U4's fonts +47,636 B; U5–U8's CSS and the intent vocabulary +7,308 B) |
| Route cost | 266 requests on open across 16 routes |
| Six-project run | 370 passed, 1,094 skipped, 0 failed, 0 flaky; baseline re-recorded at U9 (1,464 entries). Occasional single retries under full-run load (movement-contract, the evaluator's Ctrl+K, the map's feature count), each clean when repeated |
| Style tokens | 0 undefined names and references; 39 legacy alias uses (U10 retires them) |
| Raw colours outside `tokens.css` | 606 (U8 took 7 and U9 23; U10 lowers it) |
| Status badges on the evaluator routes | 46: 20 success, 16 neutral, 7 warning, 3 danger |

## Other open threads

Three security findings noticed along the way were filed as separate tasks in the desktop app:
Object Explorer masking; Object Explorer action binding and the search cut; and search
incidents and media-set scoping.
