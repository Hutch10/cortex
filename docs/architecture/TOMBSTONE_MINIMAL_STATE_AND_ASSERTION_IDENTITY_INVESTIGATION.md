# Tombstone Minimal State and Assertion Identity Investigation

## 1. Scope
Determine whether a Vitalicast tombstone is a historical assertion artifact or a canonical minimal absence-state artifact, resolving its uniqueness constraint. Determine whether assertion artifact identity and producing-event identity are distinct architecture domains to prevent unintended event-ontology creation.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `1a6bda6`

## 3. Accepted Prerequisite Decisions
* `MANIFEST_HISTORICAL_AUTHORITY_DECISION_READY`
* `PACKAGE_IDENTITY_NOT_REQUIRED_DECISION_READY`
* `PACKAGE_DIGEST_IDENTITY_PRECISION_CLOSED`
* `PACKAGE_DIGEST_SCOPE_CANONICALIZATION_DECISION_READY`
* `MANIFEST_CANONICALIZATION_DIGEST_ANCHOR_DECISION_READY`
* `COMPARISON_ONLY_MANIFEST_DIGEST_AUTHORITY_CLOSED`
* `PACKAGE_MANIFEST_SEMANTIC_SCHEMA_DECISION_READY`
* `MANIFEST_ARTIFACT_REFERENCE_MULTIPLICITY_DECISION_READY`

## 4. Competing Tombstone Models
*   **MODEL T1 (Historical Assertion Artifact)**: Rejected. Duplicates disposition assertion architecture and accumulates historical metadata.
*   **MODEL T2 (Canonical Minimal Absence-State Artifact)**: Selected. A tombstone is the minimum surviving representation for a referenced but unavailable portable entry. It occupies one semantic slot (`portableEntryIdentity`) and does not represent the disposition event.
*   **MODEL T3 (Derived Relationship Repair Artifact)**: Rejected. Leaks relationship counts and creates duplicate tombstones.
*   **MODEL T4 (Current-State Pointer)**: Rejected. Acts as a mini-ledger linking to historical assertions.
*   **MODEL T5 (No Tombstone)**: Rejected. Violates accepted Two-Scope disposition policy.

## 5. Selected Tombstone Model
**MODEL T2**. A tombstone is not a disposition-event assertion. It is the canonical minimal surviving subject state for a referenced but unavailable portable entry. It occupies exactly one semantic slot per portable entry and has no independent historical-event identity.

## 6. Tombstone Authority Matrix
| Claim | Authority |
| :--- | :--- |
| portableEntryIdentity of unavailable subject | `REQUIRED` |
| Referenced source material is unavailable | `REQUIRED` |
| Source material was disposed | `OUTSIDE_TOMBSTONE_AUTHORITY` |
| Disposition reason | `PROHIBITED` |
| Disposition time | `PROHIBITED` |
| Disposition actor | `PROHIBITED` |
| Destruction method | `PROHIBITED` |
| Prior content digest | `PROHIBITED` |
| Prior file path | `PROHIBITED` |
| Prior storage key | `PROHIBITED` |
| Prior package digest | `PROHIBITED` |
| Disposition assertion identity | `PROHIBITED` |
| Relationship identities requiring tombstone | `PROHIBITED` |
| Number of prior references | `PROHIBITED` |
| Prior preservation grade | `PROHIBITED` |
| Prior metadata | `PROHIBITED` |
| Original creation time | `PROHIBITED` |

## 7. Unavailable vs Disposed Semantics
A tombstone simply means: *material is unavailable to this archive/package*. It does NOT inherently mean material was affirmatively disposed under a known disposition event. Tombstone presence alone does not prove why or when material became unavailable (e.g., loss, corruption, imported relationship without material). "Unavailable" does not silently mean "destroyed."

## 8. Two-Scope Disposition Re-Test
*   **Case A (Unreferenced entry E1 disposed)**: No tombstone remains. No manifest record remains. No portable identity evidence remains. Disposition assertions may remain if authorized by policy. Full User Sovereignty is preserved.
*   **Case B (Referenced entry E2 disposed)**: One canonical minimal tombstone state remains for E2. Historical disposition assertions are optional (based on retention policy). Later relationships may safely reference E2 without modifying or duplicating the tombstone. The tombstone does not grow or change based on reference count.

## 9. Tombstone Multiplicity
One entry has exactly **one** minimal tombstone state. Multiple tombstone artifacts concerning one portable entry are NOT valid.

## 10. Tombstone Canonicality
A tombstone possesses a canonical semantic representation based solely on the `portableEntryIdentity` and the tombstone schema version. Availability-state tokens or structural wrappers may exist, but reason codes, timestamps, and unknown extension fields are strictly prohibited from entering the tombstone canonical state to prevent canonical semantic drift. A tombstone receives no preservation grade and its canonical digest is an artifact digest, not an entry digest.

## 11. Import Semantics
Importing a valid tombstone for E1 does not infer a historical disposition event. Identical semantic tombstones collapse as state. Differing tombstone schema versions are preserved without interpretation, but do not create conflicting states of unavailability.

## 12. Clone Semantics
Cloning an archive copies the portable entry subject state (the tombstone). It does not create a new disposition assertion or infer a new disposition event.

## 13. Merge Semantics
*   **Tombstone vs Identical Tombstone**: Collapses to one state.
*   **Tombstone vs Differing Schema Version**: Coexistence of structural representation, identical semantic state.
*   **Tombstone vs Disposition/Relationship Assertions**: Assertions merge normally as distinct artifacts; tombstone state remains minimal.
*   **Tombstone vs Live Grade A Material**: *UNRESOLVED*. What happens when one archive has a tombstone and another has live entry material for the same portable entry identity reveals a separate merge-authority prerequisite. This architecture explicitly leaves this conflict resolution unresolved rather than silently resurrecting disposed material or destroying available material.

## 14. Relationship Behavior
Relationships continue to reference the `portableEntryIdentity`. They do not reference a tombstone identity. The tombstone does not list relationships, know why it exists, or leak relationship counts.

## 15. Disposition Assertion Identity
*   **Disposition subject**: `portableEntryIdentity` E1.
*   **Disposition assertion artifact**: A detailed historical event record detailing disposition reasons and times.
*   **Disposition assertion identity**: The portable identity of that preserved assertion artifact.
*   **Producing operation/event**: The real-world system operation that caused removal.
Disposition assertion artifacts require an independent portable `assertionIdentity`.

## 16. Disposition Event vs Assertion Identity
`disposition assertion identity != disposition event identity`. A portable assertion identity identifies one preserved assertion/claim instance, not the event itself. One event could hypothetically produce multiple serialized assertions or lack a preserved assertion entirely. Vitalicast does NOT require event identity in the manifest architecture.

## 17. Integrity Attestation Assertion vs Verification Event
*   **Verification operation/event**: A computation occurred.
*   **Integrity attestation assertion artifact**: A preserved assertion recording an observed verification result.
The portable identity identifies the *assertion artifact*, not the computation event. The previous terminology `attestationEventIdentity` is corrected to `assertionIdentity` to prevent premature event ontology.

## 18. Generic Assertion Identity Vocabulary
A common base semantic rule exists: **A portable assertion identity identifies one preserved assertion artifact/claim instance, not the assertion subject and not necessarily the external event described by the assertion.**

## 19. Manifest Uniqueness-Key Re-Audit
*   **Tombstone**: `portableEntryIdentity` (Schema version is structural; semantic state uniqueness relies solely on the entry identity).
*   **Disposition Assertion**: `assertionIdentity` (Globally portable).
*   **Relationship Assertion**: `assertionIdentity` (Globally portable).
*   **Integrity Attestation**: `assertionIdentity` (Globally portable).

## 20. Adversarial Tombstone Tests A–O
*   A, B, C (Adding reason, timestamp, prior digest): `SCHEMA_INVALID` (Prohibited fields).
*   D (Two identical tombstones for E1): `SCHEMA_INVALID` (Duplicate logical-set record).
*   E (Two conflicting tombstones for E1): `SCHEMA_INVALID` (Same-key conflict on `portableEntryIdentity`).
*   F (New tombstone per relationship): `SCHEMA_INVALID` (Violates single minimal state).
*   G, H (Copy/Clone): Safely copies canonical minimal state.
*   I (Merge tombstone with live material): *UNRESOLVED* (Requires separate merge-authority architecture).
*   J (Merge V1 and V2 tombstones): Coexist as representations, semantic state collapses safely.
*   K, L (Assertion without tombstone, Tombstone without assertion): Valid and architecturally permitted.
*   M (Tombstone given assertion ID): `SCHEMA_INVALID` (Tombstone is not an assertion).
*   N (Entry ID used as assertion ID): `SCHEMA_INVALID` (Subject != Assertion).
*   O (Failed tombstone verification proves tampering): `OUTSIDE_TOMBSTONE_AUTHORITY`.

## 21. 2076 Archivist Test
The archivist knows E1 is referenced but unavailable. They cannot infer why, when, or how it became unavailable from the tombstone alone. If disposition assertions exist, they provide the historical context independently. The tombstone preserves honesty without reconstructing deleted history.

## 22. Surviving Assumptions
Manifest is a transport artifact. The Two-Scope disposition policy is maintained. Historical authority remains delegated.

## 23. Unresolved Dependencies
Merge conflict resolution between a valid minimal tombstone and live entry material across two independent archives remains explicitly unresolved and requires a dedicated merge-authority architecture investigation.

## 24. Primary Recommendation
**MODEL T2**. Define the tombstone strictly as the canonical minimal surviving subject state for an unavailable entry, occupying one semantic slot (`portableEntryIdentity`). Remove all historical metadata from tombstones. Define assertion identity generically as identifying the preserved assertion artifact, explicitly avoiding system event identity ontology.

## 25. Secondary Alternative
Model T1 (Tombstone as assertion). Rejected due to metadata leakage and disposition duplication.

## 26. Rejected Models
Model T1, T3, T4, T5.

## 27. Required Canonical Corrections
*   Update `MANIFEST_ARTIFACT_REFERENCE_AND_MULTIPLICITY_INVESTIGATION.md` to clarify event vs assertion identity terminology.
*   Update `PACKAGE_MANIFEST_SEMANTIC_SCHEMA_INVESTIGATION.md` and `TOMBSTONE_RETENTION_POLICY_INVESTIGATION.md` to reflect Model T2 semantics.
*   Add Unresolved Dependency for merge-authority to `BETA_3_IMPLEMENTATION_PLAN.md`.

## 28. Implementation Consequences
Tombstone parsers must strictly reject extra fields. Tombstones cannot be used to recreate an archive ledger.

## 29. Final Architecture Classification
**TOMBSTONE_MINIMAL_STATE_ASSERTION_IDENTITY_DECISION_READY**
