# Portable Identity and Live Material Reference Investigation

## 1. Scope
Resolve schema-expression dependencies regarding portable identity syntax and live material reference authority. Determine whether conflict observations require a portable material identity distinct from manifest-local references, define the exact URN syntax for identity domains (`assertionIdentity`, `observationIdentity`, `portableMaterialIdentity`), and resolve `defer` conflict-resolution semantics.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `4e13892`

## 3. Normative-Contract Blocker Context
The previous attempt to express the Package Manifest normative contract was blocked by unresolved dependencies regarding the exact syntax of portable identities (`assertionIdentity`, `observationIdentity`), the portability of conflict live-material references, and the semantics of the `defer` resolution outcome.

## 4. Identified Material-Reference Contradiction
*   **Proposition A**: Material components use manifest-local references because cross-package historical material citation was not required. (From `MANIFEST_ARTIFACT_REFERENCE_AND_MULTIPLICITY_INVESTIGATION.md`)
*   **Proposition B**: Availability conflict observations are portable artifacts.
*   **Proposition C**: Availability conflict observations require a live-material reference.
*   **Proposition D**: Conflict equivalence depends partly on the specific live material representation.
*   **Proposition E**: New distinct live material may justify a distinct conflict observation.

## 5. Prior Assumption Audit
`PRIOR_ASSUMPTION_FALSIFIED`. The assumption that cross-package material citation is never required is false because a conflict observation (a portable artifact) must securely reference the specific live material involved in the conflict, even after the observation is merged into a new archive with a completely different manifest context. Manifest-local references are meaningless outside their originating manifest.

## 6. Live-Material Reference Requirements
To support conflict portability across archives without granting entity identity to content digests, the reference must establish **portable component sameness** and **representation equality** independent of the source package context, path, or originating manifest. 

## 7. Material Reference Models
*   **MODEL M1 — Manifest-local reference only**: Rejected. Breaks cross-archive conflict citation.
*   **MODEL M2 — Representation digest reference**: Rejected. Breaks when distinct material components intentionally have identical bytes (e.g. two separate blank template files).
*   **MODEL M3 — Entry identity + logical role**: Rejected. Fails to disambiguate same-role multiplicity (e.g., three attachments).
*   **MODEL M4 — Entry identity + logical role + representation digest**: Rejected. Fails on intentionally distinct byte-identical same-role components.
*   **MODEL M5 — Package-relative path**: Rejected. Paths are transport addressing, not historical identity, and change across re-exports.
*   **MODEL M6 — Portable material component identity**: Selected. Assigns an opaque, globally unique identity to an intentionally inventoried material representation artifact.

## 8. Selected Material Reference Model
**MODEL M6 — Portable material component identity**. One intentionally inventoried material component possesses a portable opaque material identity (`portableMaterialIdentity`) identifying the immutable representation artifact.

## 9. Material Identity/Reference Scope
Applies to **all intentionally inventoried physical payload artifacts** (entry primary material, attachments, etc.) that can participate in relationships or conflict observations.

## 10. Material Identity vs Representation Digest
*   `portableMaterialIdentity`: Identifies the immutable material representation artifact.
*   `representationDigest`: The observed bytes of that artifact.
*   **Same-material changed-digest**: INVALID. If bytes change, it is a new representation artifact with a new `portableMaterialIdentity`.
*   **Byte-identical distinct material**: VALID. Two distinct artifacts may possess distinct `portableMaterialIdentity` values while having identical representation digests.

## 11. Immutable Representation Identity Evaluation
Selected. `portableMaterialIdentity` identifies one immutable representation artifact. This aligns with append-only sanctity-of-failure; modified bytes are new representations, not mutable history.

## 12. Identity Domain Taxonomy
*   `portableEntryIdentity`: Identifies one archive entry subject. (NOT a material component or package).
*   `assertionIdentity`: Identifies one preserved assertion/claim artifact. (NOT the external event).
*   `observationIdentity`: Identifies one preserved deterministic observation artifact.
*   `portableMaterialIdentity`: Identifies one intentionally preserved material representation artifact.

## 13. Portable Encoding Models
*   **ENCODING E1 (Plain UUID)**: Rejected. Ambiguous domains.
*   **ENCODING E2 (Domain-prefixed opaque tokens)**: Rejected. Lacks strict namespace structure.
*   **ENCODING E3 (Vitalicast application-specific identifier)**: Selected. Uses `vitalicast:<domain>:v1:<uuidv4>`.
*   **ENCODING E4 (HTTPS identifiers)**: Rejected. Implies network dependency.
*   **ENCODING E5 (Content-addressed)**: Rejected. Falsified by distinct byte-identical artifacts.

## 14. Opaque Generation Models
Selected **UUIDv4 random** string generation to prevent timestamp leakage, sequential sorting side-channels, or digest identity regressions.

## 15. Selected Encoding Framework
**ENCODING E3 — Vitalicast application-specific identifier** backed by random UUIDv4.

## 16. Exact Syntax Grammar
*   Format: `vitalicast:<domain>:v1:<uuidv4>`
*   `<domain>` must be exactly one of: `entry`, `assertion`, `observation`, `material`.
*   `<uuidv4>` must be standard RFC 4122 lowercase canonical textual representation (e.g., `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).
*   Strictly case-sensitive (all lowercase).
*   No whitespace, no percent-encoding, no Unicode.

## 17. Cross-Domain Substitution Test
Structurally detectable and strictly `DOMAIN_INVALID`. The domain token explicitly prevents using an `assertionIdentity` where a `portableEntryIdentity` is required.

## 18. Conflict Live-Material Reference Rule
A conflict observation artifact strictly cites the `portableMaterialIdentity` and the `representationDigest` of the live material artifact to explicitly bind the observation to the exact material representation.

## 19. Conflict Equivalence Re-audit
Conflict semantic equivalence requires:
`portableEntryIdentity` + `portableMaterialIdentity` + `tombstone state`
*   Exact copied conflict: Duplicate observation (deduplicated during merge).
*   Same entry, same material identity, differing digest: `CORRUPT/INVALID` (material identity is immutable).

## 20. Material Multiplicity Correction
`portableMaterialIdentity` uniquely identifies the immutable material artifact. The schema enforces that a `portableMaterialIdentity` appears exactly once per manifest. `manifestLocalReference` uniquely identifies one manifest inventory record for non-portable artifacts.

## 21. Assertion Identity Syntax
`vitalicast:assertion:v1:<uuidv4>`

## 22. Observation Identity Syntax
`vitalicast:observation:v1:<uuidv4>`

## 23. Assertion Identity Semantics
Identifies one independently authored assertion artifact. Exact copies preserve identity. A corrective assertion requires a *new* `assertionIdentity` targeting the original.

## 24. Observation Identity Semantics
Identifies one deterministic observation artifact. Exact copies are deduplicated by identity. Independently generated equivalent observations receive distinct identities until explicitly merged/deduplicated by later assertions.

## 25. `defer` Resolution Semantics
**MODEL D2 — `defer` is absence of resolution assertion**.
No resolution assertion artifact is created. The conflict remains unresolved, preventing a hidden ledger of non-action events. The normative Package Manifest contract V1 does not require a `defer` token in the schema.

## 26. Privacy/Metadata Leakage Audit
Random UUIDv4 embedded in URNs leaks no creation time, geographic location, source archive, or export cadence.

## 27. 2076 Archivist Test
The prefix explicitly identifies the scheme, domain, and version, ensuring the 2076 archivist can reliably distinguish an entry from a material artifact or an assertion without Vitalicast code.

## 28. Surviving Assumptions
Manifest-local references remain valid for intra-manifest array addressing. Digest equality proves byte equality, not component identity. No package identity, no export-event identity.

## 29. Unresolved Dependencies
Path canonicalization/Unicode semantics and precise role vocabulary remain unresolved, but they are localized to schema expression and do not block the core identity authority closed here.

## 30. Primary Recommendation
Application-specific `vitalicast:` prefix for all portable identities.

## 31. Secondary Alternative
Pure UUIDv4 strings.

## 32. Rejected Models
Plain UUIDs, content-addressing, UUIDv7.

## 33. Required Canonical Corrections
Update `MANIFEST_ARTIFACT_REFERENCE_AND_MULTIPLICITY_INVESTIGATION.md` and `PACKAGE_MANIFEST_SEMANTIC_SCHEMA_INVESTIGATION.md` to introduce `portableMaterialIdentity` as a cross-archive citation target while retaining `manifestLocalReference`. Update `AVAILABILITY_CONFLICT_OBSERVATION_AND_RESOLUTION_AUTHORITY_CLOSURE.md` to cite `portableMaterialIdentity`.

## 34. Normative-Contract Unblock Status
`PARTIALLY_UNBLOCKED`. Schema expression can now model identity fields securely.

## 35. Final Architecture Classification
`PORTABLE_IDENTITY_LIVE_MATERIAL_REFERENCE_DECISION_READY`
