# Manifest Canonicalization Semantics and Digest Anchor Investigation

## 1. Scope
Determine exactly how semantically unordered manifest inventory collections are normalized before canonical serialization. Define whether manifest arrays are semantically ordered, how duplicates and cardinality are preserved, what exact artifact preserves the expected canonical manifest digest (the anchor problem), how self-reference is avoided, what authority the anchor possesses, and what a 50-year archivist can honestly prove.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `8cc3ae5`
* **Prior Digest Decision**: `PACKAGE_DIGEST_SCOPE_CANONICALIZATION_DECISION_READY`. Canonical manifest digest is required. Per-material digests are required. Physical ZIP digest is optional transport only. Merkle root rejected.

## 3. Prior Digest Decision Under Review
The requirement for a canonical manifest digest remains accepted. The details of how to sort unordered arrays before hashing and where the canonical digest is preserved (the anchor) are under review.

## 4. Residual Overclaim Audit
* **"exact copy yields equal digest usually"**: Corrected to `DIGEST_MUST_EQUAL`. A true byte-for-byte exact copy under the same digest algorithm and input scope MUST produce equal digest output.
* **"absolute physical integrity"**: `AUTHORITY_OVERCLAIM`. Corrected to: "verifiable representation equality, internal digest consistency, and comparison against preserved expected digest assertions." Hashes do not independently establish historical originality, authenticity, ancestry, or continuous custody.

## 5. Manifest Semantic Structure
*   **Package inventory records**: `SEMANTICALLY_UNORDERED`. (Set).
*   **Archive entry material records**: `SEMANTICALLY_UNORDERED`. (Set).
*   **Relationship artifact records**: `SEMANTICALLY_UNORDERED`. (Set).
*   **Tombstone records**: `SEMANTICALLY_UNORDERED`. (Set).
*   **Integrity attestation records**: `SEMANTICALLY_UNORDERED`. (Set).
*   **Unsupported future artifact records**: `SEMANTICALLY_UNORDERED`. (Set).
*   **Algorithm attestations**: `SEMANTICALLY_UNORDERED`. (Set).
*   **Provenance records**: `SEMANTICALLY_UNORDERED`. (Set).
*   **Warning/failure records**: `SEMANTICALLY_UNORDERED`. (Set).

## 6. Collection Ordering Taxonomy
Inventory arrays are conceptually sets. The JSON array ordering possesses NO semantic authority. Normalization into a stable total order is required before calculating the canonical manifest digest.

## 7. Duplicate/Cardinality Semantics
Duplicates are prohibited within these logical sets. Canonicalization schema validation must deduplicate strictly byte-identical records or fail verification as invalid schema. Cardinality has no independent semantic meaning beyond the presence of the unique records.

## 8. Canonicalization Models
*   **MODEL C1 — Raw RFC 8785 / JCS only**: Insufficient. JCS sorts keys but preserves array ordering. Semantically unordered arrays would hash differently based on arbitrary JSON array emission order.
*   **MODEL C2 — Schema-normalized manifest projection followed by JCS**: Selected. Unordered collections are sorted into a schema-defined total order before applying JCS.
*   **MODEL C3 — Canonical inventory projection only**: Rejected. Omits critical export metadata.
*   **MODEL C4 — Record-level canonical digests plus sorted digest list**: Rejected. Unnecessary complexity compared to C2.
*   **MODEL C5 — No canonical manifest digest**: Rejected. Allows undetectable modification of paths, roles, and bindings.

## 9. Stable Total-Order Decision
Semantically unordered collections are sorted into a stable total order defined by the canonical record serialization string (the JCS serialization of the individual record object). Because records do not contain the collection they reside in, this sort resolves deterministically without recursion.

## 10. Unknown Future Field Behavior
Unknown fields are preserved. Unknown array orderings (e.g. from future schemas) cannot be safely sorted without the canonicalization contract for that schema version. A verifier missing the contract cannot verify the manifest. It is classified as `UNSUPPORTED`, not `CORRUPT`. Fail closed on verification; preserve the data.

## 11. Canonicalization Contract Reference
The canonicalization contract identifier (e.g., `vitalicast.manifest-c14n.v1`) is a versioned specification reference, not an entity identity. It defines the exact schema projection and normalization rules.

## 12. Observed vs Expected Digest Distinction
*   **Observed manifest digest**: The digest computed now from the observed manifest under contract C.
*   **Expected manifest digest**: A digest value previously asserted for that manifest content under contract C.
Verification strictly means comparing `observedDigest == expectedDigest`.

## 13. Manifest Digest Anchor Problem
Where does the `expectedDigest` for the manifest reside? If inside the manifest, it hashes itself (circular authority/self-reference). If outside, it requires a detached integrity envelope, which itself needs an anchor (infinite regress).

## 14. Anchor Models
*   **MODEL A1 — Inside manifest but excluded**: Rejected. Modifying the excluded field breaks the expected digest.
*   **MODEL A2 — Detached integrity attestation**: Rejected. Creates infinite regress without PKI.
*   **MODEL A4 — Manifest digest is comparison-only, not self-verifying**: Selected. The canonical manifest digest is not anchored internally. It establishes canonical equality when comparing two manifests, or when verified against an external transport checksum/provenance assertion.

## 15. Integrity Regress/Trust Boundary
The trust boundary is **Internal Consistency Only**. Vitalicast's architecture verifies that material files match the manifest's listed per-material digests (internal consistency). Authenticated origin, signatures, and external timestamping are explicitly out of scope. We do not invent PKI to solve infinite regress.

## 16. Preservation-Grade Authority
*   **Manifest inventory records**: Grade A.
*   **Material representation digest assertions**: Grade A (part of inventory).
*   **Canonical manifest digest assertion**: N/A (Comparison-only, not asserted internally).
*   A Vitalicast-generated digest is an observation, mechanically deterministic, but bound by Vitalicast's contextual assertion that it represents specific entry material.

## 17. Adversarial Tests A–N Audit
*   **A. Replace file**: `DETECTED` (Per-material digest mismatch).
*   **B. Swap paths**: `DETECTED` (Role binding mismatch).
*   **C. Modify manifest paths**: `DETECTED` (Canonical digest comparison mismatch).
*   **E. Add unmanifested file**: Ignored (Internal manifest completeness holds; extra files are not part of the inventory).
*   **H. Reorder manifest inventory records**: `SEMANTICALLY_EQUIVALENT` (Sorted by C2 normalization, digest remains identical).
*   **I. Duplicate an inventory record**: Handled by C2 deduplication or schema rejection.
*   **L. Unknown future artifact**: `UNSUPPORTED`.
*   **M. Known algorithm with unknown canonicalization contract**: `UNSUPPORTED`.
*   **N. Conflicting attestations**: Both preserved under sanctity of failure.

## 18. Package Completeness vs Package Closure
*   **Internal manifest completeness**: Supported. Every manifest-required material record has a corresponding file.
*   **Package closure**: Unsupported. Unmanifested files (e.g., OS metadata, thumbnails, detached envelopes) are ignored.
*   **Historical archive completeness**: Unsupported.

## 19. 2076 Archivist Verification Test
The archivist can independently verify:
*   `INTERNALLY_VERIFIABLE`: Exact observed container bytes, material matches manifest expected digest, entry/material contextual binding, ancestry (via relationship artifacts).
*   `PROVABLE`: Equality with another preserved container, individual material representation equality, manifest canonical equality with another manifest.
*   `UNKNOWN`: Manifest matches a preserved expected canonical digest (unless provided externally), package closure relative to manifest, authentic Vitalicast origin, historical originality, export-event identity, package identity, archive historical completeness, custody continuity.

## 20. Surviving Assumptions
*   Digests do not provide entity identity.
*   Internal consistency is sufficient for Vitalicast's mission. Authenticity requires external context.

## 21. Unresolved Dependencies
None. Canonicalization semantics and anchor authority are now fully defined.

## 22. Primary Recommendation
**MODEL C2 + MODEL A4**: Schema-normalized manifest projection followed by JCS (Model C2) for the canonical manifest digest. The digest serves purely as a Comparison-Only metric (Model A4), eliminating self-reference and infinite regress without resorting to unsupported PKI.

## 23. Secondary Alternative
**MODEL C1**: Raw JCS only, requiring strict emission order without schema-level sorting (fragile).

## 24. Rejected Models
**MODEL A1, A2, A3, C3, C4, C5**. All introduce unnecessary complexity, circular dependencies, or integrity blindness.

## 25. Required Canonical Corrections
*   Narrow terminology corrections removing "absolute physical integrity" and correcting "exact copy yields equal digest usually" in `PACKAGE_DIGEST_SCOPE_AND_CANONICALIZATION_INVESTIGATION.md`.
*   Update `BETA_3_TRUST_ARCHITECTURE.md` to reflect internal consistency and Comparison-Only canonical manifest digest.

## 26. Implementation Consequences
Do not implement a self-referential manifest digest field. Sort all inventory arrays deterministically before JCS canonicalization. Fail verification gracefully as `UNSUPPORTED` on unknown schemas.

## 27. Final Architecture Classification
**MANIFEST_CANONICALIZATION_DIGEST_ANCHOR_DECISION_READY**
