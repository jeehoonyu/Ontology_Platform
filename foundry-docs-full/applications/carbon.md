<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · APPLICATIONS</b><br>
<span style="font-size:22px"><b>Carbon</b></span><br>
<span style="color:#ABB3BF">A workspace builder that creates role-scoped, Ontology-aware platform experiences for operational users.</span>
</td></tr></table>

## What it is

Carbon is a Foundry application that lets administrators assemble **workspaces** — curated, permission-bounded environments composed of Foundry applications (called *modules*) wired together into guided workflows. It is designed for less-technical, operational users who need fast access to critical workflows without encountering the full complexity of the Foundry platform. A workspace presents a custom home page, a focused menu bar, and a sequenced set of tabs that pass Ontology objects between applications as the user moves through their work.

## How it works

Carbon's runtime is built around three interlocking concepts: **workspaces**, **modules**, and **navigation parameters**.

1. **Workspace as a resource.** A workspace is a Foundry resource (stored in a Project folder alongside the assets it references) that contains all configuration as YAML. The YAML declares the workspace name, description, theme override, menu bar contents, discoverable modules, external links, and home page layout. When saved, the configuration becomes the live workspace immediately; no build or pipeline is required.

2. **Home page entry point.** When a user opens a workspace, Foundry renders the configured home page. By default the home page contains a custom logo, an optional subtitle, an Ontology-aware search bar, and up to three columns of *featured item* widgets. Widgets display objects, object types, or saved explorations in either **List** or **Cards** view. Administrators can alternatively replace the entire home with any module (a Workshop app, a Quiver dashboard, etc.) using the *Replace Home with Compass Resource* option.

3. **Module types.** Every tab inside a Carbon workspace is backed by a module — a parameterized instance of a Foundry application. Supported module types are:
   - **Object View** — a single Ontology object displayed in its configured view
   - **Object Explorer** — a set of objects with filter/sort/action capabilities
   - **Workshop** — a low-code application driven by module interface variables
   - **Quiver** — an analytics dashboard that accepts objects or object sets
   - **Vertex** — a graph exploration of linked objects
   - **Slate** — a custom web application embedded as a Carbon tab
   - **Notepad** — read-only documentation
   - **Search** — keyword entry that seeds downstream modules

4. **Input/output parameter passing (the navigation framework).** Each module exposes a typed *input* (an object, object set, or search query) and a typed *output* (the currently-active selection inside that module). When the user triggers an "Open in" action from any application, Carbon intercepts the action, resolves the target module, passes the output of the current module as the input of the target, and opens it in a new tab — preserving the originating tab's state. There is no limit on chain length; the same module may appear multiple times in a session with different inputs.

5. **Discoverable modules list.** The builder registers which modules are eligible to appear in "Open in" menus through the Carbon config editor's **General** tab → **Discoverable Modules** list. Inside a workspace only that workspace's discoverable modules appear; outside a workspace (e.g., from standalone Ontology views) all discoverable modules across all promoted workspaces the user can access are surfaced.

6. **Workshop and Slate deep-integration.** Workshop modules receive objects via *external ID* variables — the builder assigns an external ID in the variable's Settings panel and Carbon populates it via URL parameters (`?param.variable.flight_id=1000`). Slate modules support two auto-typed variable names (`v_objectPassedFromCarbon`, `v_objectSetPassedFromCarbon`) that Carbon fills automatically; Slate link navigation is intercepted so that links to Foundry applications open as Carbon module tabs rather than full-page navigations.

7. **Permissions and promotion.** Workspace access is controlled by Foundry's standard resource permissions (the workspace and its referenced assets should share a folder for unified permission management). Promoted workspaces are registered at the organization level and appear in the Navigation Menu dropdown for all users who have access. Non-promoted workspaces are accessible via Projects or direct links only.

## User interface

### Editor layout

Carbon's editing interface opens when an administrator clicks **Edit** in the top-right of the menu bar (or navigates to `workspace/carbon/edit`).

<table style="border-collapse:collapse;width:100%;background:#1C2127;border:1px solid #383E47">
<tr style="background:#252A31">
  <th style="padding:8px 12px;color:#8ABBFF;text-align:left;border-bottom:1px solid #383E47">Area</th>
  <th style="padding:8px 12px;color:#8ABBFF;text-align:left;border-bottom:1px solid #383E47">What you see</th>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><b style="color:#fff">Left panel</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Tab list: <span style="color:#2D72D2"><b>General</b></span>, <span style="color:#2D72D2"><b>Home</b></span>, <span style="color:#2D72D2"><b>Modules</b></span>, plus a <i>Create workspace</i> button at the bottom.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><b style="color:#fff">General tab</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Name, description, theme override (light/dark), navigation control toggle, external links section with <i>Copy from Organization</i>, search bar filters, AIP Assist toggle, notifications toggle, and a <span style="color:#CD4246"><b>Danger Zone</b></span> delete action.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><b style="color:#fff">Home tab</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Logo uploader with max-width/height fields, subtitle text field, three featured-item column pickers (A/B/C). Each column has a widget type toggle: <span style="color:#2D72D2"><b>List</b></span> or <span style="color:#2D72D2"><b>Cards</b></span>, and a <i>Metadata &amp; Display</i> section for title/description. A <i>Replace Home with Compass Resource</i> option replaces the default home with any module.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><b style="color:#fff">Modules / Discoverable Modules</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">A Resource Selector dialog for adding Workshop apps, Quiver dashboards, Vertex, Slate, Object views, Searches, and Notepads to the workspace's navigation menu and discoverable module list.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF"><b style="color:#fff">YAML editor</b></td>
  <td style="padding:8px 12px;color:#ABB3BF">Raw YAML view for the entire workspace config — accessible for power users who prefer editing the configuration directly instead of via the GUI forms.</td>
</tr>
</table>

### Runtime (user-facing) layout

<table style="border-collapse:collapse;width:100%;background:#1C2127;border:1px solid #383E47">
<tr style="background:#252A31">
  <th style="padding:8px 12px;color:#8ABBFF;text-align:left;border-bottom:1px solid #383E47">Element</th>
  <th style="padding:8px 12px;color:#8ABBFF;text-align:left;border-bottom:1px solid #383E47">Description</th>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Menu bar</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Top bar with workspace name top-left, a Navigation Menu dropdown (promoted workspaces + external links), pinned module tabs, an optional <i>More modules</i> button, and utility buttons (Help, Notifications, AIP Assist, User profile, Logout).</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Home page</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Ontology-aware search bar, logo, subtitle, and two-column featured widget layout (prominent object types + saved explorations by default).</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Module tabs</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Each "Open in" navigation action opens a new tab showing the target application pre-filtered to the passed object(s). Tabs stack left-to-right; closing a tab returns focus to the previous one.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF"><span style="color:#2D72D2"><b>"Open in" context menu</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Appears inline in Object Views, Object Explorer, and Workshop/Slate when the module is configured as discoverable. Lists eligible target modules for the selected object or object set.</td>
</tr>
</table>

**Status indicator palette used across Carbon UI:**
<span style="color:#238551"><b>● Active / Success</b></span> · <span style="color:#C87619"><b>● Pending / Warning</b></span> · <span style="color:#CD4246"><b>● Error / Danger</b></span> · <span style="color:#2D72D2"><b>● Primary action / Link</b></span> · <span style="color:#ABB3BF">● Muted / Informational</span>

## Worked example

**Scenario: Airline operations analyst investigating a delayed flight.**

1. The analyst opens Foundry and selects the **"Airline Operations"** promoted workspace from the Applications Portal. The Carbon home page loads with a logo, a subtitle "Welcome, Ops Team", and three featured widgets: *Active Alerts*, *Flight Routes*, and *Saved Explorations*.

2. The analyst types "UA 4172" into the home page search bar. Carbon's Ontology-aware search surfaces a `Flight` object. The analyst clicks it; a new tab opens in an **Object View** module showing UA 4172's properties (departure time, gate, status, aircraft tail number).

3. From the Object View context menu the analyst selects **"Open in Quiver: Route Performance Dashboard"**. Carbon passes the UA 4172 object as the dashboard input parameter; the Quiver tab opens pre-filtered to UA 4172's route history.

4. The dashboard flags tail number `N441UA` as a recurring delay contributor. The analyst clicks **"Open in Workshop: Maintenance Triage"** from the Quiver "Open in" menu. Carbon passes the `Aircraft` object set; the Workshop module opens showing only the parts/service records for `N441UA`.

5. The analyst uses a Foundry Action button inside the Workshop module to file a maintenance request. All previous tabs remain intact; the analyst closes the Workshop tab and returns to the Quiver tab to continue analysis.

## Documentation map

- **Carbon · Overview** — entry point, purpose, and workspace concept
- **Carbon · Workspaces · Overview** — workspace structure, menu bar anatomy, promoted workspaces
- **Carbon · Workspaces · Create a workspace** — step-by-step creation and folder placement
- **Carbon · Modules · Overview** — module types and the parameterization model
- **Carbon · Modules · Configure navigation between modules** — input/output wiring, Workshop external IDs, Slate variables, state preservation
- **Carbon · Configuration reference · General configuration** — name, theme, navigation control, external links, AIP Assist, search filters, danger zone
- **Carbon · Configuration reference · Home configuration** — logo, subtitle, featured items, widget display modes, module-backed home
- **Carbon · Example workspaces** — Aviation workspace (flight route analyst) and Claim Portal (warranty claims triage) with YAML examples

## Official documentation

- [Carbon · Overview](https://www.palantir.com/docs/foundry/carbon/overview)
- [Carbon · Workspaces · Overview](https://www.palantir.com/docs/foundry/carbon/workspaces-overview)
- [Carbon · Workspaces · Create a workspace](https://www.palantir.com/docs/foundry/carbon/workspaces-create)
- [Carbon · Modules · Overview](https://www.palantir.com/docs/foundry/carbon/modules-overview)
- [Carbon · Modules · Configure navigation between modules](https://www.palantir.com/docs/foundry/carbon/modules-navigation)
- [Carbon · Configuration reference · General configuration](https://www.palantir.com/docs/foundry/carbon/configuration-general)
- [Carbon · Configuration reference · Home configuration](https://www.palantir.com/docs/foundry/carbon/configuration-home)
- [Carbon · Example workspaces](https://www.palantir.com/docs/foundry/carbon/example-workspaces)
