# Merge Authority for Tombstone/Live Material Conflicts Investigation

## 1. Scope
Determine Vitalicast merge resolution behavior when two archive sources contain conflicting availability states (canonical minimal tombstone vs. live entry material) for the same `portableEntryIdentity`. Preserve User Sovereignty and sanctity of failure without silent resurrection or destruction.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `b9f2e21`

## 3. Accepted Prerequisite Decisions
* `MANIFEST_HISTORICAL_AUTHORITY_DECISION_READY`
* `PACKAGE_IDENTITY_NOT_REQUIRED_DECISION_READY`
* `PACKAGE_DIGEST_IDENTITY_PRECISION_CLOSED`
* `PACKAGE_DIGEST_SCOPE_CANONICALIZATION_DECISION_READY`
* `MANIFEST_CANONICALIZATION_DIGEST_ANCHOR_DECISION_READY`
* `COMPARISON_ONLY_MANIFEST_DIGEST_AUTHORITY_CLOSED`
* `PACKAGE_MANIFEST_SEMANTIC_SCHEMA_DECISION_READY`
* `MANIFEST_ARTIFACT_REFERENCE_MULTIPLICITY_DECISION_READY`
* `TOMBSTONE_MINIMAL_STATE_ASSERTION_IDENTITY_DECISION_READY`

## 4. Availability-State Concepts
*   **A. Live entry material**: Available material for a portable entry identity. Source-local.
*   **B. Canonical minimal tombstone state**: Unavailable-state projection. Source-local.
*   **C. Disposition assertion**: Historical assertion of disposition. Historical truth, not automatically inferred.
*   **D. Relationship assertion**: Reference to portable entry identity.
*   **E. Availability conflict**: Two valid sources make incompatible claims (tombstone vs live).
*   **F. Merge resolution**: Explicit decision resolving the conflict.

## 5. Merge Authority Models
*   **MODEL M1 (Live material wins)**: Rejected. Silently resurrects material previously disposed by the user in one custody scope, violating Two-Scope User Sovereignty.
*   **MODEL M2 (Tombstone wins)**: Rejected. Silently destroys incoming valid live material based on a separate custody's disposition, inventing global authority.
*   **MODEL M3 (Source-priority wins)**: Rejected. Risks silent destruction/resurrection and lacks strict evidence audibility.
*   **MODEL M4 (Conflict-preserving merge)**: **SELECTED**. Merged archive preserves both source states as an unresolved availability conflict artifact. Neither state automatically wins. Aligns perfectly with Sanctity of Failure and prevents silent rewriting.
*   **MODEL M5 (Block automatic merge)**: Rejected. Merges may run unattended; blocking outright prevents partial imports of unrelated non-conflicting material.
*   **MODEL M6 (Custody-branch model)**: Rejected. Introduces highly complex git-like branch ledgers unnecessary for flat manifest archives.
*   **MODEL M7 (Import-as-provenance only)**: Rejected. Evades true merge and breaks expected availability for non-conflicting components.

## 6. No Silent Resurrection Rule
Replacing a tombstone with live material without recording a conflict or requiring explicit user/operator resolution constitutes silent resurrection.
*   **Permitted**: Preserving live material alongside the tombstone as unresolved conflict evidence, quarantining the import, and later restoring availability only via an explicit user-authorized resolution assertion.

## 7. No Silent Destruction Rule
Replacing live material with a tombstone (or deleting live material) without recording a conflict constitutes silent destruction.
*   **Permitted**: Preserving the incoming tombstone as unresolved conflict evidence, marking the conflict status, and requiring explicit user resolution before dropping live material.

## 8. Conflict Artifact Evaluation
**MODEL C4 (Assertion-like Artifact)** is selected.
The Availability Conflict is modeled as a preserved assertion artifact with its own globally portable `assertionIdentity`. It explicitly records that Source A supplied tombstone state and Source B supplied live material for `E1`. It avoids a global hidden ledger by remaining scoped to the entries it affects.

## 9. Active State Semantics
During an unresolved conflict, the active archive state for `E1` becomes **unresolved/conflicted**. It is not treated as fully available, nor is it treated as fully disposed.

## 10. Relationship Resolution During Conflict
Existing relationships referencing `E1` resolve to the **conflict state**. They are blocked from blindly accessing the live material (preventing silent resurrection) and blocked from assuming permanent unavailability (preventing silent destruction). The relationships themselves are not rewritten.

## 11. Conflict Resolution Assertion
When a user/operator resolves the conflict, the resolution is recorded as a **new assertion artifact** with its own `assertionIdentity`.
*   It explicitly references the conflict artifact.
*   The user may choose to: accept live material, retain tombstone, or preserve both as provenance.
*   This ensures the resolution history is verifiable and does not silently overwrite the conflict history.

## 12. Import Scenarios
*   **A. (No E1 -> Live E1)**: Automatic import allowed. Active state = Live.
*   **B. (No E1 -> Tombstone E1)**: Automatic import allowed. Active state = Tombstone.
*   **C. (Tombstone -> Identical Tombstone)**: Automatic import allowed. Active state = Tombstone (collapsed).
*   **D. (Live -> Identical Live)**: Automatic import allowed. Active state = Live (collapsed).
*   **E. (Live -> Different Live)**: Conflict generated. Active state = Conflicted (Data conflict).
*   **F. (Tombstone -> Live)**: Conflict generated. Active state = Conflicted (Availability conflict).
*   **G. (Live -> Tombstone)**: Conflict generated. Active state = Conflicted (Availability conflict).
*   **H. (Conflict -> Live)**: Conflict updated/persists. Requires user resolution.
*   **I. (Conflict -> Tombstone)**: Conflict updated/persists. Requires user resolution.

## 13. Clone Scenarios
Cloning an archive preserves exactly the state present (live, tombstone, conflict, or resolved) without creating new disposition or resolution events.

## 14. Merge Scenarios
*   **A. (Live + Identical Live)**: Merges to Live.
*   **B. (Live + Different Live)**: Conflict.
*   **C. (Tombstone + Identical Tombstone)**: Merges to Tombstone.
*   **D. (Tombstone V1 + Tombstone V2)**: Merges to Tombstone (structural preservation).
*   **E. (Live + Tombstone)**: Conflict.
*   **F. (Tombstone + Live)**: Conflict.
*   **G. (Conflict + Live)**: Conflict.
*   **H. (Conflict + Tombstone)**: Conflict.
*   **I. (Resolved Live + Tombstone)**: Conflict (incoming tombstone challenges prior resolution unless tombstone predates resolution).
*   **J. (Resolved Tombstone + Live)**: Conflict (incoming live challenges prior resolution).

## 15. Disposition After Conflict
If `E1` is in an unresolved conflict state and the user requests destruction:
*   Live material is destroyed.
*   Tombstone remains.
*   Conflict artifact is superseded by a new disposition assertion.
*   User Sovereignty successfully overrides the unresolved conflict.

## 16. Export After Conflict
An export of an archive containing an unresolved conflict includes both the live material (quarantined/conflicted), the tombstone state, and the conflict assertion artifact. The package manifest accurately reflects the unresolved conflict without implying a resolution or inventing package lineage.

## 17. Privacy/Metadata Leakage Test
Preserving conflict evidence leaks the fact that a divergence occurred across custody scopes. However, this is strictly necessary to prevent silent data loss or silent resurrection, maintaining the integrity of the archive. The user retains sovereignty to explicitly resolve the conflict and subsequently dispose of the evidence if authorized by policy.

## 18. 50-Year Archivist Test
The archivist looking at a merged archive with an unresolved conflict artifact can honestly infer:
*   E1 was available in at least one source.
*   E1 was unavailable in at least one source.
*   Merge did not automatically resolve the conflict.
*   Current active state is unresolved.
They *cannot* infer which source is globally authoritative or whether a malicious action occurred. Honest uncertainty is preserved.

## 19. Surviving Assumptions
Manifest is a transport artifact. The Two-Scope disposition policy is maintained. Historical authority remains delegated. Sanctity of failure applies to merges.

## 20. Unresolved Dependencies
None identified in this narrow scope.

## 21. Primary Recommendation
**MODEL M4 (Conflict-preserving merge)** + **MODEL C4 (Assertion-like Conflict Artifact)**. Vitalicast must preserve conflicting live material and tombstone states as an unresolved availability conflict. Active state becomes conflicted. Relationships resolve to the conflict state. Resolution requires an explicit user-authorized resolution assertion artifact.

## 22. Secondary Alternative
Model M5 (Block automatic merge). (Rejected due to degrading import usability for non-conflicting components).

## 23. Rejected Models
Models M1, M2, M3, M5, M6, M7.

## 24. Required Canonical Corrections
*   Update `TOMBSTONE_MINIMAL_STATE_AND_ASSERTION_IDENTITY_INVESTIGATION.md` to resolve the previously unaddressed merge conflict dependency.
*   Update `BETA_3_TRUST_ARCHITECTURE.md` and `BETA_3_IMPLEMENTATION_PLAN.md` with conflict preservation rules.

## 25. Implementation Consequences
Merge and import logic must be capable of generating conflict artifacts and quarantining live material rather than destructively overwriting state.

## 26. Final Architecture Classification
**MERGE_TOMBSTONE_LIVE_CONFLICT_DECISION_READY**
