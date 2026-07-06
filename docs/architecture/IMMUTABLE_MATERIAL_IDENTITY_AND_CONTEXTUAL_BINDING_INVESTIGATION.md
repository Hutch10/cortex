# Immutable Material Identity and Contextual Binding Investigation

## 1. Scope
Conduct a narrow architecture investigation to determine exactly which properties are intrinsic to an immutable material representation artifact (`portableMaterialIdentity`) and which properties are contextual manifest bindings or assertions about that material.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `c800718`
* **Worktree**: Clean (except untracked scratch/ and terra-pulse-demo/)

## 3. Prior Occurrence Decision Under Review
* `PORTABLE_IDENTIFIER_MATERIAL_OCCURRENCE_PRECISION_CLOSED` assigned `MATERIAL_IDENTITY_CONFLICT` to differing `logicalRole` and `mediaType` values, potentially making contextual bindings identity-defining.

## 4. Material Identity Models
* **MODEL M1 (Immutable bytes identity)**: Identity = exact representation bytes.
* **MODEL M2 (Immutable representation contract identity)**: Identity = exact bytes + media type interpretation.
* **MODEL M3 (Immutable entry-bound material identity)**: Identity = exact bytes + portable entry binding.
* **MODEL M4 (Immutable semantic material identity)**: Identity = exact bytes + entry + role + media type.
* **MODEL M5 (Artifact identity + explicit binding assertions)**: Identity = exact bytes; bindings are external assertions.

## 5. Selected Material Identity Model
**MODEL M3 — Immutable entry-bound material identity**.
Vitalicast rejects direct shared-material semantics across different entries to prevent ambiguous ownership and historical authority. Thus, `portableEntryIdentity` is intrinsically bound to `portableMaterialIdentity`. However, `logicalRole` and `mediaType` remain contextual manifest bindings.

## 6. Intrinsic vs Derived vs Contextual Property Matrix
* **Exact representation bytes**: `INTRINSIC_IDENTITY_PROPERTY`
* **Representation digest**: `DERIVED_REPRESENTATION_OBSERVATION`
* **Byte length**: `DERIVED_REPRESENTATION_OBSERVATION`
* **Digest algorithm/scope**: `DERIVED_REPRESENTATION_OBSERVATION`
* **Portable entry identity**: `INTRINSIC_IDENTITY_PROPERTY`
* **Media type**: `CONTEXTUAL_MANIFEST_BINDING` (An interpretation of the bytes)
* **File extension**: `CONTEXTUAL_MANIFEST_BINDING` (Transport convention)
* **Package-relative path**: `CONTEXTUAL_MANIFEST_BINDING`
* **Manifest-local reference**: `CONTEXTUAL_MANIFEST_BINDING`
* **Logical role**: `CONTEXTUAL_MANIFEST_BINDING`
* **Preservation grade**: `CONTEXTUAL_ASSERTION` (Outside manifest authority)
* **Source authority**: `CONTEXTUAL_ASSERTION`
* **Artifact category/record type**: `CONTEXTUAL_MANIFEST_BINDING`

## 7. Byte-Change Rule
Any byte change (transcoding, metadata rewrite, repair, corruption, malicious substitution) results in fundamentally different exact bytes. Therefore, any byte change requires a **new** `portableMaterialIdentity`. Reusing the same material identity for different bytes is always a `MATERIAL_IDENTITY_CONFLICT`.

## 8. Media-Type Authority
`mediaType` is a contextual interpretation of immutable bytes within a specific manifest. The exact same `portableMaterialIdentity` and bytes may legitimately be classified as `application/octet-stream` in one manifest and `image/tiff` in a later manifest. This is a `VALID_CONTEXTUAL_VARIATION`, not a material identity conflict.

## 9. Logical-Role Authority
`logicalRole` is a transport and presentation role. The exact same `portableMaterialIdentity` may legitimately serve as `primary` in one package and `alternateRepresentation` in another. This is a `VALID_CONTEXTUAL_VARIATION`.

## 10. Entry-Binding Authority
Under Model M3, a `portableMaterialIdentity` intrinsically belongs to exactly one `portableEntryIdentity`. Differing `portableEntryIdentity` for the same material identity is a `MATERIAL_IDENTITY_CONFLICT`.

## 11. Shared-Material Models
* **MODEL S1**: One material identity belongs to exactly one entry (Selected).
* **MODEL S2**: Material identity independent of entry membership (Rejected).
* **MODEL S3**: Shared material requires explicit material-binding assertions (Rejected).
* **MODEL S4**: Shared entry binding unsupported in V1 (Selected).

## 12. Attachment Semantics
If Entry E2 is an addendum concerning Entry E1's image material (M1), E2 MUST cite E1 or cite M1 through a relationship assertion. E2 MUST NOT directly bind M1 as its own entry material. Direct cross-entry material reuse creates ambiguous historical authority and is prohibited.

## 13. Manifest Material-Binding Authority
A manifest record containing M1, E1, and Role R is authorized to assert:
> "M1 is intentionally included in this package in association with E1 under transport/presentation role R."
It is NOT authorized to assert that M1 intrinsically possesses Role R for all of history.

## 14. Material Identity Scope by Artifact Category
* **Entry material**: `PORTABLE_MATERIAL_IDENTITY_REQUIRED`
* **Relationship assertion artifact**: `PORTABLE_ASSERTION_IDENTITY_ONLY`
* **Tombstone artifact**: `PORTABLE_ENTRY_IDENTITY_ONLY`
* **Integrity attestation artifact**: `PORTABLE_ASSERTION_IDENTITY_ONLY`
* **Disposition assertion artifact**: `PORTABLE_ASSERTION_IDENTITY_ONLY`
* **Conflict observation artifact**: `PORTABLE_OBSERVATION_IDENTITY_ONLY`
* **Conflict resolution assertion artifact**: `PORTABLE_ASSERTION_IDENTITY_ONLY`
* **Provenance artifact**: `MANIFEST_LOCAL_REFERENCE_SUFFICIENT`
* **Unsupported artifact**: `MANIFEST_LOCAL_REFERENCE_SUFFICIENT`
* **Human-readable documentation**: `MANIFEST_LOCAL_REFERENCE_SUFFICIENT`
* **Derived presentation artifact**: `MANIFEST_LOCAL_REFERENCE_SUFFICIENT`

## 15. Claim Identity vs Physical Material Identity
Assertion and observation identities identify the *semantic claim/observation*, not the physical representation bytes. A manifest needs only the `assertionIdentity` (or `observationIdentity`) and `manifestLocalReference` for the physical serialization. It does NOT require a `portableMaterialIdentity` for assertion/observation records.

## 16. Assertion Representation Multiplicity
One assertion identity (A1) may have multiple physical serializations (B1, B2) across different archives. A new serialization of the same semantic claim is an alternate representation of the same assertion, not a new assertion.

## 17. Observation Representation Multiplicity
Like assertions, an observation identity identifies the semantic observation. Alternate serializations are just alternate representations.

## 18. Provenance Material Identity
Provenance artifacts do NOT require `portableMaterialIdentity`. Assigning portable material identity to optional provenance context accidentally elevates it to historical lineage. `manifestLocalReference` is sufficient.

## 19. Unsupported Material Identity
Unsupported artifacts do NOT require `portableMaterialIdentity`. If the semantic meaning is unknown, assigning a portable identity creates meaningless overhead. `manifestLocalReference` is sufficient.

## 20. Conflict Live-Material Reference Re-Audit
A conflict observation cites the live material's `portableMaterialIdentity`, its `portableEntryIdentity`, and its `representationDigest`. It does NOT cite `logicalRole`, `mediaType`, or `manifestLocalReference`. This cleanly aligns with Model M3 (where identity and entry are intrinsic, and role/media-type are contextual). Same material identity with a different contextual role does NOT create a new availability conflict.

## 21. Material Consistency Taxonomy
* `MATERIAL_IDENTITY_CONFLICT`: Invalid reuse of `portableMaterialIdentity` (e.g. diff bytes, diff entry).
* `REPRESENTATION_OBSERVATION_CONFLICT`: Invalid derived observation (e.g. same bytes but digest mismatch).
* `CONTEXTUAL_BINDING_DIFFERENCE`: Normal contextual difference between manifests (e.g. diff role).
* `CONTEXTUAL_BINDING_CONFLICT`: Invalid context within a single manifest (e.g. duplicate paths).
* `VALID_CONTEXTUAL_VARIATION`: Acceptable contextual difference.
* `UNSUPPORTED`: Not supported in V1.

## 22. Material Cases A–M
* **A (Same M1, same bytes, same entry, same role)**: `VALID_CONTEXTUAL_VARIATION` (across packages) or `DUPLICATE` (within one package).
* **B (Same M1, same bytes, same entry, diff role)**: `VALID_CONTEXTUAL_VARIATION` (across packages).
* **C (Same M1, same bytes, diff entry)**: `MATERIAL_IDENTITY_CONFLICT` (Violates Model M3).
* **D (Same M1, same bytes, diff media type)**: `VALID_CONTEXTUAL_VARIATION`.
* **E (Same M1, diff bytes)**: `MATERIAL_IDENTITY_CONFLICT`.
* **F (Diff M1, equal bytes, same entry and role)**: `VALID` (e.g. user manually uploaded the same file twice as distinct artifacts).
* **G (Diff M1, equal bytes, diff entries)**: `VALID` (Two distinct artifacts that happen to share byte content).
* **H (Assertion A1 represented by material M1)**: `SCHEMA_INVALID` (Assertions do not use material identity).
* **I (Same assertion A1 represented by exact-copy M1)**: N/A.
* **J (Same assertion A1 represented by alternate serialization M2)**: N/A.
* **K (Observation O1 represented by material M3)**: `SCHEMA_INVALID`.
* **L (Unsupported artifact with M4)**: `SCHEMA_INVALID` (Unsupported artifacts do not use material identity).
* **M (Provenance artifact with M5)**: `SCHEMA_INVALID`.

## 23. 2076 Archivist Test
The archivist can distinguish an immutable material artifact from its current representation digest and contextual transport role. They know that a differing logical role between two packages does not imply a new historical artifact. They know that shared bytes across entries represent distinct artifacts.

## 24. Surviving Assumptions
Manifest-local references are for intra-manifest array addressing (for non-portable artifacts). No package identity. No export-event identity. One `portableMaterialIdentity` appears at most once per manifest.

## 25. Unresolved Dependencies
Path canonicalization/Unicode semantics, precise role vocabulary.

## 26. Primary Recommendation
**MODEL M3 (Immutable entry-bound material identity)**. Separate intrinsic material identity (bytes + entry binding) from contextual manifest bindings (role + media type). Restrict `portableMaterialIdentity` exclusively to entry material.

## 27. Secondary Alternative
MODEL M1 (Immutable bytes identity) + S2 (Shared material). Rejected due to ambiguous ownership and historical authority.

## 28. Rejected Models
M1, M2, M4, M5. S2, S3.

## 29. Required Canonical Corrections
Update `PORTABLE_IDENTIFIER_NAMESPACE_AND_MATERIAL_OCCURRENCE_CLOSURE.md` and related docs to remove role and media type from material identity conflict rules, and to explicitly restrict portable material identity to entry material.

## 30. Normative-Contract Unblock Status
`PARTIALLY_UNBLOCKED`

## 31. Final Architecture Classification
**IMMUTABLE_MATERIAL_CONTEXTUAL_BINDING_DECISION_READY**
