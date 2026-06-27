# Media Sets

> A media set is Foundry's storage primitive for unstructured and binary content — images, PDFs, audio, video, and other documents — alongside the structured datasets that describe them.

## What it is

Datasets are great for tabular rows, but much real-world data is unstructured: scanned invoices, inspection photos, call recordings, sensor blobs. Media sets store this binary content in Foundry with governance and addressability. Each item gets a **media reference** that can be stored as a property value on a dataset row or an Ontology object, linking structured records to their underlying files. Transforms and AIP tools (like Document Intelligence) can then process the media — extracting text, running OCR, or feeding multimodal models.

## When to use it

- You need to store and govern images, PDFs, audio, video, or arbitrary documents.
- You want to associate files with structured rows/objects via references.
- You're building document-extraction or computer-vision/multimodal workflows.

**When NOT to use it / alternatives:** For purely tabular data use **datasets**. For real-time event streams use **streams**.

## Key concepts & terminology

- **Media set** — A governed collection of binary media items.
- **Media item** — A single file (image, PDF, audio clip, etc.) in the set.
- **Media reference** — A pointer value linking a dataset row or object property to a media item.
- **Media reference property** — An object-type property whose base type is a media reference.
- **Schema / metadata** — Structured attributes describing each media item.
- **Transform over media** — Code that reads media items to derive structured outputs (e.g., extracted text).

## Core capabilities / features

- **Unstructured storage with governance** — Binary content gets the same markings/permissions as other Foundry data.
- **Media references** — Bind files to structured rows and Ontology objects so apps can display them.
- **Ingestion via syncs** — Land files from cloud storage/SFTP into a media set.
- **Processing in transforms** — Read media programmatically to extract text, run OCR, or call models.
- **AIP integration** — Document Intelligence and multimodal models operate over media sets.
- **Display in apps** — Workshop and Object Views can render referenced media (image/PDF viewers).

## How it works / typical workflow

1. **Create a media set** (or land files into one via a file-based sync).
2. **Ingest media items** — images, PDFs, etc., with optional metadata.
3. **Reference media** from a dataset/object via a media-reference property.
4. **Process** items in a transform or with **AIP Document Intelligence** (extract text, OCR, embeddings).
5. Surface results in the **Ontology** and **Workshop** (e.g., show the invoice next to its extracted fields).

## Example

An invoice-processing workflow:

1. Scanned invoice PDFs land in a media set via SFTP sync.
2. Each `Invoice` object stores a **media reference** to its PDF.
3. **AIP Document Intelligence** runs layout-aware OCR to extract vendor, total, and date.
4. Extracted fields populate `Invoice` object properties.
5. A Workshop app shows the PDF beside the extracted, editable fields.

## How it connects to the rest of Foundry

- **Ontology** — Media-reference properties link objects to their files.
- **AIP Document Intelligence** — Extracts structure from media items.
- **Transforms** — Process media programmatically.
- **Workshop / Object Views** — Render media (image/PDF/audio viewers).
- **Data Connection** — File-based syncs ingest media from external storage.

## Tips & gotchas for learners

- **Use media references, not copies** — link structured records to media rather than duplicating bytes.
- **Media sets are governed like datasets** — markings and permissions still apply.
- **Pair with Document Intelligence** for the easiest path from documents to structured data.
- **Large media volumes** need attention to storage and processing cost.
- **Not for tabular data** — keep structured attributes in datasets/objects, files in media sets.

## Official documentation

- [Media sets: Overview](https://www.palantir.com/docs/foundry/media-sets/overview)
- [AIP: Document Intelligence](https://www.palantir.com/docs/foundry/aip/overview)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
