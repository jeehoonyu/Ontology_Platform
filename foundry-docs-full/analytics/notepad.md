<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ANALYTICS</b><br>
<span style="font-size:22px"><b>Notepad &amp; Reports</b></span><br>
<span style="color:#ABB3BF">An object-aware collaborative rich-text editor for embedding live analytics and generating structured reports.</span>
</td></tr></table>

## What it is

Notepad is Foundry's primary reporting tool — a document editor that lets analysts weave formatted narrative text, embedded visualizations from Contour, Quiver, and Code Workbook, and live ontology-object properties into a single cohesive document. Unlike interactive dashboards (Quiver Dashboards, Workshop), Notepad is designed for point-in-time reporting: documents can be shared in-platform, exported as PDFs, or generated on-demand from parameterized templates. It supersedes the legacy **Reports** application (now sunset).

## How it works

Notepad documents live as Foundry resources inside a project or personal space, governed by the standard Foundry permission and marking system.

**Core resource types:**

- **Document** — the primary artifact. A document is a rich-text canvas stored in Foundry. It holds a mix of prose blocks, native widgets (tables, images, LaTeX), and embedded application widgets. Every document has a unique Foundry resource RID.
- **Template** — a reusable document blueprint with declared input parameters. When a template is instantiated, Notepad resolves each parameter (typically an object or object set from the ontology) and renders a new document or PDF.
- **Widget** — a typed content block inside a document. Widgets are either native (date, page break, value embed, LaTeX) or application-sourced (Contour chart, Quiver dashboard, object property card, map).

**End-to-end mechanics:**

1. **Authoring.** A user opens Notepad and creates a new document. The editor surface is a block-based canvas. Pressing `/` or clicking `+ Widget` opens the insertion menu listing all available widget types.

2. **Widget insertion.** When an application widget is added (e.g., a Contour chart), the user provides a path and board from an existing Contour analysis. The widget stores a reference (RID + path + board) — not a copy of the data. For object property widgets, the user selects an ontology object type and a specific property; the widget fetches that property value at read time.

3. **Automatic resource linking.** Every object, object set, and Foundry resource referenced inside a document is automatically registered as a link on the document resource. This powers Workshop's **Linked Documents** feature, which surfaces "which Notepad documents reference this object?"

4. **Data refresh.** When a user opens a document, Notepad re-fetches live data for all widgets. Contour board data is updated at document-open time. Object property widgets pull the current ontology value. This makes documents "live" by default.

5. **Content freezing (Lock data).** A user can take a point-in-time snapshot of any widget — capturing its current visualization and data. Locked widgets are frozen; they no longer re-query. When locking, Foundry mandates that all upstream data resources carry appropriate security markings, enforcing envelope security.

6. **Template instantiation.** A template author defines one or more input parameters (e.g., `aircraft_id: Aircraft`). When generating a document from a template, the caller supplies parameter values. Notepad resolves every widget that references a template input — for example, a Contour chart widget can map its parameter overrides to the template's `aircraft_id` input. Function-on-Objects sections can be configured with **batched functions**, executing once per object set (rather than once per object), significantly reducing generation time for large inputs.

7. **Export.** The document is rendered to PDF through Foundry's export pipeline. Authors control embed appearance (live vs. frozen), pagination via explicit page-break widgets, and which content blocks to include.

## User interface

**Overall layout:** The Notepad editor fills the main content area with a clean white canvas framed by the <span style="color:#ABB3BF">Foundry dark shell</span> (`#111418`). A left sidebar or breadcrumb shows the document's location in the project tree. A right sidebar — the **Widget Properties** panel — appears when a widget is selected.

**Key interface zones:**

<table style="border-collapse:collapse;background:#1C2127;color:#fff;width:100%;font-size:13px">
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px;color:#8ABBFF"><b>Zone</b></td>
  <td style="padding:8px 12px;color:#8ABBFF"><b>Description</b></td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#2D72D2"><b>Toolbar</b></span></td>
  <td style="padding:8px 12px">Standard text-formatting controls (bold, italic, heading levels, bullet lists) plus document-level actions: Share, Export PDF, Lock data.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#2D72D2"><b>Block canvas</b></span></td>
  <td style="padding:8px 12px">The editor body. Each line is a block. Typing <code>/</code> anywhere invokes the widget insertion menu. Blocks can be dragged to reorder.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#2D72D2"><b>Widget insertion menu</b></span></td>
  <td style="padding:8px 12px">A searchable popup listing all widget categories: integrations (Contour, Quiver, Code Workbook, Vertex, Object Explorer, maps) and native blocks (image, table, LaTeX, page break, date, value embed).</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#2D72D2"><b>Widget Properties panel</b></span></td>
  <td style="padding:8px 12px">Right sidebar activated on widget selection. Shows widget-specific config: for a Contour chart, Path and Board selectors plus parameter overrides. For an object property widget, object selector, property selector, icon toggle, hover-popover toggle, conditional formatting toggle.</td>
</tr>
<tr>
  <td style="padding:8px 12px"><span style="color:#2D72D2"><b>Template inputs bar</b></span></td>
  <td style="padding:8px 12px">Visible when editing a template. Declares named input parameters and their types. Each widget can then bind its data source to a template input.</td>
</tr>
</table>

**Status and state chips used in the UI:**

<span style="color:#238551"><b>● live</b></span> — widget is fetching current data
&nbsp;·&nbsp;
<span style="color:#C87619"><b>● locked / frozen</b></span> — widget shows a point-in-time snapshot
&nbsp;·&nbsp;
<span style="color:#CD4246"><b>● error</b></span> — widget failed to load (e.g., missing markings or deleted source)
&nbsp;·&nbsp;
<span style="color:#2D72D2"><b>● primary action</b></span> — Export PDF, Generate from Template

**Cross-app embedding shortcut:** In Contour, Quiver, or Code Workbook, a `Copy for Notepad` button appears on any embeddable visualization. Clicking it places a pre-configured widget reference on the clipboard; pasting into a Notepad document inserts the widget with path and board already set.

## Worked example

**Scenario:** A logistics analyst needs a weekly carrier performance report for a specific airline code.

1. The analyst opens Foundry, navigates to their project, and creates a new **Notepad template** called `Carrier Weekly Report`.
2. They declare a template input: `carrier_code` of type `string`.
3. In the document body they write a prose heading, then press `/` and insert a **Contour chart** widget. In Widget Properties they select the `Carrier Analysis` Contour analysis, choose the `On-Time Performance` board, and under Parameters map `carrier_code` → the template input `carrier_code`.
4. They add an **object property** widget for the `Carrier` object type, binding it to a carrier looked up by `carrier_code`, and enable the hover-popover so readers can click through to Object Explorer.
5. They insert a native **table** block with manually curated summary notes and a **page break** before the appendix section.
6. Every Monday, an automated process calls the template with `carrier_code = "OO"`. Notepad instantiates the template, resolves the Contour parameters, fetches live board data, and renders a PDF exported to the shared folder — ready for stakeholders without requiring any Foundry access.

## Documentation map

The following sub-pages exist beneath the Notepad section of the Foundry docs:

- **Overview** — capabilities, limitations, and comparison with dashboards
- **Get started** — step-by-step introduction for new users
- **AIP features** — AI-assisted authoring capabilities
- **Envelope security** — how markings are enforced when locking data
- **Markdown features** — supported markdown syntax in text blocks
- **Documents** — creating, editing, sharing, and versioning documents
- **Templates** — defining inputs, binding widgets, and generating documents
- **Workshop integration** — embedding Notepad documents inside Workshop apps via Linked Documents
- **Widgets — embed widgets** — overview of all widget categories and insertion methods
- **Widgets — anchor links** — linking to named sections within a document
- **Widgets — resource links** — linking to other Foundry resources
- **Widgets — images** — embedding static images
- **Widgets — tables** — native table blocks
- **Widgets — object properties** — displaying ontology object properties inline
- **Widgets — Contour chart** — embedding Contour analysis boards with parameter overrides
- **Widgets — maps** — embedding geographic visualizations

## Official documentation

- [Notepad — Overview](https://www.palantir.com/docs/foundry/notepad/overview)
- [Analytics — Reporting](https://www.palantir.com/docs/foundry/analytics/reporting)
- [Analytics — Overview](https://www.palantir.com/docs/foundry/analytics/overview)
- [Notepad — Embed widgets](https://www.palantir.com/docs/foundry/notepad/embed-widgets)
- [Notepad — Widgets: Object property](https://www.palantir.com/docs/foundry/notepad/widgets-object-property)
- [Notepad — Widgets: Contour chart](https://www.palantir.com/docs/foundry/notepad/widgets-contour-chart)
- [Analytics — Types of analysis](https://www.palantir.com/docs/foundry/analytics/types-of-analysis)
- [Reports \[Sunset\] — Overview](https://www.palantir.com/docs/foundry/reports/overview)
