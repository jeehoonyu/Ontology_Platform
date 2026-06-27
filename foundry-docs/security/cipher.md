# Cipher

> Cipher is Foundry's application for encrypting and tokenizing sensitive data values, so protected fields stay obfuscated unless a user holds an explicit license to decrypt them.

## What it is

Markings control who can access a dataset; Cipher controls whether the **values themselves** are readable. Cipher encrypts or tokenizes sensitive columns/fields so that, even if someone can open the data, they see ciphertext or tokens rather than the real values. Decryption requires a specific **Cipher channel** and a **decrypt license**, providing an additional, value-level layer of protection for the most sensitive data (PII, secrets, identifiers).

## When to use it

- Sensitive values must stay obfuscated even from users who can access the dataset.
- You need tokenization to join/analyze data without exposing raw identifiers.
- You must satisfy strict privacy/regulatory requirements on specific fields.

**When NOT to use it / alternatives:** For dataset/row/column access control use **markings & restricted views**; for general team access use **roles/permissions**.

## Key concepts & terminology

- **Cipher channel** — A configured encryption context (keys/policy) used to encrypt/decrypt.
- **Encryption** — Transforming values into ciphertext.
- **Tokenization** — Replacing values with consistent tokens (enabling joins without exposure).
- **Decrypt license** — The grant allowing a user to reveal protected values.
- **Cipher transform/function** — Encrypts/decrypts within pipelines or logic.

## Core capabilities / features

- **Value-level encryption** — Protect specific fields, not just whole datasets.
- **Tokenization** — Analyze and join on tokens without revealing raw values.
- **Channel-based key management** — Govern keys and decryption policy per channel.
- **Decrypt licensing** — Only licensed users can reveal protected values.
- **Pipeline & logic integration** — Encrypt/decrypt in transforms and functions.
- **Defense in depth** — Layers on top of markings and permissions.

## How it works / typical workflow

1. **Create a Cipher channel** with keys/policy for a class of sensitive data.
2. **Encrypt or tokenize** the sensitive fields (in a transform/pipeline).
3. Downstream consumers see **ciphertext/tokens** by default.
4. **Grant decrypt licenses** only to users who must see raw values.
5. Licensed users **decrypt** where authorized; analysis on tokens proceeds for others.
6. **Audit** decryption usage.

## Example

A `customers` dataset has an `ssn` column. A Cipher channel **tokenizes** it so analysts can still join customers across datasets by the consistent token, but no one sees real SSNs. A small fraud team holds a **decrypt license** to reveal SSNs only when investigating a case — every decryption is audited.

## How it connects to the rest of Foundry

- **Markings & permissions** — Cipher adds value-level protection beyond access control.
- **Transforms / Functions** — Encryption/decryption happens in pipelines and logic.
- **Ontology** — Protected values can flow into object properties as tokens/ciphertext.
- **Audit logs** — Decryption activity is logged for compliance.

## Tips & gotchas for learners

- **Cipher protects values; markings protect access** — they solve different problems and combine well.
- **Tokenization enables analysis** without exposure — great for identifiers used in joins.
- **Guard decrypt licenses** — they're the keys to the raw data.
- **Plan channels per data class** so policy and keys stay manageable.
- **Decryption is audited** — rely on that for compliance reviews.

## Official documentation

- [Cipher: Overview](https://www.palantir.com/docs/foundry/cipher/overview)
- [Security: Overview](https://www.palantir.com/docs/foundry/security/overview)
