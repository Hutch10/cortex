# Comparison-Only Manifest Digest Authority Closure

## 1. Scope
Resolve exactly what a Comparison-Only digest (Model A4) can verify across four specific observation contexts. Resolve duplicate schema validity, same-key conflict semantics, and unmanifested material physical-presence authority. Correct overclaiming terminology ("prevents undetectable modifications") to reflect true comparison-only boundaries.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `26e249b`
* **Prior Decision**: `MANIFEST_CANONICALIZATION_DIGEST_ANCHOR_DECISION_READY`. Model C2 + A4 (Comparison-Only) was selected.

## 3. Prior Decision Under Review
Model C2 + A4 is provisionally accepted. The extent to which Model A4 "prevents" modifications and the exact treatment of duplicates and unmanifested files require precision closure.

## 4. Digest Observation Contexts A–D
*   **Context A (One observed manifest)**: Vitalicast computes the canonical digest. No expected digest exists.
*   **Context B (Two observed manifests)**: Vitalicast computes and compares digests for M1 and M2.
*   **Context C (Observed manifest + expected digest assertion)**: Vitalicast compares the computed digest against a previously asserted expected digest value.
*   **Context D (External provenance cites digest)**: An external record asserts that a source export produced a specific digest.

## 5. Comparison-Only Authority Matrix
| Claim | Context A (One) | Context B (Two) | Context C (Expected) | Context D (External) |
| :--- | :--- | :--- | :--- | :--- |
| Schema Validity | `INTERNALLY_VERIFIABLE` | `INTERNALLY_VERIFIABLE` | `INTERNALLY_VERIFIABLE` | `UNSUPPORTED` |
| Canonicalizability | `INTERNALLY_VERIFIABLE` | `INTERNALLY_VERIFIABLE` | `INTERNALLY_VERIFIABLE` | `UNSUPPORTED` |
| Digest Value | `INTERNALLY_VERIFIABLE` | `INTERNALLY_VERIFIABLE` | `INTERNALLY_VERIFIABLE` | `UNSUPPORTED` |
| Equality with Other | `UNSUPPORTED` | `PROVABLE` | `UNSUPPORTED` | `UNSUPPORTED` |
| Differs from Other | `UNSUPPORTED` | `PROVABLE` | `UNSUPPORTED` | `UNSUPPORTED` |
| Matches Expected | `UNSUPPORTED` | `UNSUPPORTED` | `CONDITIONALLY_VERIFIABLE` (Bounded by assertion) | `CONDITIONALLY_VERIFIABLE` |
| Historical Unchangedness | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` (Only verifies it matches assertion) | `UNKNOWN` |
| Originality/Authenticity | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| Path/Role Intactness | `UNKNOWN` | `PROVABLE` (If diff) | `CONDITIONALLY_VERIFIABLE` (Against expected) | `UNKNOWN` |
| Current Consistency | `INTERNALLY_VERIFIABLE` | `INTERNALLY_VERIFIABLE` | `INTERNALLY_VERIFIABLE` | `UNSUPPORTED` |

## 6. Current Consistency vs Historical Integrity
*   **Current Consistency**: `INTERNALLY_VERIFIABLE` via Context A. Ensures observed materials match the manifest's current bindings.
*   **Historical Integrity**: `UNKNOWN` in Context A. Requires a preserved expected digest (Context C) or prior manifest (Context B).

## 7. Path-Binding and Role-Binding Challenge
An attacker modifying a path/role and moving the material to match creates a package that is **currently consistent** (Context A passes). The canonical digest will differ, but without a comparison reference, Context A does not detect the historical modification. A Comparison-Only digest does NOT independently "prevent undetectable modifications"; it "makes modifications detectable upon comparison."

## 8. Adversarial A–N Re-Audit
*   **A. Replace file**: `CURRENTLY_INCONSISTENT` (Context A).
*   **B. Swap paths**: `CURRENTLY_INCONSISTENT` (Context A).
*   **C. Modify manifest paths & move material**: `CANONICAL_CONTENT_DIFFERS` (Context B), `EXPECTED_DIGEST_MISMATCH` (Context C). `NOT_DETECTED_AS_HISTORICAL_CHANGE` (Context A).
*   **Role-binding modification & move material**: `CANONICAL_CONTENT_DIFFERS` (Context B), `EXPECTED_DIGEST_MISMATCH` (Context C). `NOT_DETECTED_AS_HISTORICAL_CHANGE` (Context A).
*   **E. Add unmanifested material**: `NOT_DETECTED_AS_HISTORICAL_CHANGE` (Context A). Excluded from import.
*   **H. Reorder records**: `SEMANTICALLY_EQUIVALENT` (All contexts).
*   **I. Duplicate inventory record**: `DETECTED` (Context A: Schema invalid).

## 9. Duplicate/Cardinality Models
*   **MODEL D1 — Schema rejection**: Selected. Fails validation, preserving evidence of malformed structure.
*   **MODEL D2 — Silent deduplication**: Rejected. Destroys failure evidence.
*   **MODEL D3 — Preserve as multiset**: Rejected.

## 10. Duplicate Rule
Canonicalization schema validation MUST fail verification as invalid schema upon encountering any duplicate logical-set record. Silent deduplication is strictly prohibited to preserve sanctity of failure.

## 11. Same-Key Conflict Semantics
Two records claiming the identical semantic uniqueness key but bearing different fields (e.g. different digests) are a CONFLICT and SCHEMA-INVALID. Multi-representation material (e.g. primary vs thumbnail) must utilize distinct logical roles.

## 12. Semantic Uniqueness Keys
Every logical-set collection must define a composite semantic uniqueness key (e.g., `portableEntryIdentity` + `logicalRole` for material records).

## 13. Unmanifested Material Authority
Physical presence of unmanifested artifacts confers NO manifest authority, NO entry binding, NO relationship authority, and NO evidence grading. It must NOT authorize automatic import. Such material is strictly ignored or explicitly quarantined.

## 14. Malicious Extra-Material Test
An unmanifested extra file falsely claiming a valid `portableEntryIdentity` does not override or compete with the manifest-authorized entry. Import logic MUST be inventory-driven (scanning based on manifest claims) rather than blindly path-driven.

## 15. Preservation-Grade Authority
The manifest itself provides Grade A context. The Vitalicast-generated digest calculation is a mechanical observation. A failed verification result is preserved historically under sanctity of failure. Contextual assertions do not transcend their source grade simply by being digested.

## 16. 2076 Archivist Test
*   **Single package**: Can prove current consistency, canonicalizability, and schema validity.
*   **Comparison package**: Can prove canonical content equality/difference.
*   **Expected digest**: Can verify equality against the assertion, constrained by the assertion's own authority grade.
*   **Authenticity/Originality**: Remains completely `UNKNOWN` without an external authenticated signature framework.

## 17. Surviving Assumptions
Comparison-only digests establish canonical equality, not absolute historical immutability. Internal consistency remains the trust boundary.

## 18. Unresolved Dependencies
None.

## 19. Required Canonical Corrections
Updated `BETA_3_IMPLEMENTATION_PLAN.md` to state the canonical digest makes path/role modifications "detectable upon comparison" rather than "preventing undetectable" modifications. Updated duplicate/unmanifested rules in `MANIFEST_CANONICALIZATION_AND_DIGEST_ANCHOR_INVESTIGATION.md`.

## 20. Final Precision Classification
**COMPARISON_ONLY_MANIFEST_DIGEST_AUTHORITY_CLOSED**
