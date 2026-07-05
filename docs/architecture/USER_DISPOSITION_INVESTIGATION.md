# User-Requested Deletion, Disposition, and Immutable History Architecture Investigation

## Phase 1 — Terminology Inventory
* **Custody Removal**: Source material is removed from the defined Vitalicast-controlled active custody scope under the documented disposition operation. We do not use the term "physical destruction" as Vitalicast cannot prove media zeroization or removal from all OS backups/caches.
* **Withdrawal**: A user assertion that prior material is retracted. Historically honest, preserves original.
* **Hide**: UI-layer visibility suppression.
* **Immutable / Canonical**: Sprint 6 concept ensuring source records are not silently rewritten.
* **Disposition**: Broader lifecycle term covering custody, state changes, and intent.

## Phase 2 — Separate Deletion Dimensions
1. **Disposition Intent**: User requests removal, visibility change, or withdrawal.
2. **Custody Result (Availability)**: Source material no longer available through the defined active archive custody boundary.
3. **Erasure Assurance**: What can actually be established about underlying retained representations (e.g., OS backups, wear leveling, caches).
4. **Historical Assertion**: Silent void vs explicit tombstone.
5. **Reference Resolution**: Resolvable vs dangling.
6. **Derivation Dependency**: Source identifiable vs source lost.

## Phase 3 — User Intent Model
* A. "I don't want to see this anymore" -> Visibility suppression (Hide).
* B. "Remove this from active archive" -> Controlled Custody Disposition.
* C. "Correct a mistake" -> Grade B Addendum (Correction).
* D. "Regret recording" -> Withdrawal (Grade B assertion) or Custody Removal.
* E. "Permanently destroy" -> Custody Removal (Erasure Assurance is limited).
* F. "Exclude from analysis" -> Analysis Exclusion.
* G. "Exclude from exports" -> Export Exclusion.
* H. "Nobody later reads this" -> Custody Removal + Warning regarding independent copies.
* I. "Evidence of withdrawal" -> Withdrawal.

## Phase 4 — Candidate Disposition Models
1. **Controlled Custody Disposition**: Source material is removed from active Vitalicast-controlled custody. Erasure Assurance cannot guarantee media zeroization.
2. **Tombstone**: A tombstone minimizes retained source content while preserving selected historical identity/disposition metadata. Tombstones and surviving relationships may themselves reveal sensitive metadata. Minimum retained data: portable entry identity, disposition fact, disposition time.
3. **Withdrawal**: Preserves source but asserts retraction.
4. **Cryptographic Erasure**: Not reliable without granular per-entry keys.

## Phase 5 — Grade-Specific Disposition
* **Grade A (Source)**: Custody removal permitted. Withdrawal permitted.
* **Grade B (Addendum)**: Custody removal permitted.
* **Grade C (Derived)**: Custody removal permitted. Source custody removal impairs reproducibility.
* **Grade D (External)**: Custody removal permitted.
* Grades are not truth, they are provenance.

## Phase 6 — Correction Versus Deletion
"Correction" requires preserving the mistaken Grade A source and appending a Grade B correction/retraction. Retraction does not prove the original was false, just that the user withdrew the assertion. A Grade B withdrawal is independently referenceable archive material and therefore requires portable entry identity. The relationship between withdrawal and prior source remains dependent on the unresolved relationship assertion identity model.

## Phase 7 — Identity vs Disposition Conflicts
* **Identity Conflict**: Same portable entry identity + different authoritative source content. Concerns entity/content disagreement.
* **Disposition Reintroduction Conflict**: A valid prior copy of a source entry is reintroduced into an archive state that contains a disposition assertion or tombstone for that entry. Concerns custody/availability policy disagreement across archive histories.

## Phase 8 — Reimport and Resurrection Semantics
When an old export containing a pre-disposition source is imported into an archive with a tombstone:
The archive preserves source historical validity, disposition assertion validity, import provenance, and marks the state as an unresolved current custody/disposition conflict.

## Phase 9 — Grade C Reproducibility Conflict
Historical Grade C artifacts are not silently recomputed when a cited source later becomes unavailable due to disposition. The Grade C artifact enters REPRODUCIBILITY_IMPAIRED_SOURCE_DISPOSITIONED. This condition is scope-aware; the source may still exist in a prior independent export.

## Phase 10 — Export and Prior Copy Reality
Availability and disposition states are assertions within a defined archive/custody scope and do not imply global absence from all prior independent copies.

## Phase 11 — Mandatory Tombstone vs Full Destruction
* **Model A - Mandatory Tombstone**: Source content removed from custody. Portable identity and minimal disposition evidence remain.
* **Model B - Full Destruction**: Source material and local disposition metadata removed completely.
Determining if Model A is constitutionally required or if Model B is constitutionally permissible requires interpreting the Constitution beyond current text. Classified as: MANDATORY_TOMBSTONE_RETENTION_VS_FULL_USER_DESTRUCTION_UNRESOLVED. This requires more research.

## Phase 12 — Minimum Durable Abstraction
1. **Archive Entry**: Historical material with portable identity.
2. **Disposition Assertion**: Authorized historical statement about intended treatment.
3. **Custody / Availability State**: Current source availability under an explicitly defined archive/custody scope, including the known Erasure Assurance.
4. **Reference Resolution State**: Whether a reference can resolve within the current context.
(Erasure assurance is integrated into Custody State.)

## Phase 13 — Public Promise Test
New disposition commitment: "User-requested disposition will be represented honestly. Vitalicast will distinguish withdrawal, visibility changes, custody-scoped source removal, and stronger erasure operations according to the effect actually completed. Vitalicast will not describe material as destroyed beyond the scope and assurance supported by the applicable disposition contract."

## Phase 14 — Threat and Abuse Model
Abusive deletion, regret, and accidental deletion require explicit states (SOURCE_DISPOSITIONED, DISPOSITION_REINTRODUCTION_CONFLICT). Threat of a tombstone leaking metadata is acknowledged. Threat of incomplete media zeroization is handled by limiting erasure assurance claims to custody removal.

## Decision Classification
USER_DISPOSITION_ARCHITECTURE_REQUIRES_MORE_RESEARCH
