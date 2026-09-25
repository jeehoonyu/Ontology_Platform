# Resume here — the Foundry look work

Started 2026-09-24 and updated at the end of each working session. The last update was
2026-09-25, after U4. Read this first, then the goal. Check `git status` and `git log` against
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

GOAL_LOOK: **U1–U4 are Met; U5–U11 are Open.** Nothing has been pushed. Never push
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
   | `python oms/test_style_tokens_audit.py` | 50 assertions (0 undefined names, 0 references, 661 raw colours) |
   | `python oms/test_route_payload_audit.py` | 42 assertions, shared closure 500 KB |
   | `python oms/audit_route_payload.py` | 17 routes, shared 511,615 B, three font lines, all shared |
   | `python oms/audit_route_cost.py` | passes; 266 requests on open across 16 routes |
   | `python oms/audit_frontier.py` | every gap owned; the largest is `raw_colour_ceiling` 661, held by U10 |
   | `python oms/audit_ratchet_motion.py` | 1 ≤ 1 |
   | `cd frontend && PYTHON_BIN=python npx playwright test look.spec.ts --project=desktop-1280` | 2 passed (needs a current build) |

3. If `frontend/dist` is stale, rebuild it with `python oms/measure_browser_evidence.py --build`.
   Check first that port 8010 is free, since another session may be serving it.

## Next: U5, body text 14px on an 18px line

The owner decided K (a). `:root` takes `font-size: var(--font-size-medium)` and
`line-height: var(--line-height-default)`; explicit sizes stay. It gets a commit of its own.
- **Before the change,** run `evaluator.spec.ts` twice on the U4 build and keep both screenshot
  sets. What differs between those two runs is noise, and is masked when before and after are
  compared. Don't reuse the census images: the face changed every one at U4, and one was taken
  mid-load.
- **The test:** `look.spec.ts::The body text is 14px on an 18px line`, shown to read 16px and
  `normal` with the change reverted and dist rebuilt.
- **Re-check** shell-widths, truncation-sites and the graph-editor fixtures (all in the full
  run). Watch for tests whose premise is a text width, as pane-layout's crowded title was at U4.
- **Then** run the full six-project run, re-record the browser-evidence baseline (the gates table
  asks for it at U5), and re-check route payload and route cost; neither should move.

After U5: U6 (buttons and inputs), U7 (headings, panels, panes, tables; pane titles at 14px is a
sub-commit of its own), U8 (status tags), U9 (sidebar colours), and U10 (primitives; the aliases
retire). U11 means writing the plan's A goal document.

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
- **Scratch specs** in `frontend/tests/` get picked up by full runs. Delete them, and their
  `.git/info/exclude` line, before measuring.
- **Git Bash** rewrites `/route` arguments (`MSYS_NO_PATHCONV=1`). Heredocs can mangle
  backslashes; write regex scripts with the Write tool.
- **The original** is signed in only in the user's Chrome. Use Claude in Chrome read-only and
  never type credentials. The JS tool returns about 1,000 characters; write results into an
  `<article>` and read them with `get_page_text`.

## Numbers to hold on to

| Measure | Value after U4 |
| --- | --- |
| Route payload | shared closure 511,615 B (U3 +13,218 B, U4 +47,636 B); every route re-baselined in the open |
| Route cost | 266 requests on open across 16 routes (U4 added the two preloaded faces to each) |
| Six-project run | 356 passed (the census's 354 plus two look tests), 1,024 skipped, 0 failed, 0 flaky; baseline re-recorded at U4 |
| Style tokens | 0 undefined names and references; 39 legacy alias uses (U10 retires them); 381 of 396 tokens unread |
| Raw colours outside `tokens.css` | 661 (U10 lowers it) |

## Other open threads

Three security findings noticed along the way were filed as separate tasks in the desktop app:
Object Explorer masking; Object Explorer action binding and the search cut; and search
incidents and media-set scoping.
