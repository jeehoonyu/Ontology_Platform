# UI config — what the original looks like, in numbers

Read on 2026-09-24 from the live enrollment, with `getComputedStyle` in a signed-in browser, on
sixteen surfaces in fifteen captures: the home page, Quicksearch, the Notifications popover, the Applications
launcher, Files, a project folder, a dataset, Object Explorer's home, an exploration, an Object
View, a menu, a Workshop module at runtime (*Common Operating Picture*), the Pipeline Builder
with a nine-node pipeline, the Ontology Manager on an object type, an app landing page
(Contour) and a resource dialog. The values are the config in
[`frontend/src/tokens.css`](../frontend/src/tokens.css); this document says where each came from
and how it is used, so a value can be re-read rather than trusted.

The first version of this document, written in the morning from four surfaces, was wrong in
places. Every value in it was checked against the afternoon's captures by two independent
readers and a third that tried to refute each correction; 101 corrections survived and 7 were
overturned. The ones that change a decision are listed under
[What changed since the morning](#what-changed-since-the-morning).

Where a value is an inference or a choice we make — a font we can ship, a fallback — it says so.
Where something was not measured, [the last section](#what-was-not-measured) says that too.

## The one fact that explains the rest

**The original is Blueprint 6 with Source Sans Pro, and it reads as one product because every
screen draws from one table.** Its `:root` exposes 206 custom properties: 205 `--bp-*` in five
families (emphasis, intent, palette, surface, typography) and one `--bp6-button-*` alias.
Around them, the components render the same values everywhere: a 4px default radius, a 30px
control height, 14px body text in two weights, a black-ink hairline at 15%, and one overlay
shadow.

It is not perfectly uniform, and the config does not pretend it is. Table headers are 30px on
Files and 40px on the home page; they are 400 weight on Files and 600 in a project folder;
app-header rules are ink alpha in Files and a solid `#dce0e5` in the Ontology Manager. Where the
original varies, the config names the variants and picks a default.

Ours has none of that table. `frontend/src/styles.css` is 6,756 lines with zero custom
properties, 308 distinct hex colours (233 of them used once), eleven radius values, no body
font size (so text is the browser's 16px), and 39 references to seven variables nobody defines
(`--border`, `--muted`, `--accent`, `--surface`, `--surface-strong`, `--text`, `--line`), which
leaves the Decision and Ops screens without borders or active-tab marks today. The gap in look
is not taste; it is the absence of a table.

## How to read the numbers

- **CSS pixels at a 2560 × 1249 viewport (Files at 2560 × 1305), device ratio 1.5.** Widths such as the 1200px home
  search are at that width; heights and paddings do not depend on it.
- **Border hairlines are one device pixel.** Every 1px border reads as `0.666667px` at a 1.5
  ratio, because Chromium snaps border widths; `1px` in the token file gives the same result.
  Rules drawn as `0 1px` / `0 -1px` box-shadows compute at 1 CSS px and are not snapped.
- **Graph sizes are graph units.** The Pipeline Builder graph is SVG under a zoom transform;
  node sizes come from the SVG attributes and equal CSS pixels at zoom 1. The morning's
  194 × 58 node was a screen reading at another zoom (194/200 and 58/60 put it near 0.97).
- **Colours that computed as `oklch(...)`** are Blueprint's colour-mix output and were converted
  back: `oklch(0.2449 0.0136 253.1)` is `#1c2127`, `oklch(0.6839 0.0306 257.1 / .15)` is a lightened
  gray-1 (≈ `rgb(142,155,173)`, a few units from gray-3) at 15%, which other surfaces compute
  as `rgba(143,153,168,.15)`, `oklch(0.2829 0.0147 257.1)` is `#252a31`.

## Type

| Tier | Value | Where it was read |
| --- | --- | --- |
| family | `Source-Sans-Pro` (the `Helvetica, sans-serif` fallback is from the morning read) | the first family of every text node on home (78 of 78) |
| faces loaded | 400, 400 italic, 600; 700 on chart pages; Source Code Pro 400 on the dataset grid | `document.fonts` per page |
| body | **14px / 18px** (1.28581), 400, `#1c2127` | every surface |
| small | 12px: hints, table headers, section labels, timestamps, counts, join input rows | Files, OE, PB |
| card and panel title | **14px 600**; line-height 16px on section cards, "Shortcuts" and dialog section titles; 18px on Files' "Filters" and exploration chart cards | section cards (OV, OM), "Shortcuts", "Manage roles"; "Filters", chart cards; PB panel (line-height not read) |
| app name | **16px / 19px 600** | Ontology Manager header; `#404854` on landing headers |
| section heading | **16px / 16px 600** | home: "Get started", "Recent", "Recommended applications" |
| page heading | **18px / 23px 600** | OM object-type title, a project's "Files" |
| empty-state title | 18px / 20px 600 in `#5f6b7c` | OE, Contour |
| landing hero | 22px / 25px 600 | Contour home |
| prominent value | 22px / 28px 600 | Object View |
| metric value | 24px / 31px **400** | Workshop KPI row |
| display | 36px / 40px 400 | the home welcome, and nowhere else |
| weights | 400 and 600 by token; 400 italic for "No value" and empty text; a 700 face loads for chart labels; 700 and 900 appear as outliers on notification titles | font census |
| text | rest `#1c2127`, hover `#111418`, muted `#5f6b7c`, disabled `#8f99a8`, link `#215db0` | typography tokens; links |
| on dark | `#f6f7f9`; muted `#abb3bf`; link `#8abbff` | sidebar, overlays, Workshop |

**Titles are bold and modest, not large.** A card or panel title is 14px 600; an app name or a
home section is 16px 600; a page heading inside content is 18px 600. The only large type is the
home welcome (36px 400), a landing hero (22px) and data values (22–24px). Ours puts a 25px `h1`
on the 15 of 23 screens that use `Page` (20px in Visual Builder) and a 15px `h2` on every
`Panel`.

Labels come in three kinds. **Section labels** on dark ground are 12px 600 uppercase `#abb3bf`
(`APPLICATIONS`, `CARRIER NAME`); Quicksearch's group headers ("RECENT SEARCHES", "JUMP TO") are
the same at 400. **Field and column labels** on light ground are 12px 400 `#5f6b7c` (facet
sections, "Quick filters", PB output settings), uppercase only in light table headers. **Keys in
key/value rows** (Object View, the dataset panel, the Ontology Manager) are 14px 400 `#5f6b7c`,
and Object View's linked-objects table headers are 14px muted, not uppercase.

Ship note: Source Sans Pro is published today as Source Sans 3. Bundle 400, 400 italic and 600
(three `@font-face` rules; our stylesheet sets `font-synthesis: none`, so a missing italic
renders upright). Keeping Inter is a product choice, not parity.

## Colour

**Palette.** Blueprint's fourteen hues in five steps, plus grays: all 87 values are in the token
file exactly as the original lists them. The morning's file named `#7961db` "violet"; it is
**indigo-3**. Violet-3 is `#9d3f9d`.

**Intents.** Rest is step 3, hover step 2, active step 1, disabled step 4.

| Intent | rest | hover | active | disabled | foreground |
| --- | --- | --- | --- | --- | --- |
| primary | `#2d72d2` | `#215db0` | `#184a90` | `#4c90f0` | `#fff` |
| success | `#238551` | `#1c6e42` | `#165a36` | `#32a467` | `#fff` |
| warning | `#c87619` | `#935610` | `#77450d` | `#ec9a3c` | `#111418` |
| danger | `#cd4246` | `#ac2f33` | `#8e292c` | `#e76a6e` | `#fff` |
| default | `#5f6b7c` | `#404854` | `#383e47` | `#8f99a8` | `#fff` |

Intent text on a 10% tint uses the hover step: a warning tag is `#935610` on orange at 10%, a
success tag `#1c6e42` on green at 10%.

**Grounds.**

| Ground | Value | Where |
| --- | --- | --- |
| app | `#f6f7f9` | behind cards in Files, OE explorations, Object View and the dataset grid (OE home is white) |
| card | `#fff` | content cards, panels, tables |
| container card | `#f6f7f9` | home right column (on white); Files' outer filter card (on the `#f6f7f9` page, set apart only by shadow-0) |
| canvas | `#edeff2` | graph canvas, document tab strip |
| code | `rgba(255,255,255,.7)` | `--bp-surface-color-code` |

**Selection is a family, not one colour.** The same blue appears at three strengths, and two
neutrals cover the rest:

| State | Fill | Text | Where |
| --- | --- | --- | --- |
| selected (default) | `rgba(45,114,210,.1)` | `#215db0` | tint tabs, menu choices, list rows, home pill |
| selected, strong | `rgba(45,114,210,.2)` | `#215db0` | project vertical tabs |
| selected, pill | `rgba(45,114,210,.3)` | `#184a90`, 600 | pill toggles on OE and Contour, dialog nav |
| resource nav | `rgba(138,187,255,.1)` | `#215db0` | Ontology Manager nav |
| neutral | `rgba(56,62,71,.16)` | — | segmented control, active icon-rail button (+ 1px `rgba(95,107,124,.25)`) |
| minimal hover | `rgba(143,153,168,.15)` | — | menu item, minimal button, unselected pill |
| sidebar active | `#1c2127` | label 600 | the sidebar |
| sidebar hover | `#383e47` | — | the sidebar |

**Lines.** Most rendered dividers are black ink at an alpha, drawn as a border or a
`0 1px` / `0 -1px` box-shadow: `rgba(17,20,24,.15)` for header rules, table rules and panel
edges; `.1` for project-table rows and drawer edges; `.08` between result-list rows; `.4` on
dark ground. The Blueprint strong border token (`rgba(95,107,124,.25)`) appears on outlined
buttons and the active rail item; the default one (`.12`) was not seen rendered. Some apps use a solid light gray instead: `#dce0e5` in the
Ontology Manager and the PB rail, `#d3d8de` under resource and landing headers, `#e5e8eb` in the
dataset panel, `#c5cbd3` under the grid toolbar and around graph nodes.

## Surfaces

| Token | Value |
| --- | --- |
| radius | **4px** by default: cards, buttons, inputs, tags, menus, dialogs, nav items |
| other radii | 2px graph nodes, swatches, bars · 3px Workshop inner cards and the graph legend · 5px the home AI banner · 8px the dark Quicksearch · 18/20px the Files and home pill searches · **30px** Blueprint round tags, pill toggles and the Object Explorer pill searches · 50% avatars and dots |
| spacing | 4px unit; measured paddings include 2, 5, 6, 7, 8, 10, 11, 12, 14, 15, 16, 17, 20, 24, 30, 35, 50 |
| card | shadow-0 `0 0 0 1px rgba(0,0,0,.15), 0 0 5px rgba(0,0,0,.02)`, no border; `#fff` on `#f6f7f9`, or `#f6f7f9` on white (home) or on `#f6f7f9` (Files' outer card) |
| raised card | shadow-1 (the home Recent table) |
| overlays | popovers, menus, tooltips and light dialogs all use shadow-3 with an ink ring: `0 0 0 1px rgba(17,20,24,.1), 0 20px 25px -5px rgba(0,0,0,.1), 0 10px 15px -3px rgba(0,0,0,.1)` |
| backdrop | `rgba(17,20,24,.7)`, behind light and dark dialogs alike |
| focus | outline 2px `#2d72d2`, offset 2px; an input takes a 1px `#4c90f0` border and a 3px `rgba(76,144,240,.3)` halo |
| motion | 0.1s, `cubic-bezier(.4,1,.75,.9)`; a bounce `cubic-bezier(.54,1.12,.38,1.11)` |

A card carries its edge in a ring shadow, which is why cards separate on `#f6f7f9` without a
visible line. Some draw real 1px borders instead: the project-folder table box, Workshop inner
cards and metric tiles, and the Ontology Manager's Discover navigation panel.

## Controls

**Buttons** are 30px tall, padding 4px 8px, radius 4px, 14px 400, with a 16px icon (7px from
the label is measured on menu items; on buttons it is Blueprint's default, not read). The
variant is the whole story:

| Variant | Fill | Edge | Text | Seen as |
| --- | --- | --- | --- | --- |
| default | `#f7f8f9` | `inset 0 0 0 1px rgba(69,78,91,.325), 0 1px 2px rgba(17,20,24,.1)` | `#1c2127` | "All Ontologies", "Recent installations", "Relevancy" |
| primary | `#2d72d2` | the same ring | `#fff` | "Save", "Start speedrun", the round search submit |
| success | `#238551` | the same ring | `#fff` | "+ New ▾", "+ New analysis", "Create new" |
| minimal | none | none; hover `rgba(143,153,168,.15)` | `#1c2127` | toolbar and header actions |
| minimal primary | none | none | `#215db0` | "Apply", "+ Group by", "Show more properties" |
| outlined | none | 1px `rgba(95,107,124,.25)` | `#1c2127` | "Analyze data", "Propose" |
| outlined primary | none | 1px `rgba(33,93,176,.6)` | `#215db0` | "SQL console", "Deploy", "Open in", "+ Add color" |
| split | as above | halves radius `4 0 0 4` and `0 4 4 0` | — | "Build ▾", "Edit output settings ⋯" |

Small buttons are 24px with padding 0 8px; large ones 40px (Blueprint's size, not measured).
The height is a minimum: ours has
buttons that wrap to two lines on purpose, and they must keep doing so.

**Inputs** are 30px, radius 4px, padding 0 8px (0 8px 0 30px behind a search icon), white, with
`inset 0 0 0 1px rgba(17,20,24,.2), inset 0 1px 1px rgba(17,20,24,.3)`. On dark ground: fill
`rgba(17,20,24,.3)`, ring `inset 0 0 0 1px rgba(255,255,255,.2), inset 0 -1px 1px rgba(255,255,255,.3)`.
A read-only launcher input (Ontology Manager's "Search resources…") is 350 × 30 on `#f6f7f9`
with a `#d3d8de` ring and a "Ctrl + K" hint at the right.

**Search pills** come in three sizes: the home enterprise search 1200 × 40, radius 20, 16px
text, padding 0 15px, "ctrl + J" hint; Files 36px, radius 18, 14px; Object Explorer a 700 × 42
floating card, radius 30, 1px `rgba(17,20,24,.2)` border and `0 2px 6px rgba(17,20,24,.2)`,
with a "Filter by…" select on the left and a round 32px primary submit on the right.

**Checkboxes** are 16px, radius 4, ring `inset 0 0 0 1px #738091`; 13px with a `#8f99a8` ring on
dark ground. **Numeric inputs** stack two 16px step buttons (radius `4 4 0 0` / `0 0 4 4`).

**Tabs** come in four kinds, and a screen picks by where they sit:

| Kind | Size | Selected | Where |
| --- | --- | --- | --- |
| underline | 14px 400, 20px apart, bar 40px (50px inside a 50px header) | text `#215db0`, 3px indicator | dataset Preview/History/…, PB Graph/Proposals/History, OE Explore/Results (16px) |
| tint | 35px bar | `rgba(45,114,210,.1)` fill, `#215db0` | PB bottom panel |
| pill | 40px, padding 0 10px, radius 4, icon + label | `rgba(45,114,210,.1)`, `#215db0` | Files: All files / Shared with you / Data Catalog / Trash |
| vertical | 240 × 40, 16px/40px 400, 16px icon | `rgba(45,114,210,.2)`, `#215db0` | project navigation |

Tab text is 400; only the colour changes.

**Segmented controls** are 30px. Light: the selected option is white with the default button
ring, others transparent in `#5f6b7c` (OE "Recents | Favorites | Your object sets"). Equal-width
variant: three buttons with the selected one on `rgba(56,62,71,.16)` (dataset "About | Columns |
Schedules"). Dark: the selected option is `#404854` (walkthrough "Guide | Overview | Files").

**Pill toggles** are interactive round tags: 30px, radius 30, padding 6px 10px, 14px. Unselected
on `rgba(143,153,168,.15)`; selected on `rgba(45,114,210,.3)` with `#184a90` 600 (OE, Contour),
or `rgba(45,114,210,.1)` with `#215db0` on home.

**Tags** are 20px, radius 4, padding 2px 6px, 12px. Minimal on `rgba(143,153,168,.15)` (counts);
intent tags on a 10% tint in the hover step with an icon ("Example" `#935610` and the dataset
build-status tag `#1c6e42` measured; "Indexed" and "Normal" follow the rule, colours not read);
round tags render as full pills (radius 30 on org badges; the Workshop count tag is radius 50px,
padding 2px 7px; the org badge's padding was not read); "New" on `rgba(122,225,216,.3)` in `#004d46` 10px 600.

## Overlays

| Overlay | Spec |
| --- | --- |
| menu | popover radius 4, shadow-overlay, no arrow, white, padding 4px, 8px from its trigger. Item 30px (52px with a description line), padding 4px 8px, radius 4, 14px/22px; leading icon 16px `#5f6b7c`; trailing caret or a muted hint; hover `rgba(143,153,168,.15)`; divider 1px `rgba(17,20,24,.15)` with 4px margins; submenus open to the side with room |
| tooltip | `#404854`, text `#f6f7f9` 14px/18px, padding 8px 12px, radius 4, shadow-overlay, no arrow |
| popover with arrow | Notifications: 480 wide, entries padding 16px in a 48px icon gutter, actor + verb + linked subject, quoted preview in muted text, a 24px primary action, a 12px muted timestamp, "View all notifications →" footer |
| light dialog | backdrop `rgba(17,20,24,.7)`; white, radius 4, shadow-overlay, centred vertically (the 690 × 700 dialog's top falls at 22% of a 1249px viewport). The resource dialog is 690 × 700: a 135px nav of minimal buttons (selected `rgba(45,114,210,.3)`, `#184a90`) beside a 555px pane with an eyebrow, the resource name, a close button, section rows and a NonIdealState |
| Quicksearch | dark even on a light page: 1200 wide, `#252a31`, radius 8, its own ring-and-drop shadow. A 45px 16px input, filter chips (Apps, Objects, Datasets, Files, More ▾), "RECENT SEARCHES"; as you type, "All search results" then a "JUMP TO" group of rows (icon, name 600, path 12px muted, a recently-viewed icon and a type chip), and a 39px `#1c2127` footer of key hints |
| Applications launcher | a dark modal, 1300 × 750 on `#1c2127`: 40px search + "Filters"; a 250px category column (All apps 62, nine categories with counts, promoted apps); a list of rows (24px icon tile, name 600, description 12px muted); a details pane with "Open ↗", a green "Create new", "Documentation" and a favorites-and-recents box |

## The shell

| Region | Spec |
| --- | --- |
| sidebar | **230px**, `#252a31`, 1px right border `rgba(17,20,24,.4)`. Header 50px (logo, collapse ⇤). Items 32px, padding 0 17px, 16px icon `#abb3bf` then 12px to a 14px label. Hover `#383e47`; active `#1c2127` with label 600 and icon `#f6f7f9`. Hints right-aligned 14px `#abb3bf` ("ctrl + J"). Groups: Home, Search, Notifications, What's New · 21px gap · Recent, Files, Ontology, Applications · then `APPLICATIONS` (favourites, and the current app at 36px) · bottom group AIP Assist, Support, Account with a top rule. Unread: a 10px `#fbb360` dot |
| app header | **50px** white, rule `0 1px 0 rgba(17,20,24,.15)` (Files, projects) or `#dce0e5` (OM). OM starts with a 50 × 50 app tile flush left, a project with a 40px "Home" button; app name 16px 600, and per app: centred top-level tabs (Files), a read-only resource search (OM), branch picker and "+ New ▾" at the right. Object Explorer has no app header: its top is the 40px document-tab strip |
| resource header | **51px** (50 + 1px `#d3d8de`): app tile, then a breadcrumb (parent muted, current 14px 600, star) over a menu bar of 20px caret buttons ("File ▾ Theme ▾ Help ▾" on a dataset; "File ▾ Settings ▾ Help ▾" in Pipeline Builder, whose header is 50px), org badge, branch "⎇ master ▾"; right: theme, build-status group, Share, details |
| document tabs | Object Explorer: 40px strip on `#edeff2`; tabs 180 wide, white when active, icon + title + close; "+" opens another |
| resource nav | Ontology Manager: 300px white; items 35px, padding 10px, radius 4; counts as minimal tags; groups separated by `rgba(220,224,229,.5)` |
| project nav | 260px of vertical tabs (see Tabs), with dividers and ↗ on pages that open elsewhere |
| facet panel | Files: 250px white; header 55px ("Filters", count tag, collapse); sections with a 12px label and chevron; a 24px search; option rows 30px: checkbox, type icon, label, count |
| right rail | Pipeline Builder: **51px** white, 1px `#dce0e5` on its left, 40 × 40 buttons that switch the 335px panel between tool views (outputs, search, changes, deploy, build settings, schedules, file tree, evaluation suites, unit tests, sources). Files and projects: a 40px rail of 30px buttons (Overview, Access, Activity, Resource queues, Branch protection) |
| walkthrough panel | a docked, resizable, dark 450px panel between the sidebar and the app: eyebrow in `#8abbff`, title 14px 600, a segmented "Guide | Overview | Files", body 14px/21px, numbered steps, "Start" |

## Page patterns

**Home.** A white main area over a faint isometric illustration; a centred 1200px column:
"Welcome back, *name*" (36px 400); the 1200 × 40 enterprise search; a hero card (radius 20, a
gradient ring, padding 30) of three columns — Get started, Install examples, Join Developer Community —
each with a 16px 600 title, a line of text and an action (Get started has two: "Start
speedrun" and "View training tracks"); "Recent" with Files / Projects pill
toggles over a table card (header 40px, rows 44px, icon + name + relative time); a dark AI
banner of prompt pills; a 380px right column of `#f6f7f9` cards: recommended applications as a
4 × 2 grid of 70px icon tiles with tooltips, "Get in touch", a newsletter.

**App landing.** Contour, Workshop, AIP Logic and Data Connection open on the same page: a 51px
header whose app tile is tinted in the app's hue (fill at 10%, an inset line at 25%), the app
name 16px 600 `#404854`, a green "+ New *thing*" and Help; a 106px white hero with the app name
at 22px 600, one paragraph, and faint line art of the app; a 1000px column with Recents /
Favorites pills over a recents table (30px white header) that shows a NonIdealState when empty,
and reference examples as 270 × 270 image cards.

**Files.** Pill tabs in the header; a breadcrumb "All files › All spaces ▾" (16px 600) and a
green "+ New ▾"; three quick-filter cards (Portfolios, Projects, Promoted items, each with
"Apply"); a pill search; the facet panel beside a table whose rows are 57px with the name over
its full path; a right rail. Dates are absolute ("Thu, Nov 6, 2025, 4:41 PM").

**Project folder.** A breadcrumb header with star, org badge, "Actions ▾" and "+ New ▾"; the
project navigation (Cover page, Files, Autosaved, References, Trash, Project usage ↗, Access
graph ↗); a "Pinned" strip; "Files" at 18px 600 over a bordered table (rows 40px, hover
`#edeff2`, name in `#215db0`). The title and description are click-to-edit.

**Resource app (dataset).** The resource header; underline tabs Preview / History / Details /
Health / Compare / Time Travel with the resource's actions at their right (outlined primary "SQL
console", split "Analyze data ▾", "Explore pipeline ▾", "All actions ▾", "Build ▾"); a resizable
513px About panel (a segmented About / Columns / Schedules; description; linked object type;
key/value rows with RID copy; Tags, Data Health, Inputs with lineage, Custom metadata as
sections with right-aligned actions); a grid whose headers carry a type glyph and type name,
cells in Source Code Pro; a collapsed 42px "SQL console" drawer.

**Object Explorer home.** The document tab strip; "Object Explorer search" (16px 600, centred)
over the floating pill search; "Shortcuts" with a segmented Recents / Favorites / Your object
sets and shortcut cards; the object type catalog (filter with an "N of M" tag, sort, segmented
All / Type group / Application) as a table with a 450px detail pane: tinted type icon and name,
status tag, compact count with a 26px micro-bar, users and apps, description; the object set
catalog with pill filters and a NonIdealState.

**Exploration.** A new document tab; an announcement banner; a header with the type and a
1300px "Search properties to add a chart or filter…"; a toolbar (undo, redo, "Custom layout ▾",
"Compare ▾", Explore | Results, a result-count tag, "Actions ▾", "Open in ▾"); chart cards in
two 492px columns (header 49px; a `#f6f7f9` option row with "+ Group by"; a histogram or a
listogram whose rows are menu items that filter; range inputs), a 280px Results card and a
Linked objects card.

**Object View.** A 60px header (36px type tile, title, star, the type's breadcrumb; a pager
"‹ 1 of 1.7M ›", refresh, comments, search, "More ▾"); a 1060px column of section cards:
**Prominent**, a five-column grid of 211 × 108 cells separated by 1px gaps (value 22px 600 over
a 14px muted label, copy on hover); **Properties**, two columns of 28px key/value rows ("No
value" italic muted, copy on every value, "Show more properties ▾"); **Linked objects**, link
types with counts on the left and a searchable table on the right.

**Ontology Manager object type.** The OM header; a 300px nav of the type's pages (Overview,
Properties, Security, Datasources, Observability, Capabilities, Object views, Interfaces,
Materializations, Automations, Usage, History) with a "Last edited … by" footer; an info banner
(installed by Marketplace); a 1040px column: a title row (40px tinted tile, 18px 600 name, star,
copy, "Actions ▾", "Open in ▾"), a metadata card (click-to-edit values with pencil and copy, a
300px status column of tags), Properties (type glyphs, key badges) beside Action types (a
NonIdealState), a link-type graph with a ghost "⊕ Create new link type" node, Interfaces; a
42px bottom bar "SQL console | Preview of … | Object mode".

## Tables

| Variant | Header | Rows | Rules | Hover |
| --- | --- | --- | --- | --- |
| default (Files, OE catalog, Contour) | **30px**, `#f6f7f9` (white in Contour), 12px 400 uppercase `#5f6b7c`, rule `0 1px rgba(17,20,24,.15)` | 57px two-line (Files); 42px (OE catalog); 40px as in the project folder | `0 -1px rgba(17,20,24,.15)` on Files; none visible on the OE catalog; no cell borders | not read on these three; the project folder's `#edeff2`, name in `#215db0`, is the nearest measure |
| home Recent | 40px, 20px side padding | 44px | as above | `rgba(45,114,210,.1)`, text `#2d72d2` |
| project folder | 30px, 12px **600** uppercase | 40px | inset `0 -1px rgba(17,20,24,.1)`; the box has a 1px border | `#edeff2` |
| dark (Workshop) | 50px `#383e47`, 12px/13.2px 600 `#abb3bf`, not uppercase, wraps | ~40px, `#2f343c`, ledger striping | 1px `rgba(17,20,24,.4)` | a selection region outlined in `rgba(138,187,255,.75)` |

Cells are padded 0 11px; the first cell starts 20px in. Sortable headers carry a 20px double
caret. Rows open a context menu on right-click.

## The graph editor (Pipeline Builder)

| Part | Spec |
| --- | --- |
| node | **200 × 60** graph units (a two-input join is 200 × 110), white, rx 2, 1px `#c5cbd3` |
| header band | **30px**: a 30 × 30 icon cell on `#edeff2` holding a 20px icon, then a 170px band in the node's **colour group**, title 14px 600 white (dark on a white band); a 1px line under it |
| body | "18 columns" 14px 400 `#5f6b7c`; a join lists its inputs in 12px ("Left dataset", "Right dataset"), each with its own input port |
| ports | 14 × 14, centred on the left and right edges at the band's lower edge |
| edges | `#abb3bf`, 2px, smooth curves, no midpoint controls |
| canvas | `#edeff2`; zoom in / out / fit as three 30px buttons stacked at the bottom-left |
| colour groups | **Bands take the legend's user-defined groups, not the node type.** Seen: Raw Input `#8f99a8`, Geospatial Join `#238551`, Clean join output `#d1980b`, Output `#147eb3`; a node in no group has a white band |
| legend | a 310px card at the top-right on `#f6f7f9`, radius 3, ring shadow: a 14px swatch (radius 2), the group's name and count, an eye toggle per group, "+ Add color" |
| header | resource header with "File ▾ Settings ▾ Help ▾", a "Batch" tag, tabs Graph / Proposals / History, undo, redo, branch, Saved, Propose, Deploy (outlined primary, split), checks, Actions, Share |
| toolbar | icon buttons in groups, each group labelled underneath in 12px: Tools, Select, Remove, Layout, Text, Add data, Reusables, Transform, AIP, Edit |
| side panel | 335px; header **44px**, padding 6px 8px, 1px `#dce0e5` below, title 14px 600, gear and "+ Add"; a search; output cards with a green "✓ 16/16 columns mapped"; "Output settings" at the bottom |
| rail | 51px beside it (see The shell) |
| bottom panel | tint tabs Selection preview / Suggestions / Pipeline warnings in a 35px bar; empty state a 48px icon and one muted line |

## Charts

Histogram bars are `#2d72d2` with their values inside in 12px white ("132k"), light gridlines,
axes in 12px. Listogram rows are 30px: the value, a right-aligned count, and a horizontal
`#2d72d2` bar (radius 2) scaled to its share; "No value" in italic; "Show more ▾". A catalog count
has a 26px micro-bar in `#5f6b7c` on `#edeff2`. Clicking a bar or a row filters.

## Dashboards (Workshop runtime, dark)

| Element | Spec |
| --- | --- |
| module header | 44px in the author's colour (the COP uses indigo-3 `#7961db`), padding 10px 16px, title 14px 600 white |
| page | `#2f343c`; body sections raised `#383e47`; the table section sunken `#1c2127`; inner cards `#2f343c`, radius 3, 1px `rgba(17,20,24,.4)` |
| metric row | five tiles joined edge to edge (outer radius 4px), `#252a31`, 1px `rgba(17,20,24,.4)`: label 12px **400** `#abb3bf`, not uppercase; value **24px/31px 400** coloured by meaning: `#2d72d2` totals, `#c87619` cancellations, `#d1980b` diversions |
| tab list | 44px rows with an icon, label and round count tag; selected row `#2d72d2` |
| filter list | section labels 12px 600 uppercase `#abb3bf`; value rows 30px: 13px checkbox, name, 14px count, a proportional `#2d72d2` bar; "only" on hover in `#8abbff`; a date histogram with start and end inputs; "Add filter" pinned at the bottom |
| map | full bleed, dark basemap, scale chip top-left, legend chips bottom-right |
| table | the dark table variant |

## Empty, loading and banners

**Empty states** are Blueprint's NonIdealState: a 48px muted icon, a title 18px/20px 600 in
`#5f6b7c`, one 14px muted line, centred in the card or table body they replace; in a dialog, a
40px circled icon and a 400px-wide line. **Loading** showed grey placeholder bars in the
exploration's chart cards before their data arrived: seen in a screenshot, not measured. **Banners:** an announcement is 39px on
`rgba(253,204,0,.1)` with a `rgba(253,204,0,.4)` rule, 14px 600 gold text and one action at the
right; an info banner is 46px on `#f6f7f9` with a `#d3d8de` rule. A result count is a radius-4 tag
(padding 4px 8px) on `rgba(76,144,240,.1)` with a `rgba(76,144,240,.4)` border in `#4c90f0`.

## What changed since the morning

| Morning | Afternoon | Why it matters |
| --- | --- | --- |
| `--palette-violet: #7961db` | indigo-3; violet-3 is `#9d3f9d`; all 87 steps shipped | the only author colour in the COP was misnamed |
| titles are 14px 600, "not big" | 14px cards and panels, 16px app names and home sections, 18px page headings, 22px heroes | a 50px header with a 16px app name, not 14px |
| table header 40px, 12px 600 | 30px, 12px **400** (600 and 40px are the exceptions) | denser tables |
| selected nav `rgba(138,187,255,.1)` | that is the OM nav only; selection is a family of five | one token could not serve all |
| tab 14px 600, 2px underline, 35px bar | 14px 400, 3px indicator, 40px bar; plus tint, pill and vertical tabs | four tab kinds |
| default button `#f6f7f9`, border `rgba(17,20,24,.2)` | `#f7f8f9`, `inset 0 0 0 1px rgba(69,78,91,.325), 0 1px 2px rgba(17,20,24,.1)` | the button's edge |
| tag radius 3px | 4px; round tags 30px | — |
| graph node 194 × 58, band 18, title 12px, ports 8px | 200 × 60, band 30 with an icon cell, title 14px 600, ports 14px | read on screen at another zoom (about 0.97, by ratio) |
| bands by category (join `#c87619`) | bands by user colour group (seen `#d1980b`), ungrouped white | colour groups are a function, not a paint |
| KPI 20px in `#4c90f0` / `#ec9a3c`, label 600 uppercase | 24px 400 in step-3 colours; label 12px 400 mixed case; tile `#252a31` | — |
| hairline `#dce0e5` everywhere | ink `rgba(17,20,24,.15)` mostly; four solid grays by app | — |
| faces 400 and 600 | 400, 400 italic, 600 (+700 on charts, + Source Code Pro on grids) | three `@font-face` rules, not two |
| ours: one root variable, six radii, a 6,300-line sheet | zero custom properties (and seven undefined ones in use), eleven radii, 6,756 lines | the undefined variables are a live bug |
| ours: node coloured whole, 8px radius | white 172 × ≥58, 3px radius, 1px `#9fb0bd`, an 8px coloured top border | ours is already a band and a body |

Kept after being challenged: the 50px app header, the 51px PB rail, the 335px side panel, the
44px side-panel header (re-measured), the 40px default row, and the PB title bar at 50px.

## From ours to this

| Ours today | Target | Token |
| --- | --- | --- |
| Inter declared, never loaded; renders Segoe UI | Source Sans 3 400, 400 italic, 600, bundled | `--font-family` |
| no body size: text and controls at the browser's 16px | 14px / 18px body | `--font-size-medium`, `--line-height-default` |
| 12px ×64 and 11px ×38 for secondary text | 12px for labels, hints, counts; nothing at 11px | `--font-size-small` |
| h1 25px on the 15 `Page` screens (20px in Visual Builder), h2 15px in panels | 16px app name in a header, 14px 600 card titles, 18px page headings in content; titles stay heading elements | `--font-title-*` |
| weights 700 ×27, 800 ×10, 650 ×6, beside 400 ×2 and 600 ×1 | 400 and 600 | `--font-weight-*` |
| 308 distinct hex colours, no palette | one palette; new colours refused | `--palette-*`, intents, surfaces |
| 7 undefined variables used 39 times | defined or aliased once | GOAL_LOOK U1 (the count) and U3 (the alias block) |
| radii 0, 2–9px, 50%, 999px | 4px default; named 2/3/5/8/18/20/30px and 50% | `--radius-*` |
| button 37px, padding 8px 12px, radius 7, 1px `#c6d0d7`, white; no shared primary style (21 `className="primary"` with no rule; a one-off `.primary-action` in `#176b8f` on 5 buttons) | 30px min, 4px 8px, radius 4, `#f7f8f9` + ring; primary, success, minimal, outlined variants | `--control-*`, `--button-*`, `--shadow-button` |
| inputs with browser chrome at 16px | 30px, radius 4, inset ring | `--input-*`, `--shadow-input` |
| sidebar 286px `#14202a`, 23 two-line text items, no icons | 230px `#252a31`, 32px icon rows in groups, section labels, favourites | `--shell-sidebar-*` |
| no shared app header: a sticky 6-step flow strip and a backend bar on every screen, then `Page`'s 25px h1, a screen's own 42/48px topbar, or Visual Builder's header of 84px or more | one 50px app header per app | `--shell-header-*` |
| panels: 1px `#d7dedf`, radius 8, padding 14, 15px h2 inside | shadow-0 cards, radius 4; section cards with a 50px header rule | `--shadow-0`, `--section-header-*` |
| pane header ~28px `#f3f6f7`, 12px title | 44px, 14px 600, `#dce0e5` rule | `--panel-header-*` |
| table 13px, header 700 `#64717a` on `#f8fafb`, rows ~33px | header 30px 12px 400 uppercase, rows 40px, ink rules, row hover | `--table-*` |
| StatusBadge: green / amber / red pills by substring, 999px radius | tags 20px radius 4 by intent, minimal for counts | `--tag-*` |
| tooltips: the native `title` attribute (316 uses) | a dark tooltip | `--tooltip-*` |
| no menu, popover or dialog primitive | menu, popover and dialog on the overlay shadow and backdrop | `--menu-*`, `--shadow-overlay`, `--overlay-backdrop` |
| empty state: a dashed box (`.empty`) or a bordered card; no icon, not centred | NonIdealState, centred | `--font-title-empty` |
| loading: static text | placeholder bars | — |
| pipeline node white 172 × ≥58, radius 3, 1px `#9fb0bd`, 8px category top border; 16px ports; edges `#9aa8b5` with a midpoint circle and a "+" | 200 × 60, band 30 with icon cell, colour groups, 14px ports, plain `#abb3bf` edges | `--graph-*` |
| canvas `#edf1f4` | `#edeff2` | `--graph-canvas` |
| two fixed dark surfaces (the sidebar `#14202a` and the Ontology Manager's walkthrough panel `#17232d`); `pre` dark | a dark scope for the sidebar, overlays, walkthrough, Workshop runtime | `--dark-*` |
| one transition in the sheet | 0.1s `cubic-bezier(.4,1,.75,.9)` on state changes | `--transition-*` |
| z-index 1 to 1100 with no scale | 0–40 scale for the app; overlays above | `--z-*` |

## What was not measured

- The colour of a **selected light table row**: there was no read-only way to select one. Hover
  is measured; selection is not.
- A **switch** (toggle): none was on screen.
- The **PB bottom panel's open height**: it was collapsed to its tabs on every visit.
- The **port ring colour**: white fill is confirmed; the ring was not read.
- The **tab indicator's colour**, a dark button's ring, and an input's padding: taken from
  Blueprint's defaults and marked as such in the token file.
- Dark table **cell widths**: heights (≈40px) were read; widths follow content.
- Anything behind a click that changes data: no dataset was built, no action run, no form
  submitted, no search stored.

## How to re-read a value

Open the surface in a signed-in browser, then in the console:

```js
getComputedStyle(document.elementFromPoint(x, y))
```

with `x, y` in CSS pixels. A screenshot of a 2560-pixel-wide viewport at a 1.5 ratio comes back
1568 wide, so multiply screenshot coordinates by 2560 / 1568. The token table is every
`:root` rule's custom properties: iterate `document.styleSheets` and read the properties that
start `--bp` (205 `--bp-*` and one `--bp6-*`). For the graph, read the node's `<rect>` `width` and `height` attributes, not its
bounding box, which changes with zoom.
