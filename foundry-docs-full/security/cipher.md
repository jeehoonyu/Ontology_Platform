<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · SECURITY & GOVERNANCE</b><br>
<span style="font-size:22px"><b>Cipher</b></span><br>
<span style="color:#ABB3BF">A Foundry service that obfuscates data using cryptographic operations — encryption, decryption, and hashing — through a permission-controlled Channel/License framework that requires no specialist cryptographic knowledge to operate.</span>
</td></tr></table>

## What it is

Cipher is a Foundry-native service that applies cryptographic operations (encryption, decryption, hashing, and visual pixel scrambling) to dataset columns, object properties, and images. It sits on top of Foundry's existing storage-level and network-level encryption as an **application-layer control**, letting data owners keep sensitive fields encrypted inside the platform until an authorised user actively chooses to decrypt a value. The entire access lifecycle is tracked, giving organisations a cell-level audit trail for privacy-sensitive workflows.

---

## How it works

Cipher's runtime model is built on two first-class Foundry resources — **Channels** and **Licenses** — arranged in a strict hierarchy.

### 1. Create a Cipher Channel

A **Cipher Channel** is a filesystem resource (visible alongside datasets and pipelines in your project) that defines *how* data will be obfuscated. When you create a Channel you choose one algorithm and supply the corresponding key material:

| Algorithm | Type | Notes |
|---|---|---|
| `AES_GCM_SIV` | Encryption — probabilistic | Different ciphertext each call; strongest confidentiality |
| `AES_SIV` | Encryption — deterministic | Same plaintext → same ciphertext; allows equality joins |
| `SHA-256` / `SHA-512` | Hashing — one-way | Requires a user-supplied or auto-generated secret (≥ 14 chars) |
| Image Scrambling | Visual obfuscation | Seed-driven pixel RGB scrambling inside polygon regions |

Key material is either derived via a stretching key-derivation function (recommended) or supplied as a single raw key. The Channel stores the algorithm choice and key configuration and is never readable by ordinary users — only the Cipher service itself reads the Channel at execution time.

### 2. Issue Cipher Licenses

A **Cipher License** is a separate filesystem resource that corresponds to exactly **one** parent Channel. Licenses are the objects you share with users; they gate which operations a user may invoke. Three license types exist:

- **Operational User License** — decrypt individual values in Workshop/Object Explorer; includes cell-level auditing and rate limiting. Cannot touch full columns.
- **Data Manager License** — encrypt, decrypt, or hash full dataset columns in Pipeline Builder, Contour, or Python Transforms. No cell-level audit or rate limit.
- **Admin License** — all Data Manager capabilities plus access to the raw cryptographic key material (needed for key export and visual-obfuscation workflows).

Licenses can be relocated and shared like any Foundry resource; revoking a License removes the user's ability to invoke operations on that Channel.

### 3. Encrypt data in bulk (pipeline-time)

With a Data Manager License in scope, encryption is applied to a full column at build time through three surfaces:

- **Pipeline Builder** — add an `Encrypt`, `Decrypt`, or `Hash` transform node, select the target column (must be String type; cast others first), and point to the License RID. Cipher can auto-generate the pipeline if you open a License with encrypt permission and click **Create Pipeline**.
- **Python Transforms** — import `bellaso-python-lib` and declare an `EncrypterInput`, `DecrypterInput`, or `HasherInput` in the `@transform` decorator. The library exposes `.encrypt_column(col(...), ctx)` for Spark DataFrames and string-level helpers for individual values.
- **Contour** — add a Cipher board to an analysis path; column values are transformed in place but the path cannot be saved back as a dataset.

Encrypted values are written in the canonical format:

```
CIPHER::<channel-rid>::<encrypted-value>::CIPHER
```

This wrapper carries enough metadata for the Cipher service to locate the correct Channel algorithm when decryption is later requested.

### 4. Decrypt individual values at query-time

For Operational Users, the decrypt flow is interactive and audited:

1. The **Ontology Manager** marks a property as `CipherText` type, optionally noting the pre-encryption `Plaintext Type` and a `Default Encryption Cipher Channel`.
2. Encrypted fields render as an **Encrypted Value** renderer in Workshop, Object Explorer, and other Foundry frontends — showing the ciphertext with a "decrypt" affordance.
3. The user submits a **justification**, the Cipher service checks the Operational License, and the plaintext is returned in-place. Every cell-level decryption is logged.
4. Rate limiting on Operational Licenses prevents bulk scraping through the UI.

### 5. Visual obfuscation

For PNG images stored in Media Sets, a Channel with the Image Scrambling algorithm uses a long random seed to scramble RGB pixel values inside user-defined polygons. A **beta Image Display widget** in Workshop lets authorised users select obfuscated regions and click **Decrypt selected areas**, restoring the original pixels. Only PNG is supported because lossless encoding avoids compression artefacts on round-trip.

---

## User interface

Cipher has no single dedicated application screen; it surfaces through several existing Foundry UIs.

### Channel & License creation

<span style="color:#8ABBFF">**Two entry points**</span> for creating a Channel:

- <span style="color:#2D72D2">**Filesystem workspace**</span>: In any project, click **+ New → Cipher Channel**. The wizard presents algorithm cards with descriptions.
- <span style="color:#2D72D2">**Cipher Application**</span>: Accessible under **Platform Apps → Data Governance**.

Once a Channel is open, a prominent <span style="color:#2D72D2">**Create New Cipher License**</span> button launches the License wizard where you choose the license type and set permissions (Encrypt / Decrypt / Hash).

### Pipeline Builder transform panel

<table>
<tr style="background:#1C2127;color:#ABB3BF">
<td style="padding:6px 10px;border:1px solid #383E47"><b>Element</b></td>
<td style="padding:6px 10px;border:1px solid #383E47"><b>What you see</b></td>
</tr>
<tr style="background:#252A31">
<td style="padding:6px 10px;border:1px solid #383E47"><span style="color:#8ABBFF">Transform node</span></td>
<td style="padding:6px 10px;border:1px solid #383E47">Cipher Encrypt / Decrypt / Hash blocks appear in the transform palette under "Security"</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:6px 10px;border:1px solid #383E47"><span style="color:#8ABBFF">Column selector</span></td>
<td style="padding:6px 10px;border:1px solid #383E47">Dropdown listing String columns of the input dataset; non-string columns require a Cast node upstream</td>
</tr>
<tr style="background:#252A31">
<td style="padding:6px 10px;border:1px solid #383E47"><span style="color:#8ABBFF">License picker</span></td>
<td style="padding:6px 10px;border:1px solid #383E47">Path browser pointing to a Data Manager License RID</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:6px 10px;border:1px solid #383E47"><span style="color:#C87619"><b>Preview mode</b></span></td>
<td style="padding:6px 10px;border:1px solid #383E47">Shows placeholder values only; actual ciphertext generated at full build</td>
</tr>
</table>

### Ontology Manager — CipherText property

In the **Properties** tab, each property has a **Property Type** dropdown. Setting it to `Cipher text` enables the encrypted-value renderer everywhere the property appears. An optional `cipher: editable` type class enables inline editing (requires Object Storage V1).

### Object Explorer / Workshop rendering

<span style="color:#238551"><b>● Decrypted</b></span> — plaintext shown inline after justification  
<span style="color:#C87619"><b>● Encrypted</b></span> — `CIPHER::...::CIPHER` shown with a lock icon and decrypt affordance  
<span style="color:#CD4246"><b>● No License</b></span> — field rendered as redacted; no decrypt button visible  
<span style="color:#2D72D2"><b>● Rate-limited</b></span> — decrypt button disabled until the rate-limit window resets

---

## Worked example

**Scenario**: A healthcare analytics team stores patient names in a Foundry dataset. Names must be encrypted by default, but care-team members need to look up individual names through a Workshop application with a full audit trail.

1. **Create Channel** — Data Engineer opens their landing project, clicks **+ New → Cipher Channel**, selects `AES_GCM_SIV` (probabilistic), and configures key derivation with a stretching function. The Channel RID is noted.
2. **Issue a Data Manager License** — Engineer clicks **Create New Cipher License**, chooses Data Manager type, enables Encrypt and Decrypt permissions. License is saved alongside the Channel.
3. **Encrypt the column** — In Pipeline Builder, a new pipeline imports the raw `patients` dataset. A **Cipher Encrypt** transform node is added, targeting the `patient_name` column with the Data Manager License. The pipeline builds; the output dataset now contains `CIPHER::<rid>::<ciphertext>::CIPHER` in every name cell. The original dataset's markings are restricted to Admin.
4. **Configure Ontology** — In Ontology Manager, the `patient_name` property is set to type `Cipher text`. The `Default Encryption Cipher Channel` is pointed at the Channel.
5. **Issue Operational Licenses** — Engineer creates Operational User Licenses (decrypt permission only, rate limit: 100 decryptions/day) and places them in the care-team's shared project.
6. **Care-team workflow** — A nurse opens the patient record in Workshop. The `patient_name` field shows as `Encrypted Value`. She clicks the lock icon, enters justification "admitting patient for procedure X", and the plaintext name appears. The Cipher service logs the decryption event — channel, license, user, timestamp, cell reference — into the audit trail.

---

## Documentation map

- **Overview** — What Cipher is and its primary use cases
- **Core concepts** — Channel and License definitions; ciphertext format `CIPHER::<channel-rid>::<encrypted-value>::CIPHER`
- **Getting started** — Step-by-step channel and license creation, algorithm selection, key configuration
- **Workflows**
  - Apply operations on columns of datasets (Pipeline Builder, Contour, Python Transforms)
  - Decrypt individual values across applications (Workshop, Object Explorer, CipherText property type)
  - Use Cipher for visual obfuscation (Media Sets, Image Display widget, PNG polygon scrambling)
  - Example use case (end-to-end selective decryption with audit trail)
- *(Related)* Data protection and governance — Foundry's broader security layer context

---

## Official documentation

- [Cipher · Overview](https://www.palantir.com/docs/foundry/cipher/overview)
- [Cipher · Core concepts](https://www.palantir.com/docs/foundry/cipher/core-concepts)
- [Cipher · Getting started](https://www.palantir.com/docs/foundry/cipher/getting-started)
- [Cipher · Workflows · Example use case](https://www.palantir.com/docs/foundry/cipher/example-use-case)
- [Cipher · Workflows · Apply operations on columns of datasets](https://www.palantir.com/docs/foundry/cipher/apply-operations)
- [Cipher · Workflows · Decrypt individual values across applications](https://www.palantir.com/docs/foundry/cipher/decrypt-individual-values)
- [Cipher · Workflows · Use Cipher for visual obfuscation](https://www.palantir.com/docs/foundry/cipher/visual-obfuscation)
- [Data protection and governance](https://www.palantir.com/docs/foundry/security/data-protection-and-governance)
