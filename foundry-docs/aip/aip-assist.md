# AIP Assist

> An LLM-powered in-platform assistant that helps Foundry users navigate the platform, understand features, write code, and get answers in natural language — without leaving their current workspace.

## What it is

AIP Assist is a conversational AI helper built into Palantir Foundry that answers questions about the platform, Foundry APIs, developer workflows, and your own organization's operational content. It lives in the workspace navigation bar and is always one keystroke away (Ctrl+Shift+U on Windows, Cmd+Shift+U on macOS). Unlike a generic chatbot, AIP Assist is context-aware: it knows which Foundry application you are currently using and can tailor its answers accordingly. It solves the problem of users having to leave Foundry, search external docs, or file a support ticket every time they encounter an unfamiliar feature.

## When to use it

- You are learning a new Foundry tool (Workshop, Code Repositories, Contour, etc.) and want a quick explanation.
- You are writing a Transform or Function and want help with syntax, debugging, or translating code into Foundry expressions.
- Your team needs onboarding help and you want to surface your own SOPs and wikis inside Foundry.
- You are building a Workshop application and want to embed a context-aware "Help" button that opens AIP Assist pre-loaded with a prompt.
- You hit an error in Ontology Manager or an Issues workflow and need an explanation and suggested fix.

**When NOT to use it / alternatives:**
- If you need answers about your actual datasets or objects — AIP Assist does **not** access your data or metadata; use AIP Logic, AIP Analyst, or direct Ontology queries instead.
- For fully automated, multi-step AI workflows, use AIP Logic (for workflow automation) or AIP Chatbot Studio (for standalone agents).

## Key concepts & terminology

- **AIP (AI Platform):** Palantir's broader suite of AI builder tools within Foundry, of which AIP Assist is one component.
- **Enrollment:** The Foundry instance (tenant) belonging to your organization. AIP features must be enabled per enrollment in Control Panel.
- **Control Panel:** The administrative interface where platform admins enable AIP features and configure access permissions.
- **Custom content source:** Internal documentation (SOPs, wikis, best-practice guides) that an admin registers with AIP Assist so it can answer organization-specific questions.
- **Notepad document:** A Foundry-native document format; the recommended way to create custom content sources.
- **Code Repositories documentation type:** A repository configured to hold Markdown documentation files, usable as a custom content source.
- **AIP Chatbot Studio (formerly AIP Agent Studio):** A Foundry builder tool for creating dedicated custom chatbots backed by specific content sources.
- **Default knowledge base:** The set of Palantir platform and developer documentation that AIP Assist searches by default, before any custom sources are added.

## Core capabilities / features

**Operational modes — AIP Assist dynamically picks from:**
- **Default mode:** Searches platform docs, developer docs, and registered custom content sources together.
- **Platform Documentation Assist:** Focuses exclusively on Palantir's official platform documentation.
- **Developer Assist:** Emphasizes Foundry APIs, SDK references, and developer code examples.
- **AIP Chatbots:** Custom enterprise assistants scoped only to content your organization has provided.

**Context-aware application integrations:**
- **Code Repositories:** "Ask AIP Assist" helper with pre-configured code actions; attach whole repos, individual files, or snippets; references dataset/object metadata from attachments.
- **Workshop:** A "Send to AIP Assist" button widget that opens the assistant with a static or dynamically-generated prompt built from application state.
- **Slate:** The `slate.askAIPAssist` action launches AIP Assist with an optional prompt parameter derived from user application state.
- **Contour:** Expression board integration — AIP Assist can explain code, find bugs, and translate content into Contour expressions.
- **Ontology Manager / Issues:** In-context explanations and suggested actions for errors in issue submission or Ontology configuration flows.
- **Carbon Workspaces:** Can be connected to tailored chatbots for specific user groups.

**Custom content sources:**
- Registered via Notepad documents (recommended) or Markdown files in a `documentation`-type Code Repository.
- Can be scoped to always appear, or only when a user views a specific Foundry resource.
- Admins can expose them to the default knowledge base or bind them to a dedicated AIP Chatbot.

**Security:** AIP Assist does not access user data or metadata. It adheres to Palantir's AI Ethics Principles and Foundry-grade security standards. Administrators control access granularity in Control Panel (platform-wide or per resource).

**Multi-language support:** Responds in multiple common languages.

## How it works / typical workflow

1. **Admin enables AIP** in Control Panel for the enrollment.
2. **User opens AIP Assist** via the navigation bar icon or keyboard shortcut (Ctrl+Shift+U / Cmd+Shift+U).
3. **User selects a mode** — Default, Platform Docs, Developer Assist, or a custom chatbot — depending on what kind of help they need.
4. **User types a natural-language question** in the text field (one clear question at a time, with full sentences).
5. **AIP Assist parses the query** using NLP and LLMs, selects the most relevant sources from its knowledge base (platform docs, developer docs, and/or custom content), and returns an answer.
6. **User follows up or refines** — they can attach files/code snippets in Code Repositories context, or click "Send to AIP Assist" in Workshop to arrive with a pre-filled prompt.
7. **User provides feedback** on response quality to help the system improve over time.

## Example

**Scenario:** A new developer is building a Workshop application for field operations. They want users to be able to ask "How do I submit a work order?" and get answers from the company's internal SOP document.

1. An admin creates a Notepad document titled "Work Order SOP" containing the procedure steps.
2. The admin opens the Notepad's Actions menu and selects **Add to AIP Assist**, granting AIP Assist access to the document and scoping it to the Workshop application resource.
3. The developer adds a **"Send to AIP Assist" button widget** in Workshop, configured with the static prompt: "How do I submit a work order using this application?"
4. A field user clicks the button. AIP Assist opens pre-loaded with the prompt, searches the custom SOP content, and returns a step-by-step answer drawn from the internal documentation — not generic Palantir docs.

## How it connects to the rest of Foundry

- **Ontology:** AIP Assist can reference Ontology object types and datasets when they are provided as attachments in Code Repositories context, though it cannot query live data.
- **Workshop:** Deep integration via the "Send to AIP Assist" button widget — useful for building self-service applications.
- **Code Repositories / Transforms / Functions:** Direct code-help integration; attach code for debugging, explanation, or syntax assistance.
- **AIP Chatbot Studio:** The natural next step when you want a standalone, content-scoped chatbot rather than the general-purpose assistant.
- **AIP Logic:** Separate from AIP Assist — AIP Logic is for building automated AI-powered operational workflows, not answering questions.
- **Control Panel:** The administrative backbone — AIP must be enabled here before AIP Assist is available.
- **Contour:** AIP Assist connects to the expression board for code explanation and bug-finding.

## Tips & gotchas for learners

- **AIP must be enabled by an admin first.** If you don't see the AIP Assist icon in the navigation bar, the feature is not yet enabled for your enrollment — contact your platform administrator.
- **AIP Assist cannot see your data.** It knows about platform features and registered documentation, not the contents of your datasets or objects. Don't ask it "Why does my dataset have nulls?" — it cannot know.
- **Be specific.** Vague questions like "This isn't working" produce unhelpful answers. Name the tool, paste the error message, and ask one question at a time.
- **Use full sentences with context.** "How do I configure row-level security in Workshop?" works far better than "row security?"
- **Custom content quality matters.** The usefulness of custom sources depends entirely on how well-written and organized your Notepad or Markdown documentation is — follow the Custom Content Best Practices guide.
- **Scope custom sources carefully.** A custom source set to "always visible" can surface irrelevant answers; scoping it to a specific resource keeps responses targeted.
- **Custom chatbots vs. default knowledge base:** A chatbot backed only by your custom sources gives more precise, scoped answers; the default knowledge base is broader but may mix Palantir docs with your content.

## Official documentation

- [AIP Assist — Overview](https://www.palantir.com/docs/foundry/assist/overview)
- [Power AIP Assist with custom content sources — Overview](https://www.palantir.com/docs/foundry/assist/aip-assist-custom-docs-overview)
- [Serve custom content sources to users](https://www.palantir.com/docs/foundry/assist/adding-documentation-to-aip-assist)
- [Register custom content sources](https://www.palantir.com/docs/foundry/assist/aip-assist-registering-content)
- [AIP Assist application integrations](https://www.palantir.com/docs/foundry/assist/application-integrations)
- [AIP Assist best practices](https://www.palantir.com/docs/foundry/platform-overview/aip-best-practices/)
- [AIP overview](https://www.palantir.com/docs/foundry/aip/overview)
