<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · AI PLATFORM</b><br>
<span style="font-size:22px"><b>AIP Assist</b></span><br>
<span style="color:#ABB3BF">An LLM-powered, context-aware support assistant embedded across the Foundry platform that answers natural-language questions about product documentation, developer APIs, and custom organizational content.</span>
</td></tr></table>

## What it is

AIP Assist is a conversational AI assistant built directly into the Palantir Foundry workspace. It uses Natural Language Processing and third-party Large Language Models (LLMs) trained on Palantir's platform documentation to give users real-time, context-sensitive answers without leaving the application they are working in. It responds in all common languages and is designed to serve both end users and developers, from basic navigation questions to deep API and code-authoring support.

## How it works

AIP Assist follows a retrieval-augmented generation (RAG) model where the knowledge base, the query context, and the response generation are all distinct, configurable layers.

1. **Administrator enablement.** AIP Assist is off by default. An enrollment administrator must enable AIP in <span style="color:#2D72D2">Control Panel</span>. Without this step, the sidebar icon does not appear for any user in the enrollment.

2. **User query submission.** A user opens the <span style="color:#2D72D2">AIP Assist sidebar</span> from the workspace navigation bar (bottom-left) or via keyboard shortcut (`Cmd+Shift+U` on macOS / `Ctrl+Shift+U` on Windows). The query is typed into the **Ask a question...** input field as plain natural language.

3. **Mode selection — which knowledge base is queried.** AIP Assist operates in one of four modes, selectable by the user:
   - **AIP Assist (default):** Dynamically routes between platform documentation, developer documentation, and any registered custom content sources, choosing the most relevant corpus for the query.
   - **Platform Documentation Assist:** Restricts retrieval to Palantir's official platform docs only.
   - **Developer Assist:** Specializes on Foundry APIs, SDK references, and common developer code examples.
   - **AIP Chatbots:** Enterprise-specific chatbots authored by internal teams in <span style="color:#2D72D2">AIP Chatbot Studio</span>, using only their designated custom documents.

4. **Application context injection.** Regardless of mode, AIP Assist is aware of which Foundry application is currently active. This context is silently injected into the prompt so that answers are scoped to the relevant tool (e.g., questions asked inside <span style="color:#2D72D2">Code Repositories</span> automatically receive code-repository-relevant responses).

5. **Retrieval and generation.** The LLM retrieves the most relevant documentation chunks from the selected knowledge base and generates a response grounded in that content. AIP Assist does **not** access a user's actual data, datasets, metadata, or workspace contents — the knowledge base contains only documentation.

6. **Custom content sources (RAG extension).** Organizations can extend the knowledge base with internal documents — standard operating procedures, wikis, onboarding guides, workflow documentation — registered through two mechanisms:
   - **Notepad documents** (recommended): content authored directly in Foundry's Notepad tool.
   - **Markdown files in Code Repositories**: in-platform documentation files checked into a code repo.
   After registration, an administrator configures visibility in Control Panel: content can be available globally across the enrollment, or scoped to specific resources. Custom content can back the default AIP Assist or a dedicated chatbot that answers *only* from the custom corpus.

7. **Suggested actions.** After generating a response, AIP Assist may surface <span style="color:#2D72D2">suggested actions</span> — navigational links or in-app prompts that guide the user to the relevant feature or, when the assistant lacks sufficient information, a pre-filled post to the Palantir Developer Community forum. Administrators can disable the forum-redirect suggestion in Control Panel.

8. **Multi-thread management.** The sidebar supports a **chat thread selector**, allowing users to maintain multiple concurrent conversations, create new threads, or delete old ones without losing context from active sessions.

9. **Feedback loop.** Users can rate responses directly in the sidebar. This signal feeds continuous refinement of the assistant's quality.

## User interface

AIP Assist appears as a collapsible right-hand sidebar panel overlaid on the active Foundry application. It does not navigate away from the user's current context.

<table>
<thead>
<tr>
<th style="background:#1C2127;color:#ABB3BF;padding:8px 12px;border:1px solid #383E47">Element</th>
<th style="background:#1C2127;color:#ABB3BF;padding:8px 12px;border:1px solid #383E47">Description</th>
</tr>
</thead>
<tbody>
<tr>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Navigation bar icon</b></span></td>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47">Bottom of the left-side workspace navigation bar; click to open/close the sidebar. Keyboard shortcut shown on hover.</td>
</tr>
<tr>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Mode selector</b></span></td>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47">Dropdown at the top of the sidebar to switch between Default, Platform Docs, Developer Assist, or a custom chatbot.</td>
</tr>
<tr>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Thread selector</b></span></td>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47">Lists active conversation threads; buttons to add a new chat or delete an existing one.</td>
</tr>
<tr>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Chat transcript area</b></span></td>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47">Scrollable message history for the active thread. User messages are right-aligned; assistant messages left-aligned with source citations.</td>
</tr>
<tr>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Ask a question... input</b></span></td>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47">Plain-text entry field at the bottom of the sidebar; supports multi-line input. Submit with Enter or the send button.</td>
</tr>
<tr>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Suggested actions chips</b></span></td>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47">Appear below assistant responses as clickable navigational shortcuts or community forum prompts.</td>
</tr>
<tr>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Feedback controls</b></span></td>
<td style="background:#252A31;padding:8px 12px;border:1px solid #383E47">Thumbs-up / thumbs-down buttons beneath each assistant response.</td>
</tr>
</tbody>
</table>

**Response states:**
<span style="color:#2D72D2"><b>● generating</b></span> (streaming response in progress) · <span style="color:#238551"><b>● complete</b></span> (response delivered) · <span style="color:#CD4246"><b>● error</b></span> (LLM unavailable or enrollment not enabled) · <span style="color:#C87619"><b>● no information found</b></span> (query out of scope for selected knowledge base)

**Per-application integrations** give AIP Assist extra surface area inside specific tools:

- <span style="color:#2D72D2">Code Repositories</span> — "Ask AIP Assist" helper with pre-configured actions; users can attach a full repo, individual files, or selected code snippets as context. The assistant can explain file relationships, identify bugs, and optimize code.
- <span style="color:#2D72D2">Contour</span> — Expression board integration to explain, debug, or translate expressions.
- <span style="color:#2D72D2">Workshop</span> — A "Send to AIP Assist" button widget that developers drop onto their app; launches the sidebar pre-loaded with a static or variable-interpolated prompt derived from application state.
- <span style="color:#2D72D2">Slate</span> — `slate.askAIPAssist` action opens AIP Assist with optional prompt parameters from app state.
- <span style="color:#2D72D2">Ontology Manager</span> — "Explain with AIP Assist" in the Errors tab during Ontology updates; surfaces error explanations and suggested remediation steps.
- <span style="color:#2D72D2">Issues</span> — Available in the issue submission form to answer questions or summarize a long issue description.
- <span style="color:#2D72D2">Carbon Workspaces</span> — Users can interact with pre-configured custom chatbots tailored to specific user groups.

## Worked example

**Scenario: onboarding a new analyst to a custom data pipeline**

1. A Foundry administrator has registered the team's internal onboarding Notepad (covering pipeline naming conventions, dataset access procedures, and SOP for error escalation) as a custom content source, scoped globally to the enrollment.
2. The new analyst is working inside <span style="color:#2D72D2">Code Repositories</span>, viewing an unfamiliar transform file.
3. She presses `Ctrl+Shift+U` to open AIP Assist. The mode is set to **AIP Assist (default)**.
4. She selects the transform file as an attachment and types: *"What does this transform do, and where do I find the dataset naming convention for output datasets?"*
5. AIP Assist generates a response in two parts: (a) an explanation of the transform logic drawn from the attached file context, and (b) naming convention guidance drawn from the registered custom Notepad source — without the analyst knowing which knowledge base each answer came from.
6. A suggested action chip appears: **Open dataset naming conventions doc**. She clicks it and is navigated directly to the Notepad.
7. She thumbs-up the response. The feedback is recorded for quality refinement.

## Documentation map

The following sub-pages live beneath the AIP Assist section in Palantir's Foundry docs:

- **Overview** — entry point, modes, access, and enablement requirements
- **AIP Assist best practices** — query formulation guidance and effective vs. ineffective examples
- **Power AIP Assist with custom content sources — Overview** — how to extend the knowledge base with internal docs
- **Custom content registration** — step-by-step for Notepad and Code Repository sources
- **Custom source deployment** — scoping and visibility configuration in Control Panel
- **AIP Chatbots in Assist** — building dedicated chatbots backed by custom-only corpora via AIP Chatbot Studio
- **Application integrations** — per-tool integration details (Code Repositories, Contour, Workshop, Slate, Issues, Ontology Manager, Carbon Workspaces)
- **Suggested actions in AIP Assist** — what suggested actions are, how to manage them, and how to disable forum redirection

## Official documentation

- [AIP Assist — Overview](https://www.palantir.com/docs/foundry/assist/overview)
- [AIP Assist — Best practices](https://www.palantir.com/docs/foundry/assist/aip-best-practices)
- [AIP Assist — Power AIP Assist with custom content sources](https://www.palantir.com/docs/foundry/assist/aip-assist-custom-docs-overview)
- [AIP Assist — Application integrations](https://www.palantir.com/docs/foundry/assist/application-integrations)
- [AIP Assist — Suggested actions](https://www.palantir.com/docs/foundry/assist/aip-assist-suggested-actions)
- [AIP — Overview](https://www.palantir.com/docs/foundry/aip/overview)
