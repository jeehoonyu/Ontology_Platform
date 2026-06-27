<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · SECURITY & GOVERNANCE</b><br>
<span style="font-size:22px"><b>Audit Logs & Data Governance</b></span><br>
<span style="color:#ABB3BF">Tamper-evident, structured records of every platform action, paired with lifecycle governance tools for sensitive data compliance.</span>
</td></tr></table>

## What it is

Audit Logs & Data Governance is Foundry's built-in accountability layer. Audit logs capture a structured, immutable record of every significant action taken inside the platform — who did what, to which resource, at what time, and whether it succeeded. The companion data governance surface wraps those logs with tooling for classifying sensitive data, enforcing access controls, and meeting regulatory obligations (GDPR, HIPAA, CCPA, and others) across the full data lifecycle from ingestion to deletion.

## How it works

Foundry produces audit records in two schema generations, each with different latency and access characteristics.

**Schema generations**

| | Audit.2 (legacy) | Audit.3 (current) |
|---|---|---|
| Latency | ~24 hours | ~15 minutes |
| API access | Export-only | Public REST API |
| Categories | Optional, loose | Enforced on every event |
| Field names | `request_params` / `result_params` | `requestFields` / `resultFields` |

**End-to-end mechanics (Audit.3)**

1. **Event emission.** Every Foundry service (Compass, Code Repositories, Ontology, AIP, Pipeline Builder, etc.) emits a log line at the moment an operation is executed — not batched, not deferred. Each line carries at minimum one enforced category from the standardized taxonomy.

2. **Schema normalization.** The platform writes each log line in the Audit.3 JSON schema. Core fields include:
   - `time` (RFC3339Nano UTC)
   - `uid` — the most-downstream caller's user ID
   - `orgId` — the organization the event is attributed to
   - `product` — the emitting service name
   - `name` — event identifier, typically `PRODUCT_ENDPOINT` in ALL_CAPS
   - `categories` — set of standardized category strings (e.g., `dataExport`, `userLogin`)
   - `requestFields` / `resultFields` — structured parameters and derived outputs
   - `entities` — all resources (datasets, ontology objects, etc.) referenced in the request or result
   - `result` — success or failure
   - `eventId` / `logEntryId` — event grouping and line deduplication keys
   - `traceId`, `sid`, `tokenId` — cross-request correlation handles

3. **Storage and availability.** Audit.3 logs are available via the public API within ~15 minutes of event occurrence. Audit.2 logs are compiled, compressed, and archived to external object storage (e.g., S3) within ~24 hours.

4. **Delivery path A — direct API ingestion (recommended for SIEMs).** External systems poll two REST endpoints authenticated via a `audit-export:view`-scoped token (obtained through a Developer Console third-party application or OAuth2 client credentials):
   - `list-log-files` — enumerate available log files filtered by date range
   - `get-log-file-content` — retrieve individual file contents with token-based pagination
   This path requires no Foundry intermediary and enables near-real-time SIEM ingestion.

5. **Delivery path B — Foundry export dataset.** Administrators configure a target Foundry dataset in the <span style="color:#8ABBFF">Control Panel → Audit logs → Create export dataset</span> workflow. Both schema versions can be exported. Audit.3 exports append on a regular cadence (max 100 GiB per append); Audit.2 exports max at 10 GiB per append. The export dataset supports per-dataset security markings and start-date filtering. The partition column `date` on Audit.3 exports enables performant Spark queries when filtered first.

6. **Organization attribution.** Each log line is attributed to an organization via the `orgId` field, derived from user-ID-to-org mappings. Service-initiated requests with an empty `origins` field are excluded from org attribution. Maximum retention is 730 days.

7. **Category-based analysis.** Security teams query logs by category rather than by product-specific event names, making queries future-proof: new Foundry features automatically emit events into existing categories, so monitoring queries never require updates when new products launch.

**Audit log categories (major groups)**

| Group | Example categories |
|---|---|
| Data operations | `dataLoad`, `dataExport`, `dataImport`, `dataCreate`, `dataDelete`, `dataTransform`, `dataSearch`, `dataMerge`, `dataPromote` |
| Management | `managementPermissions`, `managementUsers`, `managementGroups`, `managementTokens`, `managementMarkings` |
| Auth | `userLogin`, `userLogout`, `authenticationCheck`, `authorizationCheck` |
| Ontology & logic | `logicAccess`, `ontologyLogicCreate`, `ontologyDataLoad` |
| Infrastructure | `configureInfra`, `containerLaunch`, `restartInfra` |
| Workflow | `monitorRun`, `requestCreate`, `requestApprove`, `requestExecute` |

**Data governance tooling**

Beyond logging, Foundry provides five governance instruments that integrate with audit data:

- **Sensitive Data Scanner** — defines org-specific sensitive data patterns (PII, HIPAA categories, etc.), runs manually or continuously on new data, and triggers automated responses: alerts or auto-applied security markings.
- **Security Markings** — apply classification labels to datasets or individual dataset properties; access is then restricted to users whose roles carry the matching marking clearance.
- **Checkpoints** — require users to supply a written justification before sensitive-data actions proceed, creating an accountability trail aligned with the OECD Purpose Specification principle.
- **Cipher** — a cryptographic service for encryption, decryption, and hashing across pipelines and applications to obfuscate sensitive fields.
- **Data Lifetime / Retention Policies** — define deletion schedules on datasets; supports GDPR right-to-erasure while accommodating regulatory retention mandates.

## User interface

Audit log administration lives in the <span style="color:#8ABBFF">Control Panel</span>, accessible to platform administrators.

**Control Panel → Audit logs**

<table style="background:#1C2127;border:1px solid #383E47;border-radius:4px;width:100%;border-collapse:collapse">
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px;color:#ABB3BF;font-size:12px"><b>PANEL / ACTION</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;font-size:12px"><b>WHAT YOU SEE / DO</b></td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Audit logs overview</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Summary of configured export datasets, schema version in use, and retention window.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Create export dataset</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Form to select schema version (Audit.2 / Audit.3), target dataset path, start date, and optional security marking for the destination dataset.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>API credentials</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Developer Console link to create a third-party application scoped to <code>audit-export:view</code>; displays token issuance instructions for SIEM integration.</td>
</tr>
<tr>
  <td style="padding:8px 12px"><span style="color:#8ABBFF"><b>Retention settings</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF">Slider/numeric field capped at 730 days; applies to both API-accessible and export-dataset log retention.</td>
</tr>
</table>

**Status indicators used throughout the governance UI**

<span style="color:#238551"><b>● Active / Success</b></span> · <span style="color:#C87619"><b>● Pending / Stale</b></span> · <span style="color:#CD4246"><b>● Failed / Violation</b></span> · <span style="color:#2D72D2"><b>● Primary action</b></span> · <span style="color:#ABB3BF"><b>● Disabled / Muted</b></span>

**Sensitive Data Scanner UI** (accessed from <span style="color:#8ABBFF">Control Panel → Sensitive Data Scanner</span>) presents a rule editor for defining regex/pattern-based sensitive data definitions, a scan trigger control (manual or scheduled continuous mode), and a results pane showing matched datasets with a one-click option to apply a security marking or send an alert.

**Checkpoints UI** (accessed within a dataset or pipeline's settings) presents an approval workflow builder: administrators specify a trigger condition (e.g., any `dataExport` event on a marked dataset), a required justification prompt shown to the requesting user, and an approver group. Approved requests generate an audit log entry with the justification text embedded in `requestFields`.

When querying exported Audit.3 datasets inside Foundry (e.g., via Code Workbook or Contour), always apply a `date` partition filter first — the UI query planner surfaces a <span style="color:#C87619"><b>● performance warning</b></span> if a full-table scan is detected.

## Worked example

**Scenario: Investigating a suspected data exfiltration event**

1. A security analyst receives an alert from their SIEM that an unusual volume of `dataExport` events occurred between 02:00–03:00 UTC on 2026-05-15.
2. The analyst queries the Audit.3 export dataset in Contour with the filter `date = '2026-05-15' AND categories CONTAINS 'dataExport' AND time BETWEEN '2026-05-15T02:00:00Z' AND '2026-05-15T03:00:00Z'`.
3. The query returns 47 log lines. Each line's `uid` field points to a single service account. The `entities` field lists 12 distinct dataset RIDs.
4. The analyst cross-references the `orgId` field — all events are attributed to Organization A, which owns those datasets.
5. The `result` field shows `SUCCESS` on all 47 lines, confirming the exports completed. The `tokenId` field is identical across all lines, indicating a single token was used.
6. The analyst navigates to <span style="color:#8ABBFF">Control Panel → Developer Console</span>, locates the token by its `tokenId`, sees it belongs to a pipeline service account, and determines the exports were triggered by a misconfigured scheduled pipeline — not a malicious actor.
7. The analyst revokes the token, patches the pipeline, and appends the Checkpoint justification requirement to that dataset's export action for future accountability.

## Documentation map

- **Security auditing**
  - [Audit logs overview](https://www.palantir.com/docs/foundry/security/audit-logs-overview)
  - [Monitor audit logs](https://www.palantir.com/docs/foundry/security/monitor-audit-logs)
  - [Audit log categories](https://www.palantir.com/docs/foundry/security/audit-log-categories)
- **Data protection and governance**
  - [Data protection and governance overview](https://www.palantir.com/docs/foundry/security/data-protection-and-governance)
  - [Protecting sensitive data — getting started](https://www.palantir.com/docs/foundry/security/protecting-sensitive-data)
  - [Download controls](https://www.palantir.com/docs/foundry/security/download-controls)
- **Broader security surface**
  - [Security overview](https://www.palantir.com/docs/foundry/security/overview)
  - [Shared security responsibility model](https://www.palantir.com/docs/foundry/security/shared-security-responsibility-model)
  - [AIP security and privacy](https://www.palantir.com/docs/foundry/aip/aip-security)
  - [AI FDE — Security and governance](https://www.palantir.com/docs/foundry/ai-fde/security-and-governance)

## Official documentation

- [Audit logs overview](https://www.palantir.com/docs/foundry/security/audit-logs-overview)
- [Monitor audit logs](https://www.palantir.com/docs/foundry/security/monitor-audit-logs)
- [Audit log categories](https://www.palantir.com/docs/foundry/security/audit-log-categories)
- [Data protection and governance](https://www.palantir.com/docs/foundry/security/data-protection-and-governance)
- [Security overview](https://www.palantir.com/docs/foundry/security/overview)
