# Availability Conflict Observation and Resolution Authority Closure

## 1. Scope
Determine whether a tombstone/live availability conflict is a derived state, a deterministic observation, or an authored assertion. Define conflict portability, uniqueness, and resolution semantics. Eliminate ambiguous vocabulary such as "superseded" and generic "preserve both as provenance".

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `cf60196`

## 3. Prior Merge Decision Under Review
*   `MERGE_AUTHORITY_TOMBSTONE_LIVE_CONFLICT_INVESTIGATION.md` (Decision: Model M4 conflict-preserving merge + Model C4 assertion-like artifact).

## 4. Source State Definition
**Admitted source state** (e.g., valid live entry material, canonical minimal tombstone) is the raw material/state contributed by a source. It is NOT an authored assertion artifact. Live material is simply the material itself; the tombstone is a minimal subject state projection.

## 5. Availability Incompatibility Definition
**Availability incompatibility** is a deterministic, derived fact under the versioned merge contract: valid live state and canonical minimal tombstone state cannot simultaneously occupy one resolved active availability slot for a portable entry identity.

## 6. Conflict Semantic Models
*   **MODEL C1 (Derived state only)**: Rejected. Loses evidence if one source is later removed.
*   **MODEL C2 (Preserved observation artifact)**: Evaluated. Captures deterministic nature.
*   **MODEL C3 (Generic assertion artifact)**: Evaluated (provisional direction). May inaccurately imply historical authorship.
*   **MODEL C4 (Conflict state plus observation artifact)**: **SELECTED**. `CONFLICTED` is the derived active state. A distinct preserved observation artifact records that the incompatible source states were encountered. Resolution changes the active-state interpretation without erasing the observation.
*   **MODEL C5 (Merge/import result only)**: Rejected. Lacks portability.

## 7. Selected Conflict Model
**MODEL C4**. A conflict observation artifact preserves the fact that incompatible admitted source states were observed together under a versioned merge contract. It does NOT assert which source is historically correct. `CONFLICTED` is the derived active availability state resulting from this unresolved observation.

## 8. Generic Assertion Identity Re-evaluation
A conflict observation is a deterministic record, not an authored historical claim (like a disposition or relationship assertion). However, because later resolution assertions must independently cite the conflict across boundaries, the conflict artifact requires a portable reference. We utilize a distinct portable observation identity, explicitly differentiating it from a generic authored assertion identity.

## 9. Conflict Portability
A portable conflict reference is REQUIRED because a resolution assertion may be created after import, or across archive/package boundaries, and must reliably identify the specific divergence being resolved.

## 10. Conflict Equivalence and Uniqueness
Conflict semantic equivalence is defined by the `portableEntryIdentity` and the core conflicting states (the minimal tombstone state and the live material representation, specifically identified by its `portableMaterialIdentity`). However, to prevent a hidden merge-event ledger, repeated observations of the identically same unresolved source states for the same entry do NOT automatically create new historical conflict artifacts. 

## 11. Repeated Conflict Observation Rule
Evaluating identical unresolved source states repeatedly simply verifies the existing conflict observation. It does not generate new multiplicity. A new conflict artifact is only justified if new, distinct live material conflicts with the tombstone.

## 12. Conflict Authority Matrix
| Field | Authority |
| :--- | :--- |
| portableEntryIdentity | `REQUIRED` |
| portableMaterialIdentity observed | `REQUIRED` |
| representation digest observed | `REQUIRED` |
| tombstone subject state observed | `REQUIRED` |
| merge contract identifier/version | `OPTIONAL` |
| which source is historically correct | `PROHIBITED` |
| source archive/package identity | `PROHIBITED` |
| merge time | `PROHIBITED` |
| merge actor / operation identity | `PROHIBITED` |
| that disposition/resurrection occurred | `OUTSIDE_CONFLICT_AUTHORITY` |

## 13. Derived Conflict State
`CONFLICTED` is a **derived active availability state**. It is recomputed from the presence of the unresolved conflict observation and the admitted source materials. It is not an assertion artifact itself, nor a historical truth, but the archive's current operational status for that entry.

## 14. Resolution Semantics
A resolution assertion resolves the conflict strictly for *active-state purposes*. It does NOT delete, rewrite, or erase the historical conflict observation. The observation remains historically accurate (the conflict *did* happen).

## 15. Allowed Supersession/Resolution Vocabulary
*   **ALLOWED**: `resolved`, `inactive`.
*   **PROHIBITED**: `superseded`, `replaced`, `removed`, `overwritten` (when discussing the conflict observation artifact in relation to resolution).

## 16. Disposition-After-Conflict Test
If a user explicitly requests disposition of conflicted live material, this requires TWO distinct semantic operations:
1.  **Resolution Assertion**: Resolves the active state to the tombstone (making the conflict observation inactive).
2.  **Disposition Assertion**: Records the historical fact of the user's new disposition action.
These are distinct. Do not duplicate unnecessarily, but do not collapse disposition truth and conflict-resolution authority.

## 17. Accept-Live Resolution Test
Accepting live material creates a resolution assertion. The tombstone is no longer the active state, but the fact that a tombstone existed (and conflicted) remains verifiable via the inactive conflict observation. This respects User Sovereignty without silently falsifying the prior tombstone's existence.

## 18. Preserve-Both-As-Provenance Test
The prior generic option "preserve both as provenance" is insufficiently defined, as "provenance" cannot be a downgrade state for active material or tombstones. This option is REMOVED from the accepted explicit resolution choices. If the user wishes to take no action, the state simply remains `CONFLICTED` (unresolved).

## 19. Import/Merge Scenario Re-Audit
Scenarios A-J remain structurally identical to the previous investigation, but with clarified vocabulary: "conflict generated" means the deterministic derivation of `CONFLICTED` state AND the creation/verification of the conflict observation artifact.

## 20. Export Semantics
Package export inventories the live material, the tombstone state, and the conflict observation artifact (and resolution assertion, if present). The derived `CONFLICTED` active state is reconstructed by the importing system; it is not a duplicated authoritative artifact in the manifest.

## 21. Manifest Semantic-Schema Treatment
The availability conflict observation MUST be inventoried if it is part of the package payload. It uses a portable observation identity. It is not a generic historical assertion.

## 22. Privacy/Hidden-Ledger Test
Identical repeated conflict observations collapse/reuse the existing artifact. Merge timestamps, source package identities, and source archive identities are PROHIBITED in the conflict observation. This prevents the conflict artifact from becoming a hidden event ledger while preserving the necessary evidence of divergence.

## 23. 2076 Archivist Test
The archivist can honestly infer that incompatible states were observed for E1 and that the active state was conflicted (or resolved by user R1). They CANNOT infer merge times, source archives, or hidden custody history. Honest uncertainty is preserved.

## 24. Surviving Assumptions
Manifest is a transport artifact. The Two-Scope disposition policy is maintained. Sanctity of failure applies to merges.

## 25. Unresolved Dependencies
None.

## 26. Required Canonical Corrections
*   Update `MERGE_AUTHORITY_TOMBSTONE_LIVE_CONFLICT_INVESTIGATION.md` to clarify vocabulary (`inactive`/`resolved` instead of `superseded`) and remove the "preserve as provenance" resolution option.
*   Update `PACKAGE_MANIFEST_SEMANTIC_SCHEMA_INVESTIGATION.md` to define the conflict observation identity separate from generic assertions.
*   Update `BETA_3_TRUST_ARCHITECTURE.md` and `BETA_3_IMPLEMENTATION_PLAN.md` with the refined observation vs. assertion semantics.

## 27. Final Precision Classification
**AVAILABILITY_CONFLICT_OBSERVATION_AUTHORITY_CLOSED**
