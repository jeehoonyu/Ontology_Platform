<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Media Sets</b></span><br>
<span style="color:#ABB3BF">A versioned, schema-typed container for storing and processing high-scale unstructured media files — images, audio, video, and documents — within Foundry pipelines.</span>
</td></tr></table>

## What it is

A **Media Set** is Foundry's first-class data asset for unstructured content. Unlike a Dataset (which stores tabular rows) or a Stream (which carries event records), a Media Set holds binary media items — JPEG images, MP3 audio, PDFs, video clips — each addressed by a path within the set. Media Sets participate fully in Foundry's lineage graph, branch model, and build system, so unstructured data can flow through the same governed pipelines as structured data.

## How it works

### Core building blocks

| Object | Description |
|--------|-------------|
| **Media Set** | The top-level Foundry resource (has an RID, lives in a Project, appears in Compass). |
| **Schema type** | Declares the broad category of content: `IMAGE`, `AUDIO`, `VIDEO`, `DOCUMENT`, or `MULTIMODAL`. Governs which transforms and viewers are available. |
| **Primary format** | The canonical file format all items stored in the set must conform to (e.g., `JPEG`, `PNG`, `MP4`, `PDF`). |
| **Additional input formats** | Optional secondary formats that are auto-converted to the primary format on ingest (e.g., accept `PNG` and `BMP` and convert both to `JPEG`). |
| **Media item** | A single binary file stored at a slash-delimited path inside the set (e.g., `2024/frame_001.jpg`). Each item has a stable **RID** and associated metadata. |
| **Media reference** | A lightweight pointer to a media item that can be embedded in a Dataset row or Ontology object property without copying the binary data. |
| **Transaction** | A write boundary (open → put/register items → commit or abort) used by transactional media sets. |
| **Branch** | Media Sets follow Foundry's branch model; a set has a `master` branch and can have feature branches, just like a Dataset. |

### Execution and data-flow mechanics

1. **Creation.** A user opens a Project in Compass, selects **New → Media Set**, picks a schema type and primary format, and optionally configures additional input formats and transaction policy. The Catalog assigns an RID and registers the resource.

2. **Ingestion — direct upload.** Files can be dragged directly onto the Media Set viewer. If a file matches an additional input format it is converted; if it matches the primary format it is stored as-is. Each item lands at the path the user specifies (or a default path derived from the file name).

3. **Ingestion — sync.** A **Media Set Sync** (configured in Data Connection) connects an external source — cloud storage bucket, SFTP, or file share — and writes new or updated files into the set on a schedule. The sync honors transaction policy (transactionless syncs write items immediately; transactional syncs wrap each run in a transaction).

4. **Ingestion — pipeline output.** A Pipeline Builder graph or a Code Repository transform can write computed binary content to a Media Set. The transform declares a `MediaSetOutput`, opens a transaction (if transactional), calls `put_media_item()` for each file, then commits. On failure of a transactional set the entire transaction is aborted and the set remains unchanged. On failure of a transactionless set, successfully written items are retained.

5. **Transaction policies — the key behavioral split.**
   - **Transactional**: Items are only visible after the transaction commits. Only one open transaction is permitted per branch at a time. Supports rollback. Item limit: 10,000 files per transaction; larger uploads must be batched.
   - **Transactionless**: Items are immediately readable after each write. Multiple clients can write concurrently. No rollback is possible. Accessed via `MediaSetOutput(should_snapshot=False)` in Python transforms.

6. **Reading in transforms.** A Python transform (Code Repositories) receives a `MediaSetInput` handle. Key API calls:
   - `media_input.get_media_item_by_path(path)` — fetches a single item by its path.
   - `media_input.list_media_items()` — iterates all items.
   - `fast_copy_media_item(src, dst)` — copies a reference without duplicating the binary blob (preferred for large files).

7. **Media references in structured data.** After processing, transforms can write a Dataset whose rows contain **media reference columns** pointing into a Media Set. These references travel through lineage and can be resolved at query time without re-reading raw binaries.

8. **Ontology integration.** In Ontology Manager, a media reference property type can be added to an Object Type. The property is backed by a media reference column in the linked Dataset. Foundry Functions can read and write these properties; Workshop can render the referenced media inline.

9. **Retention policies.** An optional time-based retention window (e.g., 14 days) can be configured. Media items older than the window are permanently deleted automatically, making Media Sets suitable for high-throughput streaming use cases where data should not accumulate indefinitely.

10. **Incremental processing.** In Python (Spark) transforms, an incremental media set transform processes only newly added items since the last successful build, reducing compute cost for large sets that grow over time.

## User interface

### Media Set viewer (Compass)

When a Media Set resource is opened in Compass the viewer loads in the main panel. The overall layout follows Foundry's standard resource chrome:

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;padding:12px;width:100%;border-collapse:collapse">
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold;white-space:nowrap">UI area</td>
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold">What you see / do</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#fff;white-space:nowrap"><span style="color:#2D72D2"><b>Top toolbar</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Branch selector, build-status badge, <b>Upload</b> button, <b>New transaction</b> button (transactional sets only).</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#fff;white-space:nowrap"><span style="color:#2D72D2"><b>File browser (left panel)</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Tree view of media item paths. Folders are implied by path prefixes. Click a folder to filter; click an item to preview it.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#fff;white-space:nowrap"><span style="color:#2D72D2"><b>Preview pane (center)</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Renders images, PDFs, and audio inline. Displays file path, size, media item RID, and format. Video preview available for supported formats.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#fff;white-space:nowrap"><span style="color:#2D72D2"><b>Details tab</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Shows schema type, primary format, additional input formats, transaction policy, and retention policy. Additional input formats can be edited here after creation.</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#fff;white-space:nowrap"><span style="color:#2D72D2"><b>Lineage tab</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Standard Foundry lineage graph showing upstream inputs (syncs, transforms) and downstream consumers (datasets, other media sets).</td>
</tr>
</table>

### Status indicators

<span style="color:#238551"><b>● Built / committed</b></span> — transaction committed, items visible on branch  
<span style="color:#C87619"><b>● Building / open transaction</b></span> — pipeline run in progress or transaction open  
<span style="color:#CD4246"><b>● Failed</b></span> — pipeline or sync failed; transactional sets retain previous state  
<span style="color:#2D72D2"><b>● Upload / New transaction</b></span> — primary action buttons in the toolbar

### Creation wizard

Select **New** inside a Compass Project → type `media set` in the search bar → choose a **schema type** tile (Image, Audio, Video, Document, Multimodal) → select a **primary format** from the dropdown → optionally add **additional input formats** → click **Create media set**. The set is immediately registered in the Catalog and an empty viewer opens.

### Pipeline Builder integration

In a Pipeline Builder graph, add an **Output** node and choose **Media Set output**. A right-hand config panel prompts for the target Media Set RID, the **Media type**, and the **Format** (must match the primary format of the target). The output node then appears as a sink in the DAG.

## Worked example

**Scenario: Auto-converting uploaded satellite imagery to JPEG for downstream ML**

1. A data engineer creates a new Media Set named `satellite-imagery-jpeg` with schema type **Image**, primary format **JPEG**, and additional input format **TIFF**.
2. A Data Connection sync is configured to pull `.tif` files nightly from an S3 bucket. The sync writes to the media set; Foundry auto-converts each TIFF to JPEG on ingest.
3. A Code Repository Python transform reads from `satellite-imagery-jpeg` using `MediaSetInput`, calls a CV model for each image via `get_media_item_by_path()`, and emits a Dataset of rows containing `(image_path, detection_label, confidence, media_reference)`.
4. In Ontology Manager, the `SatelliteScene` object type gains a `thumbnail` property of type **media reference** backed by the `media_reference` column.
5. A Workshop application renders the `thumbnail` property inline next to each `SatelliteScene` record, with no additional data transfer — the media reference resolves directly against the stored JPEG.

## Documentation map

- **Core concepts → Media sets (unstructured data)** — foundational definitions, schema types, transaction and retention policies
- **Media sets (unstructured data) → Overview** — feature summary and navigational index
- **Media sets (unstructured data) → Importing media** — direct upload and format conversion
- **Media sets (unstructured data) → Advanced media set settings** — schema, format, policy configuration post-creation
- **Media sets (unstructured data) → Virtual media sets** — read-only, dynamically computed media sets
- **Media sets (unstructured data) → Transforming media** — built-in pipeline expressions (e.g., extract-text-from-PDF)
- **Media sets (unstructured data) → Using media in the Ontology** — media reference properties on Object Types
- **Building pipelines → Create a media set batch pipeline with Code Repositories** — step-by-step tutorial
- **Building pipelines → Create a media set batch pipeline with Pipeline Builder** — visual pipeline tutorial
- **Pipeline Builder → Add a media set output** — output node configuration
- **Python → Use media sets with Python transforms** — `MediaSetInput` / `MediaSetOutput` API
- **Python → Media set transforms API reference** — full method signatures
- **Python (Spark) → Incremental media sets** — incremental build patterns
- **Data Connection → Set up a media set sync** — sync configuration from external sources
- **API Reference → Media Sets v2** — REST API for transactions, put/get/register/transform items
- **Product QAs → Media sets** — common questions, error codes, workarounds

## Official documentation

- [Core concepts — Media sets (unstructured data)](https://www.palantir.com/docs/foundry/data-integration/media-sets)
- [Media sets (unstructured data) — Overview](https://www.palantir.com/docs/foundry/media-sets-advanced-formats/media-overview)
- [Media sets — Importing media](https://www.palantir.com/docs/foundry/media-sets-advanced-formats/importing-media)
- [Advanced media set settings](https://www.palantir.com/docs/foundry/media-sets-advanced-formats/media-set-settings)
- [Using media in the Ontology](https://www.palantir.com/docs/foundry/media-sets-advanced-formats/media-in-ontology)
- [Python — Use media sets with Python transforms](https://www.palantir.com/docs/foundry/transforms-python/media-sets)
- [Python (Spark) — Incremental media sets](https://www.palantir.com/docs/foundry/transforms-python-spark/incremental-media-sets)
- [Pipeline Builder — Add a media set output](https://www.palantir.com/docs/foundry/pipeline-builder/outputs-add-media-set-output)
- [Building pipelines — Create a media set batch pipeline with Code Repositories](https://www.palantir.com/docs/foundry/building-pipelines/create-batch-pipeline-cr-media-sets)
- [Media Set basics — API Reference](https://www.palantir.com/docs/foundry/api/media-sets-v2-resources/media-sets/media-set-basics)
- [Product QAs — Media sets](https://www.palantir.com/docs/foundry/questions-answers/media-sets)
