<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · AI PLATFORM</b><br>
<span style="font-size:22px"><b>Palantir MCP</b></span><br>
<span style="color:#ABB3BF">A Model Context Protocol server that lets AI IDEs and agents autonomously build, explore, and modify Foundry applications end-to-end.</span>
</td></tr></table>

## What it is

Palantir MCP is an implementation of the [Model Context Protocol](https://modelcontextprotocol.io) that exposes 70+ Foundry platform actions as MCP tools. It enables AI coding assistants (Claude Code, Cursor, Copilot, Cline, Continue, Windsurf) to navigate your ontology, run Python transforms, create ontology proposals, manage code repositories, and generate OSDK applications — all from within a developer's IDE. It is distinct from **Ontology MCP** (OMCP), which is designed for *consumers* of an ontology to read and write object data at runtime; Palantir MCP is designed for *builders* who are constructing the ontology and its surrounding application infrastructure.

## How it works

Palantir MCP runs as a local Node.js process (launched via `npx -y palantir-mcp`) that acts as an MCP server. The AI IDE connects to it over the standard MCP stdio or SSE transport and discovers the full tool catalog. Every tool call is authenticated with a user-scoped token against your Foundry instance hostname.

**End-to-end mechanics:**

1. **Enable in Control Panel.** A platform administrator opens the Foundry Control Panel, navigates to **Code Repositories**, and toggles Palantir MCP on. Access can be scoped to specific users or groups. This is disabled by default.

2. **Generate a user token.** The developer creates a personal token inside their Foundry instance (User Settings → Tokens) and sets it as the environment variable `FOUNDRY_TOKEN`.

3. **Configure the IDE.** The developer adds an MCP server entry pointing to:
   ```
   npx -y palantir-mcp --foundry-api-url https://<your-foundry-hostname>
   ```
   Each supported IDE (Claude Code, Cursor, Copilot in VS Code, Windsurf, etc.) uses an equivalent JSON config block referencing the same command and the `FOUNDRY_TOKEN` env var.

4. **Repository context injection.** When the agent opens a file, the `get_repository_context` tool detects the repository type (OSDK React app, Python transforms, TypeScript functions) and injects curated Foundry library documentation and relevant code-snippet examples. For repositories that fall outside these categories the tool searches Palantir's internal snippet index.

5. **Tool dispatch.** The AI agent calls tools by name. Each tool maps to a Foundry API endpoint:
   - **Ontology tools** (`search_foundry_ontology`, `view_foundry_object_type`, `create_or_update_foundry_object_type`, etc.) read or write ontology schema on a named **Global Branch** — never directly on `main` — so all changes are staged.
   - **Dataset tools** (`run_sql_query_on_foundry_dataset`, `create_and_write_to_foundry_dataset`, `get_dataset_stats`) execute against the Foundry SQL engine. The agent **cannot** overwrite existing datasets; it can only create new ones.
   - **Build tools** (`build_datasets`, `preview_transform`, `get_build_status`) submit pipeline jobs and poll for results, enabling the agent to iterate on Python transforms until they pass.
   - **Developer Console tools** (`generate_new_ontology_sdk_version`, `install_sdk_package`, `convert_to_osdk_react`) regenerate the OSDK after ontology changes, so the IDE's TypeScript/Python types update immediately.
   - **Documentation tools** (`load_foundry_documentation_page`, `search_foundry_documentation`, `get_python_transforms_documentation`, etc.) let the agent look up live Foundry docs without leaving the chat context.

6. **Proposal and human-approval gate.** Any ontology modification creates a **Global Proposal** rather than a direct commit. The developer reviews the diff in the Ontology Manager UI and merges or rejects it. All write tools are either non-destructive (additive only) or gated behind this approval step — no destructive writes are exposed at all.

7. **VS Code Workspace shortcut.** Inside Foundry-hosted VS Code workspaces, Palantir MCP is available automatically via the built-in AI development tools panel, with no manual token configuration required.

## User interface

There is no dedicated Palantir MCP UI within Foundry itself — the interaction surface lives in your AI IDE. However, several Foundry screens are touched during a typical MCP session:

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127">
  <th style="padding:8px 12px;color:#8ABBFF;border-bottom:1px solid #383E47;text-align:left">Surface</th>
  <th style="padding:8px 12px;color:#8ABBFF;border-bottom:1px solid #383E47;text-align:left">What you see / do</th>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Control Panel → Code Repositories</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47;color:#ABB3BF">Toggle to enable Palantir MCP; restrict to user/group allow-list.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>User Settings → Tokens</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47;color:#ABB3BF">Generate the personal token that authenticates all MCP tool calls.</td>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>IDE MCP config (mcp.json / .cursor/mcp.json)</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47;color:#ABB3BF">JSON block with <code>command</code>, <code>args</code>, and <code>env.FOUNDRY_TOKEN</code>. Identical structure across all supported IDEs.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>AI Chat / Agent panel (IDE)</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47;color:#ABB3BF">The primary interaction surface. Tool calls appear inline as collapsible steps; results stream back as text or code blocks.</td>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Foundry Ontology Manager</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47;color:#ABB3BF">Where the human reviews and merges Global Proposals created by the agent. Shows a diff of added/changed object types, link types, and action types.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Developer Console</b></span></td>
  <td style="padding:8px 12px;border-bottom:1px solid #383E47;color:#ABB3BF">After <code>generate_new_ontology_sdk_version</code> runs, updated OSDK package versions appear here ready for <code>npm install</code>.</td>
</tr>
</table>

**Status indicators used in IDE tool call output:**

<span style="color:#238551"><b>● success</b></span> — tool call completed, result available · <span style="color:#C87619"><b>● pending</b></span> — build or job still running · <span style="color:#CD4246"><b>● failed</b></span> — tool call errored, agent will retry · <span style="color:#2D72D2"><b>● awaiting approval</b></span> — Global Proposal created, human review required

## Worked example

**Scenario: Add a new `Supplier` object type and wire it into a React OSDK app.**

1. Developer opens Cursor with Palantir MCP configured and types: *"Create a Supplier object type with fields name, country, and tier, link it to the existing PurchaseOrder type, then regenerate my OSDK."*

2. The agent calls `get_repository_context` — detects an OSDK React repository and injects relevant OSDK TypeScript documentation.

3. `search_foundry_ontology` confirms `PurchaseOrder` exists and returns its RID and current properties.

4. `create_global_branch` creates a branch named `add-supplier-type`.

5. `create_or_update_foundry_object_type` stages the `Supplier` type (with `name`, `country`, `tier` properties) on that branch.

6. `create_or_update_foundry_link_type` stages a one-to-many link from `Supplier` → `PurchaseOrder`.

7. `create_global_proposal` wraps the branch into a reviewable proposal. The agent reports: *"Proposal #42 created — please review and merge in Ontology Manager."*

8. Developer opens Foundry Ontology Manager, inspects the diff (<span style="color:#238551"><b>+2 object types, +1 link type</b></span>), and merges.

9. Agent calls `generate_new_ontology_sdk_version` — new OSDK package version is published to the Developer Console.

10. `install_sdk_package` prints the `npm install` command. Developer runs it and the new `Supplier` TypeScript type is immediately available in their IDE with full autocompletion.

## Documentation map

Sub-pages that live beneath the Palantir MCP section in official docs:

- **Overview** — `/docs/foundry/palantir-mcp/overview`
- **Installation** — `/docs/foundry/palantir-mcp/installation` (per-IDE config snippets for all six supported IDEs)
- **Available tools** — `/docs/foundry/palantir-mcp/available-tools` (full reference for all 14 tool categories)
- **Example MCP workflows** — `/docs/foundry/palantir-mcp/example-mcp-workflows` (dataset search, ontology modification, transform iteration, OSDK generation)
- **Security — Data governance** — `/docs/foundry/palantir-mcp/security` (data flow diagrams for Foundry-hosted vs. local environments)
- **Dev toolchain overview** — `/docs/foundry/dev-toolchain/overview` (positions MCP alongside OSDK, APIs, and Compute Modules)

Related tools often used alongside Palantir MCP:

- **Ontology MCP** — `/docs/foundry/ontology-mcp/overview` (runtime data read/write for external agents)
- **Developer Console** — `/docs/foundry/developer-console/ontology-mcp` (exposes your application's ontology as MCP tools)
- **Compute Modules** — `/docs/foundry/compute-modules/overview`

## Official documentation

- [Palantir MCP — Overview](https://www.palantir.com/docs/foundry/palantir-mcp/overview)
- [Palantir MCP — Installation](https://www.palantir.com/docs/foundry/palantir-mcp/installation)
- [Palantir MCP — Available tools](https://www.palantir.com/docs/foundry/palantir-mcp/available-tools)
- [Palantir MCP — Example MCP workflows](https://www.palantir.com/docs/foundry/palantir-mcp/example-mcp-workflows)
- [Palantir MCP — Security / Data governance](https://www.palantir.com/docs/foundry/palantir-mcp/security)
- [Dev toolchain — Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
