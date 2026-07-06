# Package Digest Scope and Canonicalization Investigation

## 1. Scope
Determine exactly what material enters the package digest domain, the canonicalization contract, and what equality claims digest equality authorizes. Evaluate whether Vitalicast requires physical container digests, canonical manifest digests, per-material digests, Merkle roots, or combinations thereof. Resolve the precision overclaims that re-export, merge, clone, or reconstruction operations inherently yield distinct representation digests.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `1369bbc`
* **Prior Digest Precision**: `PACKAGE_DIGEST_IDENTITY_PRECISION_CLOSED`. Confirmed no package identity; digests prove representation/canonical equality only. Unresolved: Physical vs. Canonical digest scopes.

## 3. Prior Digest Authority Decisions
* Package identity is explicitly rejected (Model A).
* Digests establish only the equality claim authorized by their specific scope.
* Export-event identity is not tracked.
* Lineage belongs to entries and relationships, not packages.

## 4. Residual Distinct-Digest Precision Audit
The prior claim that re-export, clone, merge, and reconstruction operations inherently create new/distinct digests is an **AUTHORITY OVERCLAIM**. 
Operation distinctness alone does not force digest distinctness unless operation-specific metadata (timestamps, UUIDs) is intentionally injected into the digest domain.

*   1. exact copy: `DIGEST_MAY_EQUAL_OR_DIFFER` (Physical bytes usually equal).
*   2. independent byte-identical export: `DIGEST_MAY_EQUAL_OR_DIFFER` (Equal if timestamps/ordering are normalized).
*   3. same logical state re-export: `DIGEST_MAY_EQUAL_OR_DIFFER`.
*   4. metadata-only archive change: `DIGEST_MAY_EQUAL_OR_DIFFER`.
*   5. unreferenced entry disposition: `DIGEST_MUST_DIFFER`.
*   6. referenced entry disposition with tombstone: `DIGEST_MUST_DIFFER`.
*   7. relationship assertion addition: `DIGEST_MUST_DIFFER`.
*   8. integrity attestation addition: `DIGEST_MUST_DIFFER`.
*   9. partial export: `DIGEST_MUST_DIFFER`.
*   10. import then export: `DIGEST_MAY_EQUAL_OR_DIFFER`.
*   11. clone then export: `DIGEST_MAY_EQUAL_OR_DIFFER`.
*   12. merge then export: `DIGEST_MAY_EQUAL_OR_DIFFER`.
*   13. independent reconstruction from identical components: `DIGEST_MAY_EQUAL_OR_DIFFER`.

## 5. Digest Domain Taxonomy
*   **A. Physical representation digest**: Exact ZIP/container bytes as emitted. Highly sensitive to compression levels, file mtimes, and library implementation details.
*   **B. Manifest representation digest**: Exact serialized manifest bytes. Sensitive to whitespace, BOM, and key ordering.
*   **C. Canonical manifest digest**: Digest of manifest under an explicit canonicalization contract (e.g., deterministic key sort, no whitespace).
*   **D. Logical inventory digest**: Digest over a normalized inventory model, excluding irrelevant metadata.
*   **E. Per-material/file digest**: Digest of individually hashed files (entries, relationship files).
*   **F. Merkle/root digest**: Root hash derived from canonically ordered component hashes.
*   **G. Entry canonical digest**: Existing entry-level identity integrity mechanism.

## 6. Digest Assertion Matrix
| Assertion | YES / NO / DEPENDS |
| :--- | :--- |
| exact physical byte equality | **DEPENDS** (Physical representation digest) |
| manifest byte equality | **DEPENDS** (Manifest representation digest) |
| canonical manifest equality | **DEPENDS** (Canonical manifest digest) |
| same logical inventory | **DEPENDS** (Canonical manifest digest / Model D) |
| same archive entries | **DEPENDS** (Per-material digests / Manifest) |
| same entry content | **DEPENDS** (Entry per-material digest) |
| same relationships | **DEPENDS** (Relationship per-material digests) |
| same tombstones | **DEPENDS** (Manifest inventory of tombstones) |
| same integrity attestations | **DEPENDS** (Manifest inventory of attestations) |
| same export event | **NO** |
| same historical entity | **NO** |
| ancestry | **NO** (Only explicit relationships assert this) |
| custody | **NO** (Provenance asserts this) |
| provenance | **NO** (External provenance asserts this) |
| completeness | **DEPENDS** (Relative to Manifest inventory) |

## 7. Physical Container Digest Evaluation
Hashing exact emitted ZIP bytes (SHA-256 over ZIP) is fragile. It proves representation equality of the container, but creates false distinctions due to varying compression libraries, ZIP timestamps (mtime), or OS-specific file attributes. While useful for pure transport/download checksums, it fails the 50-year verifiability test as a primary logical identifier because the internal contents could be logically identical but physically distinct.

## 8. Manifest Representation Digest Evaluation
Hashing raw serialized JSON is fragile against JSON formatting differences (whitespace, indentation). It proves exact manifest serialization equality but not logical equality.

## 9. Canonical Manifest Digest Evaluation
Hashing a canonically serialized manifest (e.g., RFC 8785 JSON Canonicalization Scheme or a custom deterministic sorted-key serialization) provides a robust anchor. It proves canonical-content equality.

## 10. Logical Inventory Equivalence Evaluation
"Logical inventory equivalence" must be defined rigorously. 
*   **MODEL I2 — Inventory-bearing equality** is required. The same intentionally included material records exist. 
*   Model I1 (exact semantic equality) is too brittle against metadata changes. Model I5 (no generalized claim) is too weak.

## 11. Per-Material Digest Evaluation
Package manifests must act as an integrity map, binding `logicalRole` to a `representationDigest`. Per-material digests are strictly required. Without them, paths can be maliciously swapped or corrupted. The manifest must bind the file's representation digest to its portable entry identity and logical role.

## 12. Root/Merkle Necessity Evaluation
A Merkle root adds unnecessary cryptographic complexity. The self-reference problem (manifest containing a root that hashes the manifest) requires a detached integrity envelope. A simple canonical manifest digest combined with per-material digests listed within the manifest provides the exact same verifiable integrity without requiring a Merkle tree. 

## 13. Integrity Attestation Authority
*   Manifest inventory claims are **Grade A**.
*   A digest generated by Vitalicast is an **assertion**.
*   Failed verifications must be preserved historically (respecting the sanctity of failure).

## 14. Manifest Ordering Rule
Manifest array ordering carries **NO SEMANTIC MEANING**. To generate a Canonical Manifest Digest, inventory lists must be sorted deterministically (e.g., by logical role or portable identity) during the canonicalization pass.

## 15. Algorithm Migration
Digest algorithms must be explicitly identified (e.g., `sha256:` prefix). The original SHA-256 digest remains permanently preserved. New algorithms (e.g., SHA-3) in 2045 will be added as independent addendum attestations. One material can have multiple valid digest attestations over time.

## 16. Canonicalization Migration
If canonicalization contract C1 is replaced by C2, C1 remains authoritative for the artifacts it generated. C2 does not rewrite C1. The written contract for C1 must be portable enough to execute in 2076 independently.

## 17. Partial Export / Disposition Pressure Test
If P1 exports {E1, E2, E3}, and E1 is later fully disposed (unreferenced), P2 exporting {E2, E3} will have a new canonical manifest digest and new per-material digests array. P2 contains zero evidence of E1. The integrity architecture does not weaken Two-Scope disposition.

## 18. Unknown Future Material Test
In 2076, an unknown artifact type present in the manifest will still have a listed `representationDigest` and `logicalRole`. The archivist can verify physical byte integrity even if semantic parsing is impossible. It fails closed on parsing, but remains verifiable for transport/storage integrity.

## 19. Adversarial Integrity Tests
*   **A. Replace file**: Detected by per-material digest mismatch.
*   **B. Swap paths**: Detected by manifest role/digest binding mismatch.
*   **C. Modify manifest paths**: Detected by canonical manifest digest mismatch.
*   **D. Remove file**: Detected by missing file during manifest verification.
*   **E. Add unmanifested file**: Detected by file existing outside manifest scope (ignored or flagged).
*   **K. Recompress package**: Physical ZIP digest changes, Canonical Manifest Digest remains perfectly equal. Verification succeeds.

## 20. 50-Year Archivist Test
Without Vitalicast software, the archivist can:
*   Hash the raw files to verify per-material digests.
*   Apply the open canonicalization contract to the manifest to verify the canonical manifest digest.
*   Verify completeness relative to the manifest.
*   They CANNOT establish ancestry or entity identity via digests (they rely on Grade B/C relationships for ancestry).

## 21. Candidate Models
*   **MODEL C — Canonical manifest digest plus per-material digests**: Selected. Highly resilient to recompression, fully verifiable without a Merkle tree, naturally avoids self-reference if the container digest is separate.
*   **MODEL A, B, E, F**: Rejected as fragile, incomplete, or unnecessarily complex.

## 22. Surviving Assumptions
*   Digests do not provide entity identity.
*   Entry relationships authorize ancestry.

## 23. Unresolved Dependencies
*   The exact JSON Canonicalization Scheme (e.g., RFC 8785) is yet to be implemented.

## 24. Primary Recommendation
**MODEL C — Canonical manifest digest plus per-material digests**.
A package guarantees integrity through a deterministic Canonical Manifest Digest, which inventories the exact Per-Material Representation Digests for all included contents. The physical ZIP digest is relegated to an optional transport checksum, possessing no canonical authority.

## 25. Secondary Alternative
**MODEL F — Detached integrity envelope**.

## 26. Rejected Models
**MODEL A (Physical ZIP digest only)** — Rejected due to recompression and timestamp fragility.
**MODEL E (Merkle Root)** — Rejected due to unnecessary complexity and self-reference issues.

## 27. Implementation Consequences
Do not rely on the physical ZIP byte hash for any logical or historical verification. Ensure the package manifest includes a `representationDigest` for every material file.

## 28. Final Architecture Classification
**PACKAGE_DIGEST_SCOPE_CANONICALIZATION_DECISION_READY**

