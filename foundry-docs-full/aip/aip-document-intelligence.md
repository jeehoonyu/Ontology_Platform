<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · AI PLATFORM</b><br>
<span style="font-size:22px"><b>AIP Document Intelligence</b></span><br>
<span style="color:#ABB3BF">A low-code workbench for configuring, evaluating, and deploying document extraction pipelines against enterprise media sets.</span>
</td></tr></table>

## What it is

AIP Document Intelligence is Palantir Foundry's purpose-built application for extracting structured information from large collections of enterprise documents. It lets analysts and developers rapidly prototype extraction strategies — ranging from classic OCR to vision-language-model (VLM) prompting — evaluate their quality and cost on real samples, then deploy the winning strategy as a production-grade Python transform in a single click. The tool became generally available on 4 February 2026.

---

## How it works

AIP Document Intelligence follows a **test-evaluate-deploy** loop. Every session starts with a Foundry **media set** (a dataset containing PDFs, images, or other document formats stored in the Foundry filesystem) and ends with a deployed lightweight Python transform that can process entire collections at scale.

### 1. Media set selection

The user opens the tool and searches for a Foundry media set using the built-in dataset picker. The selected set provides the sample pages that all subsequent strategy runs are executed against. No data is copied out of Foundry; the tool reads directly from the platform's object-storage layer.

### 2. Strategy configuration

Inside the <span style="color:#8ABBFF">**Configuration**</span> tab the user picks one of six extraction strategies:

| Strategy | Description |
|---|---|
| **Raw text** | Reads embedded text directly from PDF byte streams. Fastest, zero AI cost. PDF-only. |
| **Traditional OCR** | Applies optical character recognition to rasterised page images. |
| **Layout-aware OCR** | OCR that preserves spatial layout (columns, tables, reading order). |
| **Generative AI** | Sends each page image to a VLM with a user-supplied prompt. |
| **Generative AI + OCR preprocessing** | Runs traditional OCR first, then passes both the OCR text and the raw page image to the VLM, giving the model richer context. |
| **Layout-aware Generative AI** | Combines layout OCR preprocessing with VLM inference; supports optional table cropping for complex grids. |

For generative strategies the user writes (or edits) the prompt that instructs the VLM. Prompts are stored separately in a `prompts.py` file so they remain in sync with batch deployments.

### 3. Execution

The user triggers a run. Foundry executes the selected strategy page-by-page against the sample documents in the media set. For VLM-based strategies the platform routes requests through the **AIP Model Catalog**, which manages model versions, API keys, and rate limits — Claude (Anthropic) models are referenced directly from the enrollment's model catalog.

### 4. Result review

The <span style="color:#8ABBFF">**Extraction result**</span> tab renders the Markdown output of each extracted page alongside the original PDF image. Bounding boxes drawn on the PDF indicate which regions the strategy parsed, providing a fast visual confirmation loop. The user can page through documents and compare runs side-by-side.

### 5. Evaluation

Clicking <span style="color:#8ABBFF">**Evaluate results**</span> triggers an LLM-as-judge pipeline (requires Anthropic Claude Sonnet to be accessible in the enrollment). A fine-tuned evaluation prompt scores each extraction on a **1–5 scale** across multiple dimensions including table extraction accuracy, header recognition, and overall quality. Aggregate metrics — quality score, token cost, latency — are surfaced in the <span style="color:#8ABBFF">**Evaluate results**</span> tab so the user can compare strategies quantitatively.

### 6. Chunk preview (optional)

The <span style="color:#8ABBFF">**Chunk**</span> tab lets the user preview how extracted text will be segmented using the `DocumentChunker` utility before being passed to downstream RAG pipelines or embedding models. This confirms chunk boundaries look sensible without running the full batch job.

### 7. Deployment

From the <span style="color:#8ABBFF">**Deployment**</span> tab the user triggers a single-click export that generates a fully configured **Python transforms** repository in Foundry Code Repositories. The generated template includes:

- The exact strategy configuration (model reference, prompt, preprocessing flags)
- Output dataset wiring via the `@transform.using` decorator
- An optional `@incremental(...)` decorator (commented out by default) that — when uncommented — processes only new documents on subsequent runs and appends results to the output dataset
- A `THREAD_NUMBER` parameter (default 20, tested up to 300) controlling concurrency
- Post-extraction hooks for `DocumentChunker` and embedding model calls

The generated transforms use **lightweight (non-Spark) compute**, reducing processing time from days to hours for large document collections compared to the legacy Spark-based path. The user reviews the template, then triggers a build to run batch extraction over the entire media set.

---

## User interface

AIP Document Intelligence is a single-page web application inside the Foundry platform. It is composed of three structural zones:

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47;color:#8ABBFF;font-weight:bold">Zone</td>
<td style="padding:8px 12px;border:1px solid #383E47;color:#8ABBFF;font-weight:bold">What you see</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47;color:#FFFFFF"><b>Left sidebar</b></td>
<td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">AI Platform navigation tree. Expandable sections for each AIP tool. The document-intelligence sub-section lists Overview, Core concepts, and Deploy to Python transforms.</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47;color:#FFFFFF"><b>Main workspace</b></td>
<td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">Five top-level tabs: <span style="color:#8ABBFF">Configuration</span> · <span style="color:#8ABBFF">Extraction result</span> · <span style="color:#8ABBFF">Deployment</span> · <span style="color:#8ABBFF">Chunk</span> · <span style="color:#8ABBFF">Evaluate results</span>. Active tab content fills the panel.</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47;color:#FFFFFF"><b>Right panel</b></td>
<td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">Collapsible table of contents with anchor links. In the Extraction result tab this area is replaced by the live PDF viewer with bounding-box overlay.</td>
</tr>
</table>

**Key UI interactions:**

- <span style="color:#2D72D2">**Dataset picker**</span> — a search-and-select dialog for locating a Foundry media set by name or RID.
- <span style="color:#2D72D2">**Strategy selector**</span> — a radio-button group inside the Configuration tab; choosing a generative option reveals a prompt editor textarea.
- <span style="color:#2D72D2">**Preprocessing toggle**</span> — available under Generative AI strategies; enables the OCR-then-VLM dual-pass mode.
- <span style="color:#2D72D2">**Run button**</span> — executes the configured strategy against the loaded sample pages.
- <span style="color:#2D72D2">**Evaluate button**</span> — submits extracted output to the LLM judge; results appear as scored cards in the Evaluate results tab.
- <span style="color:#2D72D2">**Deploy button**</span> — opens a dialog to name the output repository and dataset, then generates the Python transform template.

**Status chips used across the tool:**

<span style="color:#238551"><b>● complete</b></span> · <span style="color:#C87619"><b>● running / pending</b></span> · <span style="color:#CD4246"><b>● failed</b></span> · <span style="color:#2D72D2"><b>● deploying</b></span> · <span style="color:#ABB3BF"><b>● not started</b></span>

---

## Worked example

**Scenario:** A legal team has a Foundry media set (`/Legal/Contracts/2025`) containing 4,000 PDF contracts. They want to extract the counterparty name and effective date from every document.

1. **Open** AIP Document Intelligence and select the `2025 Contracts` media set via the dataset picker. Five sample pages load.
2. **Configure:** Choose **Generative AI** strategy. Write the prompt:
   > *"Extract the counterparty name and the effective date from this contract page. Return JSON: {counterparty, effective_date}."*
3. **Run** against the five samples. The Extraction result tab shows the JSON output side-by-side with the PDF page, with the header region highlighted by a bounding box.
4. **Evaluate:** Click Evaluate results. The LLM judge scores the run 4.2/5 for extraction accuracy; it flags that table-heavy cover pages score lower.
5. **Iterate:** Enable **OCR preprocessing** to give the VLM the typed text alongside the image. Re-run — score improves to 4.7/5.
6. **Deploy:** Click Deploy, name the output dataset `contracts_extracted`, and accept the generated transform template. Uncomment `@incremental(...)` so future contract batches are appended incrementally. Trigger the build — the 4,000-document backfill completes in approximately 2 hours using 20 default threads.

---

## Documentation map

The following sub-pages exist beneath the AIP Document Intelligence section in the Palantir Foundry docs:

- **Overview** — Entry point; feature list and getting-started workflow diagram
- **Core concepts** — Definitions of media sets, preprocessing, extraction strategies, evaluations (LLM judge), and deployment paths
- **Deploy extraction strategies to Python transforms** — Step-by-step deployment guide; template anatomy, incremental processing, thread tuning, prompt customization, and post-extraction chunking/embedding hooks

The tool is listed as one of several **AIP Applications** in the broader AIP overview alongside AIP Analyst, AIP Threads, AIP Chatbot Studio, and AIP Model Catalog.

---

## Official documentation

- [AIP Document Intelligence — Overview](https://www.palantir.com/docs/foundry/document-intelligence/overview)
- [AIP Document Intelligence — Core concepts](https://www.palantir.com/docs/foundry/document-intelligence/core-concepts)
- [AIP Document Intelligence — Deploy extraction strategies to Python transforms](https://www.palantir.com/docs/foundry/document-intelligence/deploy-to-python-transforms)
- [AIP Platform — Overview](https://www.palantir.com/docs/foundry/aip/overview)
