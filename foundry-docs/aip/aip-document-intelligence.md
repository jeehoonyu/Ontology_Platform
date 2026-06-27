# AIP Document Intelligence

> Foundry's built-in tool for testing, evaluating, and deploying document extraction strategies — from traditional OCR to vision-language models — so that text and structured data locked in enterprise documents can flow into pipelines and the Ontology.

## What it is

AIP Document Intelligence is Foundry's entry point for all document extraction workflows. It solves the problem of getting useful, structured information out of PDFs, scanned images, and other unstructured document formats at enterprise scale. It lives inside the AIP suite alongside tools like AIP Logic and AIP Chatbot Studio. Rather than writing extraction code from scratch, teams use its interactive UI to test multiple extraction strategies side by side, evaluate quality and cost, then deploy the winning strategy to a production Python transform with a single click.

## When to use it

- You have a media set of PDFs, scanned images, or mixed-format documents and need to extract text or structured data from them.
- You want to compare OCR vs. vision-language model (VLM) extraction quality on your specific documents before committing to a pipeline.
- You need to populate a vector database for a Retrieval-Augmented Generation (RAG) system using document content.
- You are extracting tabular data from reports, invoices, or forms for downstream analytics.
- You want to convert legacy paper-based documentation into searchable, structured Foundry datasets.
- You need chunked and embedded text output for semantic search without building the chunking logic yourself.

**When NOT to use it / alternatives:** If your documents are already machine-readable (e.g., structured CSVs or JSON), use standard Foundry data integration pipelines instead. For real-time single-document queries by end users, AIP Chatbot Studio or AIP Threads may be more appropriate.

## Key concepts & terminology

- **Media set** — A Foundry dataset that stores unstructured files (PDFs, images, etc.); AIP Document Intelligence operates on a media set as its input.
- **Extraction strategy** — A specific configuration for how documents are processed: which method (Raw text, OCR, Layout-aware OCR, or VLM) plus any prompt or preprocessing settings.
- **Raw text extraction** — Reads text directly from document metadata; fastest but only works on electronically generated PDFs (not scanned documents).
- **OCR (Optical Character Recognition)** — Traditional character recognition that extracts text without preserving layout structure.
- **Layout-aware OCR** — Advanced OCR that uses bounding boxes to preserve the spatial structure of the document (tables, columns, headers).
- **VLM (Vision Language Model) strategy** — Uses a multimodal AI model with fine-tuned prompts to extract content as Markdown, including complex tables and figures.
- **Preprocessing** — A hybrid mode that runs traditional OCR first and then passes that output alongside the document page image to a VLM, giving the model extra context for complex or low-quality scans.
- **Evaluation** — An automated quality scoring step (1–5 scale) that uses a VLM-as-evaluator to assess extraction results across dimensions like table quality, header recognition, and overall fidelity.
- **Lightweight transforms** — The current deploy target for Document Intelligence; faster than Spark-based transforms and used by default for production document processing.
- **Chunking and embedding** — Post-extraction steps that split extracted text into chunks and generate vector embeddings; supported natively within Document Intelligence as of March 2026.
- **Incremental processing** — A deploy option that processes only newly added documents on each pipeline run rather than reprocessing the entire media set.

## Core capabilities / features

**Multiple extraction methods**
- **Raw text**: Zero-compute extraction from PDF metadata; suitable only for digitally created PDFs.
- **OCR**: Proven optical character recognition for scanned documents; does not retain layout.
- **Layout-aware OCR**: Uses bounding boxes to reconstruct column and table layout; better for structured documents.
- **VLM strategies**: Multimodal model analysis with fine-tuned prompts that output Markdown; best for complex layouts, figures, and mixed content.
- **Preprocessing**: Combines OCR output with VLM analysis for documents where VLM alone struggles.

**Interactive testing and evaluation UI**
- Browse and select a Foundry media set directly in the UI.
- Run multiple strategies and view results as rendered Markdown mapped back to bounding boxes on the original document page.
- Side-by-side comparison of quality scores, execution speed, and token/compute cost for each strategy.
- LLM-based evaluation scores (1–5) across specific quality dimensions (tables, lists, code blocks, headers).

**One-click deployment to Python transforms**
- After validating a strategy, generate a production-ready Python transform repository automatically.
- The template configures dataset references, model references, and custom prompts from the Document Intelligence settings.
- Output schema: one row per page with fields for media item ID, media reference, page number, and extracted content.
- Adjusting prompts should be done in Document Intelligence first, then redeployed, to keep the transform in sync.

**Chunking and embedding (GA March 2026)**
- Natively chunk extracted text and generate vector embeddings end-to-end inside the platform.
- Enables direct population of vector databases for RAG workflows without additional custom code.

**Performance controls**
- Default `THREAD_NUMBER` of 20 concurrent threads; can be raised to ~300 in development for faster bulk runs.
- Incremental mode available via the `@incremental(...)` decorator to process only new documents.

## How it works / typical workflow

1. **Prepare your media set.** Upload enterprise documents (PDFs, images) into a Foundry media set dataset.
2. **Open AIP Document Intelligence.** Navigate to the tool within the AIP section of Foundry.
3. **Select your media set.** Use the search UI to point Document Intelligence at your media set.
4. **Choose and configure an extraction strategy.** Pick from Raw text, OCR, Layout-aware OCR, or a VLM strategy. Optionally enable preprocessing or write a custom VLM prompt.
5. **Run the extraction.** Execute the strategy against a sample of your documents.
6. **Review and evaluate.** Inspect the Markdown output mapped to the original document pages. Review the automated evaluation scores for quality, speed, and token cost.
7. **Iterate.** Adjust the strategy (change method, tune prompts, enable preprocessing) and re-run until quality is satisfactory.
8. **Deploy to Python transforms.** Click deploy to generate a Python transforms repository. Specify the output dataset, then trigger a build.
9. **Optionally enable chunking and embedding.** If building a RAG pipeline, configure chunking parameters and embedding model in the deploy step.
10. **Monitor and maintain.** Use incremental mode for ongoing ingestion of new documents. Adjust prompts in Document Intelligence and redeploy if document types change.

## Example

**Scenario:** A legal team has 10,000 scanned contract PDFs stored in a Foundry media set. They need to extract clause text for semantic search.

1. They open Document Intelligence and select the contracts media set.
2. They try Raw text first — poor results because the documents are scanned, not digital.
3. They try OCR — text is extracted but table-of-contents structure is lost.
4. They enable Layout-aware OCR with preprocessing + a VLM strategy. Evaluation scores jump from 2.3 to 4.6 for table and header quality.
5. They deploy to a Python transform. The generated transform looks roughly like:

```python
# Auto-generated by AIP Document Intelligence
@transform(
    output=Output("/Legal/contracts_extracted"),
)
# @incremental(...)  # Uncomment to process only new documents
def extract_contracts(ctx):
    # THREAD_NUMBER = 20  # Increase for faster processing
    ...
```

6. The output dataset has one row per page with extracted Markdown. They then pipe it into a chunking/embedding step to populate a vector store for RAG.

## How it connects to the rest of Foundry

- **Media sets** — Document Intelligence requires a Foundry media set as its input source; media sets are the standard Foundry mechanism for storing unstructured files.
- **Python transforms** — Deployed extraction strategies become Python transforms in the Foundry pipeline graph, producing structured output datasets that feed downstream logic.
- **Ontology** — Extracted structured datasets can be linked to Ontology object types, making document content queryable and actionable through the Ontology layer.
- **AIP Logic / Functions** — Downstream AIP Logic workflows or Ontology Functions can consume the extracted text datasets to drive automated actions.
- **AIP Chatbot Studio / AIP Threads** — Chunked and embedded outputs can back a RAG retrieval system used by chatbot agents built in Chatbot Studio or surfaced through Threads.
- **Workshop** — Extracted and Ontology-linked data can be surfaced in Workshop applications for end users to search and interact with document content.
- **AIP Model Catalog** — The VLM strategies and evaluations call models managed in the AIP Model Catalog; Claude Sonnet is used for evaluations.

## Tips & gotchas for learners

- **Match the method to your document type.** Raw text is zero-cost but useless on scanned docs. Start with Layout-aware OCR as a general baseline, then try VLM if tables or figures are critical.
- **Always evaluate before deploying.** The evaluation scores (1–5) are cheap to run and will save you from deploying a strategy that looks fine on one page but fails on others.
- **Edit prompts in Document Intelligence, not in the transform.** The generated Python transform inherits prompts from Document Intelligence settings. If you edit the transform directly and then redeploy, your edits will be overwritten.
- **Preprocessing adds cost.** Enabling preprocessing runs OCR and a VLM — roughly double the compute. Use it only when raw VLM results are insufficient.
- **Preview mode does not work** in the generated Python transform template; this is expected behavior. Actual pipeline builds work correctly.
- **Incremental mode is off by default.** If you are processing a growing media set, uncomment the `@incremental` decorator to avoid reprocessing every document on every run.
- **Evaluations require Claude Sonnet.** If your Foundry enrollment does not have Claude Sonnet (Anthropic) available, the evaluation feature will not function.
- **GA date:** AIP Document Intelligence became generally available on February 4, 2026, and is enabled by default for all AIP enrollments. Chunking and embedding support was added in March 2026.

## Official documentation

- [AIP Document Intelligence — Overview](https://www.palantir.com/docs/foundry/document-intelligence/overview)
- [AIP Document Intelligence — Core Concepts](https://www.palantir.com/docs/foundry/document-intelligence/core-concepts)
- [AIP Document Intelligence — Deploy Extraction Strategies to Python Transforms](https://www.palantir.com/docs/foundry/document-intelligence/deploy-to-python-transforms)
- [AIP Overview](https://www.palantir.com/docs/foundry/aip/overview)
