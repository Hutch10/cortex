# Portable Identifier Namespace and Material Occurrence Closure

## 1. Scope
Resolve the architecture precision gap regarding the portable identifier namespace (URN vs application-specific) and the manifest inventory occurrence semantics (material multiplicity and uniqueness keys).

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `c572b75`

## 3. Prior Identity Decision Under Review
*   `PORTABLE_IDENTITY_LIVE_MATERIAL_REFERENCE_DECISION_READY` introduced `urn:vitalicast:` syntax and `portableMaterialIdentity`, but left the URN namespace unregistered and material occurrence rules unreconciled.

## 4. URN Namespace Authority Audit
*   `vitalicast` is an `UNREGISTERED_URN_NAMESPACE` according to IANA/RFC 8141.
*   Therefore, the prior phrase "Vitalicast URNs" is an authority overclaim. The architecture must not claim standards-valid URN semantics without registration.

## 5. Identifier Encoding Models
*   **MODEL E1**: Unregistered `urn:vitalicast:` strings (Rejected, invalid URN).
*   **MODEL E2**: Vitalicast application-specific portable identifier grammar (`vitalicast:<domain>:v1:<uuidv4>`) (Evaluated).
*   **MODEL E3**: Registered `urn:uuid:` plus separate domain field (Rejected, risks cross-domain substitution if parsed incorrectly).
*   **MODEL E4**: Plain UUIDv4 + positional domain (Rejected, poor human interpretation).
*   **MODEL E5**: HTTPS URI identifiers (Rejected, implies network dependency).
*   **MODEL E6**: Future registered Vitalicast URN namespace (Future only).

## 6. Selected Identifier Encoding
**MODEL E2 — Vitalicast application-specific portable identifier grammar**. It provides offline interpretation, explicit identity domains, stable syntax, and avoids invalid standards claims.

## 7. Identifier Terminology Rule
*   **URN / URI**: NOT APPLICABLE. Must not be used for V1 identifiers.
*   **portable identity**: The abstract semantic identity concept.
*   **application-specific portable identifier**: The normative string representation (e.g., `vitalicast:entry:v1:...`).
*   **namespace**: Application prefix (`vitalicast`), not a registered URN namespace.
*   **identity domain**: The semantic category (`entry`, `assertion`, `observation`, `material`).
*   **identifier domain**: The token in the identifier string representing the category.

## 8. Exact V1 Grammar
Format: `vitalicast:<domain>:v1:<uuidv4>`
*   Domains: `entry`, `assertion`, `observation`, `material`.
*   ASCII only, lowercase only.
*   UUID textual form: standard 8-4-4-4-12 lowercase hex.
*   UUID version: exactly v4.
*   UUID variant: exactly variant 1 (RFC 4122).
*   Whitespace, percent-encoding, Unicode: PROHIBITED.
*   Comparison semantics: strictly case-sensitive exact string match. No URI normalization.

## 9. Cross-Domain Substitution Results
*   Entry identifier supplied as assertion identity: `DOMAIN_INVALID` (Structurally valid, but schema-invalid).
*   Assertion identifier supplied as observation identity: `DOMAIN_INVALID`.
*   Observation identifier supplied as material identity: `DOMAIN_INVALID`.
*   Valid UUID with wrong domain prefix (e.g., `invalid`): `STRUCTURALLY_INVALID`.
*   Uppercase prefix / UUID hex: `STRUCTURALLY_INVALID`.
*   UUIDv7 in UUID-shaped text: `UNSUPPORTED_VERSION`.
*   Malformed UUID variant: `STRUCTURALLY_INVALID`.
*   Percent-encoded separators / Unicode homoglyph: `STRUCTURALLY_INVALID`.
*   Leading/trailing whitespace: `STRUCTURALLY_INVALID`.

## 10. Immutable Material Artifact Identity
`portableMaterialIdentity` identifies one intentionally preserved immutable material representation artifact.
*   Preserved across: exact copy, package export, re-export, import, clone.
*   Byte change: Requires a *new* material identity.
*   Representation migration: Requires a *new* material identity.
*   Media type reinterpretation / byte-length / digest disagreement: Same material identity with differing bytes/metrics is an invalid reuse of identity (identity collision/corruption).

## 11. Inventory Occurrence Models
*   **MODEL O1**: One material identity may appear only once per manifest (Evaluated).
*   **MODEL O2**: Multiple occurrences via distinct paths/local references (Rejected, unnecessary complexity).
*   **MODEL O3**: Repeated paths require distinct identities (Rejected).
*   **MODEL O4**: Path aliasing separate from material records (Rejected).

## 12. Selected Inventory Occurrence Model
**MODEL O1 — One material identity may appear only once per manifest**. Vitalicast does not need to emit the identically same immutable artifact at multiple package-relative paths in a single export envelope. This minimizes schema complexity.

## 13. Manifest-Local Reference Semantics
`manifestLocalReference` identifies one strictly manifest-local inventory record/occurrence for artifacts lacking a globally portable identity (e.g., provenance, unsupported artifacts).
*   It does NOT identify a portable material artifact, entry, assertion, observation, or package.
*   It is strictly non-portable and does not survive re-export, partial export, merge, or clone boundaries reliably.

## 14. Material Identity Uniqueness
Within one valid manifest, the number of materially inconsistent records that may use the same `portableMaterialIdentity` is exactly **zero**.

## 15. Manifest Record Uniqueness
*   **Material components**: `portableMaterialIdentity`. (The prior `manifestLocalReference` requirement is removed for material components, as Model O1 ensures uniqueness).
*   **Provenance/Unsupported**: `manifestLocalReference`.

## 16. Package Path Uniqueness
Two records CANNOT use the same normalized package-relative path.

## 17. Material Binding Consistency
Because Model O1 dictates that a `portableMaterialIdentity` appears exactly once per manifest, intra-manifest contextual binding consistency checks (comparing two records with the same identity) will always result in either a duplicate error or a same-key conflict.

## 18. Repeated Material Occurrence Cases A–J
*   **A** (Same identity, digest, path): `DUPLICATE` (Schema invalid).
*   **B** (Same identity, digest, diff path): `SAME_KEY_CONFLICT` (Violates Model O1 single-occurrence rule).
*   **C** (Same identity, diff digest): `MATERIAL_IDENTITY_CONFLICT` (Violates immutable identity rule).
*   **D** (Same identity, diff byte length): `MATERIAL_IDENTITY_CONFLICT`.
*   **E** (Same identity, diff media type): `MATERIAL_IDENTITY_CONFLICT`.
*   **F** (Same identity, diff entry identity): `MATERIAL_IDENTITY_CONFLICT`.
*   **G** (Same identity, diff logical role): `MATERIAL_IDENTITY_CONFLICT`.
*   **H** (Diff identities, equal digest, same entry/role): `VALID` (e.g., two distinct attachments that happen to have identical bytes).
*   **I** (Diff identities, equal digest, diff entries): `VALID`.
*   **J** (Same path, diff material identities): `SCHEMA_INVALID` (Path collision).

## 19. Conflict Live-Material Reference
A conflict observation cites `portableMaterialIdentity` strictly as the portable material artifact reference.
*   It also records: `representationDigest` and `portableEntryIdentity`.
*   It explicitly EXCLUDES: `manifestLocalReference`, package-relative path, source manifest identifier, and package identity.
*   The conflict observation remains stable independently of re-export paths or local references.

## 20. Conflict Equivalence
*   **A** (Same entry + same material id + tombstone): Semantically equivalent conflict.
*   **B** (Same entry + diff material id + equal digest + tombstone): `DISTINCT_CONFLICT` (Distinct material artifact, despite identical bytes).
*   **C** (Same entry + same material id + diff digest): `INVALID_SOURCE` (Material identity corruption).
*   **D** (Same material id at diff path): Irrelevant to conflict observation (path is excluded).
*   **E** (Same material id under diff local ref): Irrelevant to conflict observation.

## 21. Entry Material Uniqueness Wording Correction
Corrected wording: `portableMaterialIdentity` uniquely identifies the immutable material artifact. `manifestLocalReference` uniquely identifies one manifest inventory record for non-portable artifacts. The schema enforces that a `portableMaterialIdentity` appears exactly once per manifest.

## 22. Repeated Conflict Observation Wording Correction
Corrected wording: Repeated evaluation of semantically equivalent unresolved source states reuses an existing conflict observation when available; observation identity itself does not prove semantic equivalence.

## 23. Defer Reaffirmation
Confirmed: `defer` means the absence of a resolution assertion. Active state remains `CONFLICTED`. No Manifest V1 `defer` resolution token is required.

## 24. Privacy Audit
The `vitalicast:<domain>:v1:<uuidv4>` identifier leaks no timestamps, MAC addresses, archive membership, package membership, or export cadences.

## 25. 2076 Archivist Test
The archivist can trivially parse the identifier domain and UUID offline. They understand that identity is abstract and does not independently prove authenticity, custody, or provenance without verifying the corresponding assertions.

## 26. Surviving Assumptions
Manifest-local references are for intra-manifest array addressing only (for non-portable artifacts). Digest equality proves byte equality, not component identity. No package/export-event identity.

## 27. Unresolved Dependencies
Path canonicalization/Unicode semantics, precise role vocabulary.

## 28. Required Canonical Corrections
Narrowly correct `PORTABLE_IDENTITY_AND_LIVE_MATERIAL_REFERENCE_INVESTIGATION.md`, `MANIFEST_ARTIFACT_REFERENCE_AND_MULTIPLICITY_INVESTIGATION.md`, `PACKAGE_MANIFEST_SEMANTIC_SCHEMA_INVESTIGATION.md`, `AVAILABILITY_CONFLICT_OBSERVATION_AND_RESOLUTION_AUTHORITY_CLOSURE.md`, `BETA_3_TRUST_ARCHITECTURE.md`, `BETA_3_IMPLEMENTATION_PLAN.md`, and `ARCHITECTURE_EVIDENCE_DECISION_REGISTER.md` to replace `urn:vitalicast` with the application-specific grammar and enforce Model O1 uniqueness.

## 29. Normative-Contract Unblock Status
`PARTIALLY_UNBLOCKED`.

## 30. Final Precision Classification
**PORTABLE_IDENTIFIER_MATERIAL_OCCURRENCE_PRECISION_CLOSED**
