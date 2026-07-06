# Package Manifest Semantic Schema Investigation

## 1. Scope
Define the minimum semantic record model required for a Vitalicast Package Manifest to perform its accepted package-scoped inventory role, establishing a portable semantic contract without inventing new authority.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `efe19da`

## 3. Accepted Prerequisite Decisions
*   `MANIFEST_HISTORICAL_AUTHORITY_DECISION_READY`
*   `PACKAGE_IDENTITY_NOT_REQUIRED_DECISION_READY`
*   `PACKAGE_DIGEST_IDENTITY_PRECISION_CLOSED`
*   `PACKAGE_DIGEST_SCOPE_CANONICALIZATION_DECISION_READY`
*   `MANIFEST_CANONICALIZATION_DIGEST_ANCHOR_DECISION_READY`
*   `COMPARISON_ONLY_MANIFEST_DIGEST_AUTHORITY_CLOSED`

## 4. Manifest Authority Boundary
*   Artifact X is intentionally included: `MANIFEST_AUTHORITY`
*   Artifact X is located at package-relative location P: `MANIFEST_AUTHORITY`
*   Observed bytes for X had digest D under algorithm A: `MANIFEST_AUTHORITY` (as observation)
*   Artifact X has package inventory role R: `MANIFEST_AUTHORITY`
*   Artifact X represents portable archive entry E: `MANIFEST_AUTHORITY` (as package binding observation)
*   Artifact X is historically authentic: `OUTSIDE_MANIFEST_AUTHORITY`
*   Artifact X is original: `OUTSIDE_MANIFEST_AUTHORITY`
*   Artifact X is the current authoritative version: `OUTSIDE_MANIFEST_AUTHORITY`
*   Artifact X supersedes artifact Y: `MANIFEST_MAY_REFERENCE_EXTERNAL_ASSERTION` (via relationship artifacts)
*   Artifact X cites artifact Y: `MANIFEST_MAY_REFERENCE_EXTERNAL_ASSERTION`
*   Artifact X is a tombstone: `MANIFEST_MAY_REFERENCE_EXTERNAL_ASSERTION` (Manifest inventories the tombstone; truth resides in the tombstone)
*   Artifact X is an integrity attestation: `MANIFEST_MAY_REFERENCE_EXTERNAL_ASSERTION`
*   Artifact X is Grade A/B/C/D: `OUTSIDE_MANIFEST_AUTHORITY` (Except manifest is Grade A itself)
*   This package is historically complete: `PROHIBITED_CLAIM`
*   Omitted artifact Y never existed: `PROHIBITED_CLAIM`

## 5. Artifact Category Taxonomy
*   **Archive entry material**: MUST be inventoried. MUST bind to portable identity. MUST have logical role. MUST carry representation digest.
*   **Relationship assertion**: MUST be inventoried. MUST bind to assertion identity. MUST have logical role. MUST carry digest.
*   **Disposition/tombstone**: MUST be inventoried. MUST bind to entry identity. MUST carry digest.
*   **Integrity attestation**: MUST be inventoried. MUST carry digest.
*   **Provenance**: MAY be inventoried.
*   **Manifest/control**: PROHIBITED from inventorying itself.
*   **Human-readable documentation**: MUST be inventoried if intentionally included as payload.
*   **Unsupported future**: MUST be inventoried (by future exporter).
*   **Derived presentation**: MUST be inventoried if intentionally included. MUST have distinct logical role.

## 6. Candidate Record Models
*   **MODEL R1 (Universal Record)**: Rejected. Creates dangerous optional-field ambiguity.
*   **MODEL R2 (Tagged Union)**: Evaluated. Distinct record types prevent ambiguity.
*   **MODEL R3 (Minimal File Inventory + Self-Description)**: Rejected. Path swapping allowed, trusts file content without manifest binding.
*   **MODEL R4 (Minimal Inventory + External Binding)**: Rejected. Excessive indirection.
*   **MODEL R5 (Hybrid Tagged Union)**: Selected. Manifest binds physical material to inventory role and portable identity (where required) using distinct tagged records. Historical relationships and integrity history remain in separate artifacts.

## 7. Selected Record Model
**MODEL R5 (Hybrid Tagged Union)**. Tagged records distinctly define their required fields, avoiding ambiguity and safely delegating complex historical claims to separate evidence artifacts.

## 8. Direct Manifest Binding Fields
*   **record type**: `REQUIRED`.
*   **logical role**: `CONDITIONALLY_REQUIRED` (Required for entry material and derived presentation).
*   **package-relative path**: `REQUIRED`.
*   **media type**: `REQUIRED`.
*   **byte length**: `REQUIRED`.
*   **representation digest algorithm/scope/value**: `REQUIRED`.
*   **portable entry identity**: `CONDITIONALLY_REQUIRED` (Required for primary entry material and tombstones).
*   **artifact-specific portable reference**: `CONDITIONALLY_REQUIRED` (Required for relationship and attestation records).
*   **schema/version**: `PROHIBITED_IN_MANIFEST` (per record). Handled at root package level.

## 9. Logical Role Semantics
`logicalRole` is a package transport/presentation role, not historical truth or disposition state. It prevents path-based meaning.

## 10. Logical Role Vocabulary
Versioned controlled vocabulary.

## 11. Path Authority
Path is transport addressing only. Duplicate paths prohibited. Absolute paths, `.` and `..` forbidden. Backslashes normalized. Not a semantic identity.

## 12. Semantic Uniqueness Keys
*   **Entry material**: `portableEntryIdentity + logicalRole + manifestLocalReference`
*   **Relationship artifact**: `assertionIdentity`
*   **Tombstone**: `portableEntryIdentity` (Minimal state, historical disposition assertions require separate assertionIdentity)
*   **Integrity attestation**: `attestationEventIdentity`
*   **Provenance/Unsupported**: `manifestLocalReference`

## 13. Multi-Representation Rule
Multiple records may bind to one `portableEntryIdentity` if and only if they use distinct `logicalRoles` (e.g., primary vs thumbnail). A derived preview NEVER substitutes for primary entry material. Authority is determined by the entry artifact's grade, not the transport role.

## 14. Relationship Artifact Treatment
The manifest only inventories the relationship artifact and its digest, binding it to a portable assertion identity. The manifest MUST NOT copy relationship source/target fields, avoiding duplicated historical authority.

## 15. Tombstone Treatment
The manifest inventories the tombstone artifact, binds it to the affected `portableEntryIdentity`, and preserves its digest. It MUST NOT directly state disposition facts. Fully destroyed unreferenced entries are completely omitted.

## 16. Integrity Attestation Treatment
The manifest inventories the attestation file and binds it. It MUST NOT copy verification results or act as a historical integrity ledger. Manifest material digest fields are current observations; integrity artifacts preserve historical evidence.

## 17. Provenance Treatment
Explicitly inventoried and bound, but NOT automatically graded or imported into archive history as truth.

## 18. Unsupported Artifact Treatment
Physically verifiable via manifest digest, intentionally included, but meaning is unknown. Preserved as unsupported material; does not reject package.

## 19. Human-readable and Derived Artifact Treatment
Intentionally included human-visible artifacts MUST be inventoried. Unmanifested extra artifacts are strictly ignored.

## 20. Manifest Self-Treatment
**MODEL M1 (No self-inventory)**. The manifest is a distinguished package control artifact and MUST NOT inventory itself.

## 21. Record Authority Matrix
(Conceptually implemented in the definitions above. Manifest record authority is strictly `DIRECT` for transport bindings, `REFERENCE_ONLY` for relationships/tombstones, and `PROHIBITED` for external historical truth.)

## 22. Adversarial Tests A–P
*   A, B, C: `CURRENTLY_INCONSISTENT`.
*   D: `SCHEMA_INVALID`.
*   E: `CONFLICT / SCHEMA_INVALID`.
*   F: Valid distinct roles.
*   G: Schema invalid (relationship semantics prohibited in manifest).
*   H: Valid transport change, context difference detectable upon comparison.
*   I: Valid omission.
*   J: Excluded from import, no manifest authority.
*   K: Preserved as `UNSUPPORTED`.
*   L: Preserved, but claims are outside manifest authority.
*   M: Manifest digest verifies bytes; human interpretation attack out of scope.
*   N, O: `CURRENTLY_INCONSISTENT` (verification fails).
*   P: `SCHEMA_INVALID` (duplicate path).

## 23. 2076 Archivist Test
The archivist can identify intentional artifacts, paths, expected bytes, entry bindings, and differentiate material types. They CANNOT infer historical archive completeness, authenticity, custody, or omitted historical entries.

## 24. Schema-Expression Strategies
**STRATEGY S4 (JSON Schema + canonicalization specification + authority documentation)** selected for implementation portability.

## 25. Primary Recommendation
**MODEL R5 (Hybrid Tagged Union)** and **MODEL M1 (No Self-Inventory)**. The manifest explicitly binds material via tagged records utilizing semantic uniqueness keys, but strictly delegates historical, disposition, and relationship truth to independently preserved evidence artifacts.

## 26. Secondary Alternative
MODEL R2 (Strict Tagged Union without external reference delegation).

## 27. Rejected Models
MODEL R1, R3, R4. (Excessive optionality, dangerous self-description, or excessive indirection).

## 28. Surviving Assumptions
Manifest is package-scoped inventory. Historical authority resides in entries, dispositions, and relationship artifacts.

## 29. Unresolved Dependencies
None.

## 30. Final Architecture Classification
**PACKAGE_MANIFEST_SEMANTIC_SCHEMA_DECISION_READY**

