<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Webhooks &amp; Listeners</b></span><br>
<span style="color:#ABB3BF">Two-way integration with external systems — outbound webhooks let Actions and Functions call out to other services; inbound listeners let external systems push events into Foundry.</span>
</td></tr></table>

## What it is

Foundry exchanges events with the outside world through two complementary mechanisms:

- **Webhooks (outbound)** — a configured HTTP request, attached to a **REST API source**, that Foundry invokes *from* an Action or Function. Used to write back to or trigger external systems.
- **Listeners (inbound)** — an HTTPS (or WebSocket / email) endpoint that *external* systems POST events to; Foundry validates and ingests them into a dataset.

Outbound applications (OAuth 2.0) hold the credentials Foundry uses to authenticate its outbound calls.

## How it works

**Outbound webhooks**
1. **Definition.** A webhook belongs to a REST API source and declares a request (method, path, headers, query, **body template**), an **input-parameter** schema, and **output parameters** to extract from the response.
2. **Two execution modes.**
   - **Writeback** — the webhook runs as part of the Action transaction. If it fails, the ontology edit is **rolled back** (atomic); on success, response values are extracted and passed to subsequent rules.
   - **Side-effect** — the ontology edit commits first; webhooks fire **best-effort** afterward (any order, non-blocking), and failures are logged without aborting the Action.
3. **Parameter mapping.** `{name}` tokens in the request are substituted from input parameters (or from a Function that returns an array of payloads → batch execution). Output keys are extracted from the JSON response.
4. **Authentication.** Credentials (API key / OAuth 2.0 client credentials) are stored on the source; an OAuth **outbound application** supplies token + refresh. Expired tokens are refreshed before invocation.
5. **Idempotency.** Each invocation carries an idempotency key; a retry with the same key returns the prior result rather than re-calling the external system.
6. **Test / dry-run.** A webhook can be executed against a sample payload to preview the request and validate the response **without** committing.

**Inbound listeners**
1. **Definition.** A listener exposes a webhook URL and an event schema, with an auth method (HMAC signature, bearer token, or API key) and a target dataset.
2. **Event processing.** An incoming POST is **authenticated**, its payload **validated** against the schema, optionally **transformed**, then **appended** to the target dataset. Each event is tracked through `received → validated → persisted`; auth failures and schema failures are recorded (the latter accepted for retry).

## User interface

Configured in **Data Connection** (sources, webhooks, listeners) and surfaced in the **Action / Function** editors when wiring a side-effect or writeback; outbound applications live in **Control Panel**.

<table>
<tr style="background:#1C2127;color:#fff"><th align="left" style="border:1px solid #383E47;padding:6px 10px">Concept</th><th align="left" style="border:1px solid #383E47;padding:6px 10px">Direction</th><th align="left" style="border:1px solid #383E47;padding:6px 10px">Trigger</th></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Webhook — writeback</span></td><td style="border:1px solid #383E47;padding:6px 10px">Outbound</td><td style="border:1px solid #383E47;padding:6px 10px">Action rule (atomic)</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Webhook — side-effect</span></td><td style="border:1px solid #383E47;padding:6px 10px">Outbound</td><td style="border:1px solid #383E47;padding:6px 10px">Action rule (best-effort)</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Listener</span></td><td style="border:1px solid #383E47;padding:6px 10px">Inbound</td><td style="border:1px solid #383E47;padding:6px 10px">External POST</td></tr>
</table>

Execution states: <span style="color:#238551"><b>● success / persisted</b></span> · <span style="color:#CD4246"><b>● failed / auth error</b></span> · <span style="color:#C87619"><b>● validation error (retry)</b></span>.

## Worked example

An Action "Escalate Ticket" runs a **writeback** webhook to the ticketing system with body `{"priority":"{priority}","id":{object_id}}`; if the call returns non-2xx the priority change is rolled back. Separately, a **listener** receives Slack events: it verifies the HMAC `x-signature`, validates the payload, and appends each message to a `slack_events` dataset.

## How it connects to the rest of Foundry

- **Ontology / Actions** — webhooks are Action side-effects/writebacks; failures gate the transaction.
- **Functions** — a Function can invoke a webhook or return the batch of payloads to send.
- **Control Panel** — outbound applications and credentials are governed centrally.
- **Pipelines** — listener-ingested events land in datasets that feed pipelines.

## In this platform (local equivalent)

`webhooks_ops.py` — outbound: `/connections/webhooks` (+ `/{id}/invoke|test|authorize`), `/connections/sources/{id}/credentials`, `/outbound-applications`; inbound: `/listeners` (+ `/{id}/events` POST/GET). Transport is deterministic (a stored `mock_response` stands in for the external system) so writeback-rollback (422), side-effect best-effort, idempotency, parameter substitution, and HMAC/bearer/api-key listener auth are all testable. Verified by `oms/test_webhooks_ops.py` (**78 assertions**).

## Official documentation
- [Data Connection: Webhooks overview](https://www.palantir.com/docs/foundry/data-connection/webhooks-overview)
- [Set up a webhook](https://www.palantir.com/docs/foundry/data-connection/webhooks-setup) · [Webhooks reference](https://www.palantir.com/docs/foundry/data-connection/webhooks-reference)
- [Action types: Webhooks](https://www.palantir.com/docs/foundry/action-types/webhooks) · [Set up webhook](https://www.palantir.com/docs/foundry/action-types/set-up-webhook)
- [Listeners overview](https://www.palantir.com/docs/foundry/data-connection/listeners-overview) · [Event processing](https://www.palantir.com/docs/foundry/data-connection/listeners-event-processing)
- [Configure outbound applications (OAuth 2.0)](https://www.palantir.com/docs/foundry/administration/configure-outbound-applications)
