# Palantir MCP (Model Context Protocol)

> An MCP server built into Foundry that lets AI IDEs and agents autonomously design, build, edit, and review end-to-end Foundry applications — from data integration through ontology configuration — on behalf of a developer.

## What it is

Palantir MCP is Foundry's implementation of the open Model Context Protocol standard. It exposes 70+ tools that give LLM agents the context to navigate internal Palantir libraries and understand Foundry architecture, along with the ability to take real actions (search datasets, modify ontology types, generate code) inside the platform. It lives in the **developer toolchain** layer of Foundry alongside the OSDK and VS Code workspaces. The key problem it solves is reducing context-switching: instead of a developer manually looking up documentation, exploring the ontology, and writing boilerplate, an AI agent connected via MCP can handle those auxiliary tasks autonomously while the developer stays focused.

> **Palantir MCP vs. Ontology MCP (OMCP):** These are two distinct features. Palantir MCP targets *ontology builders* (developers) and lets agents modify types and code. Ontology MCP (OMCP) targets *ontology consumers* (end-user systems like Copilot Studio or Gemini Enterprise) and lets external AI agents safely read and write *data* through the ontology.

## When to use it

- When building or iterating on OSDK applications (TypeScript or Python) and you want an AI agent to auto-generate boilerplate, find the right object types, or refactor code.
- When writing Python transforms and you want the agent to fix errors iteratively without breaking focus.
- When exploring an unfamiliar ontology and you want to ask "find me an object type that represents X."
- When creating notional (sample) datasets for prototyping before real data is available.
- When you want to generate a pull request or ontology proposal via natural language instead of manual clicks.

**When NOT to use it / alternatives:**
- If you need an external business system (e.g., Copilot Studio) to query or write *production data* through your ontology, use **Ontology MCP (OMCP)** instead.
- If you only need a code editor without AI actions, the standard VS Code workspace is sufficient.
- Palantir MCP cannot update or delete existing datasets — use the Foundry UI or platform APIs for those operations.

## Key concepts & terminology

- **Model Context Protocol (MCP):** An open standard (not Palantir-specific) that defines how AI clients (IDEs, agents) connect to external tool servers to take actions.
- **MCP server:** The process that Palantir runs exposing Foundry tools; configured once per IDE/client via `npx -y palantir-mcp`.
- **MCP client / AI IDE:** The external IDE or agent (Cursor, Claude Code, Windsurf, GitHub Copilot, etc.) that connects to the MCP server and calls tools.
- **Tool:** A single callable capability exposed by the MCP server (e.g., "search object types," "create dataset," "run SQL").
- **Ontology builder:** A developer who defines and modifies ontology types (object types, link types, action types) — the primary user of Palantir MCP.
- **OSDK (Ontology SDK):** The generated SDK (Python, TypeScript, Java) that Foundry regenerates after ontology changes; MCP can trigger regeneration automatically.
- **RID (Resource Identifier):** Foundry's unique identifier for any resource (dataset, object type, etc.); used in MCP tool calls.
- **Proposal review:** A human-in-the-loop approval step that is *required* before any MCP-initiated ontology modification reaches production.
- **FOUNDRY_TOKEN:** The user-scoped API token placed in the IDE environment so the MCP server authenticates on the developer's behalf.

## Core capabilities / features

- **70+ tools across multiple categories:**
  - *Ontology exploration:* Search object types, link types, action types, and query functions by natural language description.
  - *Ontology modification:* Create and edit object types, link types, and action types — always via a proposal that requires human approval before merging.
  - *Dataset operations:* List accessible datasets, run SQL queries against them, create new datasets with notional data (create only — no update or delete).
  - *OSDK code context:* Fetch code and API context for TypeScript OSDK and Python transform repositories so the agent understands how to use Palantir libraries correctly.
  - *Developer Console integration:* Update Developer Console applications and regenerate the OSDK after ontology changes.
  - *Transform development:* Execute and preview Python transforms; the agent can iteratively fix errors without developer intervention.
  - *Pull request creation:* Generate PRs for code changes directly from an agent prompt.
  - *Documentation search:* Query Palantir documentation and platform metadata in-context.

- **Supports leading AI IDEs:** Claude Code, Cursor, Windsurf, Cline, Continue, and GitHub Copilot in VS Code.

- **VS Code workspace integration:** Developers who use Foundry's built-in VS Code workspace can access Palantir MCP through the integrated AI development tools without any external IDE setup.

- **Non-destructive write controls:** The only write operation available on data is *creating* new datasets. All ontology mutations require a proposal-and-approval workflow, preventing accidental production changes.

- **Governance split by environment:** When running inside Foundry's platform, Palantir-provided LLMs are used and data stays within your environment. When running through a local IDE, data is sent to the external LLM provider (e.g., Anthropic for Claude Code) — governance then depends on your agreement with that provider.

## How it works / typical workflow

1. **Enable in Control Panel:** A platform administrator enables Palantir MCP in the Control Panel under the *Code Repositories* section and grants access to specific users or groups.
2. **Generate a user token:** The developer creates a Foundry user token (scoped to their own permissions) for IDE authentication.
3. **Configure the IDE:** Add an MCP server entry to the IDE's config file pointing to `npx -y palantir-mcp --foundry-api-url https://<your-hostname>` and set the `FOUNDRY_TOKEN` environment variable.
4. **Open a Foundry project repo:** The developer opens an OSDK app or transform repository in the IDE.
5. **Prompt the agent:** The developer asks natural-language questions or gives tasks (e.g., "Find an object type for flight data and add a link to Airport").
6. **Agent calls MCP tools:** The IDE's LLM invokes the appropriate MCP tools (search ontology, propose object type, regenerate OSDK).
7. **Review proposals:** For any ontology change, the developer reviews and approves the generated proposal in Foundry before it merges to the branch.
8. **Iterate:** The agent continues with downstream tasks (writing OSDK application code, creating datasets, fixing transform errors) using fresh ontology context.

## Example

**Scenario:** A developer wants to add a new `FlightRoute` object type linked to an existing `Airport` object type, then regenerate the OSDK for their TypeScript app.

1. Developer opens their TypeScript OSDK repo in Cursor with Palantir MCP configured.
2. Prompt: *"Find the Airport object type in my ontology and create a FlightRoute object type with properties origin, destination (both linked to Airport), and departureDatetime."*
3. The agent calls the `search_object_types` tool, finds `Airport`, then calls `propose_object_type` with the specified properties and link types.
4. The agent presents the proposal for review; developer approves it in Foundry.
5. Agent calls `regenerate_osdk` — the TypeScript OSDK updates automatically.
6. Prompt: *"Now write a React component that lists all FlightRoutes departing today."* — the agent writes the component using the freshly generated OSDK types.

**Minimal IDE config snippet (Cursor `mcp.json`):**
```json
{
  "mcpServers": {
    "palantir": {
      "command": "npx",
      "args": ["-y", "palantir-mcp", "--foundry-api-url", "https://mycompany.palantirfoundry.com"],
      "env": {
        "FOUNDRY_TOKEN": "<your-user-token>"
      }
    }
  }
}
```

## How it connects to the rest of Foundry

- **Ontology:** Palantir MCP's primary surface — it can read and propose changes to object types, link types, action types, and query functions that define the ontology.
- **OSDK (Ontology SDK):** After an ontology change, MCP can trigger OSDK regeneration so TypeScript/Python/Java application code immediately reflects the new types.
- **Code Repositories / Transforms:** MCP can read repository context and execute Python transforms, enabling iterative development loops.
- **Developer Console:** MCP can update Developer Console applications as part of an end-to-end build workflow.
- **Ontology MCP (OMCP):** The complementary feature; Palantir MCP is for *building* the ontology, while OMCP is for *consuming* it from external AI agents.
- **VS Code Workspaces:** Foundry's browser-based VS Code environment has Palantir MCP built in, so cloud-based developers get these tools without any local setup.
- **Global Branching:** MCP-proposed ontology changes are made on branches (like any Foundry change), keeping production safe until explicitly merged.

## Tips & gotchas for learners

- **Admin enablement is required first.** If MCP tools don't appear in your IDE, confirm the feature is enabled in Control Panel — individual developers cannot enable it themselves.
- **Use your own token, not a service account token.** The MCP acts on your behalf and your Foundry permissions determine what it can see and do.
- **Do not include `https://` in the hostname environment variable** — only use it in the `--foundry-api-url` argument flag. Mixing these up is a common misconfiguration.
- **Ontology changes always require human review.** MCP never silently modifies production ontology; a proposal must be approved. Don't expect fully autonomous merges.
- **Data stays external.** When using a local IDE (Cursor, Claude Code, etc.), query content is sent to the external LLM provider. Review your organization's data governance policy before connecting sensitive ontology metadata.
- **Ask the agent "What tools does the Palantir MCP provide?"** — this is the fastest way to discover available capabilities inside any supported IDE.
- **Palantir MCP vs. Ontology MCP confusion is common.** Remember: Palantir MCP = for developers building Foundry; Ontology MCP = for external systems consuming Foundry data.

## Official documentation

- [Palantir MCP — Overview](https://www.palantir.com/docs/foundry/palantir-mcp/overview)
- [Palantir MCP — Getting Started](https://www.palantir.com/docs/foundry/palantir-mcp/getting-started)
- [Palantir MCP — Installation](https://www.palantir.com/docs/foundry/palantir-mcp/installation)
- [Palantir MCP — Example MCP Workflows](https://www.palantir.com/docs/foundry/palantir-mcp/example-mcp-workflows)
- [Palantir MCP — Security & Data Governance](https://www.palantir.com/docs/foundry/palantir-mcp/security)
- [Ontology MCP — Overview](https://www.palantir.com/docs/foundry/ontology-mcp/overview)
- [Dev Toolchain — Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
