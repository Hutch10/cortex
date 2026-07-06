# Manifest Artifact Reference and Multiplicity Investigation

## 1. Scope
Determine the minimum portable reference model required for manifest records to distinguish entities, representations, relationships, dispositions, attestations, provenance, and unsupported artifacts. Ensure semantic uniqueness keys do not destroy multiplicity, addenda, corrective assertions, failed verification history, or legitimate multiple material components.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `60b1a6f`

## 3. Accepted Prerequisite Decisions
* `MANIFEST_HISTORICAL_AUTHORITY_DECISION_READY`
* `PACKAGE_IDENTITY_NOT_REQUIRED_DECISION_READY`
* `PACKAGE_DIGEST_IDENTITY_PRECISION_CLOSED`
* `PACKAGE_DIGEST_SCOPE_CANONICALIZATION_DECISION_READY`
* `MANIFEST_CANONICALIZATION_DIGEST_ANCHOR_DECISION_READY`
* `COMPARISON_ONLY_MANIFEST_DIGEST_AUTHORITY_CLOSED`
* `PACKAGE_MANIFEST_SEMANTIC_SCHEMA_DECISION_READY`

## 4. Identity/Reference Domain Taxonomy
*   **Portable entry identity**: `PORTABLE_IDENTITY_REQUIRED`. Identifies an archive entry across boundaries. Not a storage key.
*   **Material component/reference**: `MANIFEST_LOCAL_REFERENCE_SUFFICIENT`. Identifies one intentionally inventoried material representation.
*   **Relationship assertion identity**: `EXISTING_IDENTITY_REUSED`. Refers to one historical relationship assertion artifact.
*   **Disposition assertion/tombstone identity**: `PORTABLE_IDENTITY_REQUIRED`. Refers to one disposition assertion or minimal tombstone.
*   **Integrity attestation assertion/assertion identity**: `PORTABLE_IDENTITY_REQUIRED`. Refers to one digest creation/verification event.
*   **Provenance artifact reference**: `MANIFEST_LOCAL_REFERENCE_SUFFICIENT`. Refers to one provenance artifact.
*   **Unsupported artifact reference**: `MANIFEST_LOCAL_REFERENCE_SUFFICIENT`. Allows inventory without semantic interpretation.

## 5. Entity Identity vs Assertion Identity
*   `subject identity != assertion identity`.
*   An assertion must possess its own identity, completely distinct from its subject. This prevents multiple assertions concerning the same subject (e.g., failed then successful verifications, or multiple disposition corrections) from collapsing into a single semantic slot.

## 6. Prior Uniqueness-Key Audit
*   **Entry material**: `portableEntryIdentity + logicalRole` -> `TOO_COARSE`. Collapses multiple valid attachments sharing a role.
*   **Relationship artifact**: `assertionIdentity` -> `SAFE`.
*   **Tombstone**: `portableEntryIdentity` -> `TOO_COARSE`. Prohibits multiple disposition assertions/addenda for one entry.
*   **Integrity attestation**: `subjectReference + algorithm + scope + canonicalizationContract` -> `TOO_COARSE`. Destroys verification failure history and repeated PASS events.
*   **Provenance**: `packageRelativePath` -> `TOO_COARSE`. Ambiguous for multiple provenance records from the same source.
*   **Unsupported artifact**: `packageRelativePath` -> `TOO_COARSE`. Fails to distinguish identical bytes at different paths safely without a manifest-local identifier.

## 7. Entry Material Multiplicity
A single portable entry may legitimately possess multiple material representations sharing the same `logicalRole` (e.g., three original image attachments). The previous key collapses them.

## 8. Material Component/Reference Models
**MODEL M4 (Entry + role + material artifact reference)** is originally selected. However, this is later amended: a distinct `portableMaterialIdentity` is required for globally identifying the immutable material representation artifact, while a manifest-local reference remains required for distinguishing intra-manifest duplicate inclusion (e.g., identical bytes at different paths).

## 9. Manifest-Local Reference Challenge
Historical architecture initially assumed no cross-package material component citation was required. However, the subsequent **Availability Conflict Observation** architecture requires a portable conflict artifact to explicitly cite the specific live material representation involved in a conflict. Therefore, an opaque, globally portable `portableMaterialIdentity` is required for intentionally inventoried material components. The manifest-local reference remains exclusively for intra-manifest transport addressing.

## 10. Relationship Assertion Multiplicity
Multiple distinct assertions may concern the same entities (e.g., multiple citations, or an addendum correcting an earlier assertion). Relationship assertion identity inherently supports this multiplicity.

## 11. Tombstone vs Disposition Assertion Semantics
*   **Tombstone artifact**: The minimal artifact of absence required to satisfy the Two-Scope disposition policy without leaking history.
*   **Disposition assertion artifact**: A detailed historical event record (e.g., custody removal).
They are distinct artifact categories.

## 12. Tombstone/Disposition Multiplicity
One entry may have multiple disposition assertions (e.g., corrections or multiple removal events). Therefore, `portableEntryIdentity` alone is insufficient as a uniqueness key. A disposition assertion must use its own assertion identity. A minimal tombstone, however, is a derived state artifact; its uniqueness may be bound to the entry, provided historical assertions remain separately identifiable.

## 13. Integrity Attestation Multiplicity
PASS and FAIL verifications for the exact same digest context may coexist historically. Therefore, `subjectReference + digest context` is insufficient. An explicit attestation assertion/assertion identity (Model I4) is required.

## 14. Current Digest Observation vs Integrity History
Manifest per-material digest observations are current package inventory fields. They are not historical attestation events. Export does not automatically create integrity-history artifacts. This prevents the manifest from recreating an integrity ledger.

## 15. Provenance Multiplicity/Reference
Provenance artifacts require a manifest-local reference to differentiate multiple artifacts from the same source or byte-identical files with different contexts.

## 16. Unsupported Artifact Multiplicity
Unsupported artifacts require a manifest-local reference to safely inventory identical bytes at different paths without collapsing them.

## 17. Manifest Record Identity Evaluation
**MODEL R2 (Manifest-local record reference)** is selected. Since material components and other artifacts require intra-manifest disambiguation, an opaque manifest-local reference per record safely solves uniqueness without leaking portable identities.

## 18. Multiplicity Matrices
| Artifact category | Multiple per entry/subject? | Repeated observations valid? | Corrective artifacts valid? | Failed/Later Success coexist? | Distinct assertion reference? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Entry material | YES | N/A | YES | N/A | Manifest-Local |
| Relationship | YES | YES | YES | N/A | YES (Portable) |
| Disposition | YES | YES | YES | N/A | YES (Portable) |
| Tombstone | NO (Minimal state) | N/A | N/A | N/A | NO (Entry-bound) |
| Attestation | YES | YES | N/A | YES | YES (Portable) |
| Provenance | N/A | YES | N/A | N/A | Manifest-Local |
| Unsupported | N/A | YES | N/A | N/A | Manifest-Local |

## 19. Duplicate/Conflict/Valid Multiplicity Semantics
*   **Duplicate**: Two records represent the identically same semantic assertion/component (schema invalid).
*   **Same-key conflict**: Two records claim the same semantic slot (e.g., identical manifest-local ID) but disagree on fields.
*   **Valid multiplicity**: Multiple records concern the same subject but possess distinct manifest-local or assertion identities.
*   **Corrective relation**: A later artifact explicitly references an earlier one via its assertion identity.
*   **Verification-history coexistence**: Failed and successful attestations possess distinct assertion identities.

## 20. Adversarial Tests A–O
*   A (Three attachments): Valid multiplicity via distinct manifest-local references.
*   B (Identical bytes, distinct components): Valid multiplicity via distinct references.
*   C (Same reference, different digest): Same-key conflict (`SCHEMA_INVALID`).
*   D (Same relationships, distinct assertion IDs): Valid multiplicity.
*   E (Exact duplicate assertion ID): Duplicate (`SCHEMA_INVALID`).
*   F (Two tombstones for E1): Schema invalid (minimal state). (Two disposition assertions are valid).
*   G (Disposition correction): Valid corrective relation.
*   H (PASS and FAIL coexist): Valid verification-history coexistence via distinct assertion identities.
*   I (Two PASS events): Valid multiplicity.
*   J (Attestation without ID): `SCHEMA_INVALID`.
*   K (Two provenance from one source): Valid via distinct manifest-local references.
*   L (Same provenance bytes, two paths): Valid via distinct manifest-local references.
*   M (Two unsupported, equal bytes): Valid via distinct manifest-local references.
*   N (Changed manifest-local reference, same bytes): Treated as a distinct component, current consistency verifies.
*   O (Preview uses primary's reference): Same-key conflict (`SCHEMA_INVALID`).

## 21. 2076 Archivist Test
The archivist can distinguish primary material from attachments, separate attachments sharing a role, historical assertions from their subjects, and failed from successful attestations—all without needing a database. They cannot infer historical completeness, authenticity, or custody.

## 22. Surviving Assumptions
Manifest is a transport artifact. Historical authority resides in entries, dispositions, and relationship artifacts.

## 23. Unresolved Dependencies
None.

## 24. Primary Recommendation
**MODEL M4** (Entry + role + manifest-local material reference + portable material identity) and **MODEL I4** (Explicit assertion identity). Introduce a `portableMaterialIdentity` for cross-archive citation of material representation artifacts, alongside a manifest-local record reference for intra-manifest transport disambiguation. Require globally portable assertion/observation identities for all historical attestations, dispositions, relationships, and conflicts.

## 25. Secondary Alternative
Portable component identities alone (rejected due to inability to distinguish same-component multi-path transport packaging).

## 26. Rejected Models
MODEL I1 (Digest-context key), MODEL M1 (One material per entry per role).

## 27. Required Canonical Corrections
Update semantic uniqueness keys in `PACKAGE_MANIFEST_SEMANTIC_SCHEMA_INVESTIGATION.md` and related docs.

## 28. Implementation Consequences
Manifest parsers must accept multiple material attachments for the same entry/role, distinguishing them by a local reference.

## 29. Final Architecture Classification
**MANIFEST_ARTIFACT_REFERENCE_MULTIPLICITY_DECISION_READY**

