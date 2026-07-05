# User-Requested Deletion, Disposition, and Immutable History Architecture Investigation

## Phase 1 — Terminology Inventory
* **Delete / Erasure / Destruction**: Hard physical removal of bytes from custody. Currently unimplemented in Beta 2 archive readers/writers.
* **Withdrawal**: A user assertion that prior material is retracted. Historically honest, preserves original.
* **Hide**: UI-layer visibility suppression.
* **Immutable / Canonical**: Sprint 6 concept ensuring source records are not silently rewritten.
* **Purge / Disposition**: Broader lifecycle terms covering custody and state changes.

## Phase 2 — Separate Deletion Dimensions
1. **Visibility**: Hidden vs visible in normal UI.
2. **Logical Archive Membership**: Active vs dispositioned.
3. **Physical Retention**: Bytes exist vs destroyed.
4. **Cryptographic Accessibility**: Decryptable vs key destroyed.
5. **Historical Assertion**: Silent void vs explicit tombstone.
6. **Reference Resolution**: Resolvable vs dangling.
7. **Derivation Dependency**: Source identifiable vs source lost.
8. **Export Presence**: Included vs excluded.
9. **Prior Copy Status**: Retrievable vs unreachable (independent of Vitalicast).
10. **Legal Retention**: Custodian obligation vs user sovereignty.

## Phase 3 — User Intent Model
* A. "I don't want to see this anymore" -> Visibility suppression (Hide).
* B. "Remove this from active archive" -> Logical disposition.
* C. "Correct a mistake" -> Grade B Addendum (Correction).
* D. "Regret recording" -> Withdrawal (Grade B assertion) or Destruction.
* E. "Permanently destroy" -> Hard Physical Deletion with Tombstone.
* F. "Exclude from analysis" -> Analysis Exclusion.
* G. "Exclude from exports" -> Export Exclusion.
* H. "Nobody later reads this" -> Destruction.
* I. "Evidence of withdrawal" -> Withdrawal.
* J. "Act as though this never existed" -> Silent Canonical Rewrite (Conflicts with constitution).
* K. "Delete everything" -> Archive-Wide Destruction.

## Phase 4 — Candidate Disposition Models
1. **Hard Physical Deletion**: Violates implicit assumptions if silent, breaks citations, but fulfills strict sovereignty. Requires a tombstone to maintain historical honesty.
2. **Tombstone**: Preserves identity and historical fact of disposition without retaining source material. Truthful, privacy-preserving.
3. **Withdrawal**: Preserves source but asserts retraction.
4. **Hide**: Deceptive if treated as deletion.
5. **Analysis/Export Exclusion**: Valid for controlling use without destroying history.
6. **Cryptographic Erasure**: Not reliable without granular per-entry keys.
7. **Archive-Wide Destruction**: Destroys local/cloud custody.
8. **Silent Canonical Rewrite**: Rejected. Conflicts with Vitalicast's historical honesty principle.

## Phase 5 — Grade-Specific Disposition
* **Grade A (Source)**: Physical deletion (with tombstone) permitted. Withdrawal permitted.
* **Grade B (Addendum)**: Physical deletion permitted (tombstones).
* **Grade C (Derived)**: Physical deletion permitted. Source deletion impairs reproducibility.
* **Grade D (External)**: Physical deletion permitted.
* Grades are not truth, they are provenance. Sovereignty applies to custody of all grades.

## Phase 6 — Correction Versus Deletion
"Correction" requires preserving the mistaken Grade A source and appending a Grade B correction/retraction. Retraction does not prove the original was false, just that the user withdrew the assertion. Deleting Grade A to "correct" history is a canonical rewrite and is prohibited.

## Phase 7 — Portable Identity Interaction
Hard deletion must leave a tombstone that preserves the urn:vitalicast:entry:v1:<UUID> identity. Citations point to the dispositioned identity (dangling). Re-importing an old export restores the content under the original identity, creating a conflict if the current archive holds a tombstone.

## Phase 8 — Citation and Relationship Interaction
Citations to a destroyed target become dangling references. The identity survives in the tombstone, allowing the system to disclose "Target Unavailable/Dispositioned." Citations are not silently rewritten.

## Phase 9 — Grade C Reproducibility Conflict
If Grade C analysis D cites Grade A record B, and B is destroyed:
D remains. B is physically destroyed (tombstone). D's citations remain. The original derivation cannot be fully reproduced. State: REPRODUCIBILITY_IMPAIRED_SOURCE_DISPOSITIONED. Historical analyses remain historical artifacts.

## Phase 10 — Export and Prior Copy Reality
Vitalicast cannot destroy copies outside its custody. The promise is limited to "Current Vitalicast-Controlled Custody." It is impossible to guarantee "permanently deleted everywhere."

## Phase 11 — Cryptographic Erasure Analysis
Vitalicast does not currently employ per-entry key isolation capable of granular cryptographic erasure. Cryptographic erasure is fragile for long-term portable archives.

## Phase 12 — Legal and Ethical Boundary
User-policy disposition is architecturally separate from external legal retention/erasure obligations.

## Phase 13 — Threat and Abuse Model
Abusive deletion, regret, and accidental deletion require explicit states (SOURCE_DISPOSITIONED, DISPOSITION_CONFLICT). Repeated delete/import cycles cause explicit identity conflicts. Merges that reintroduce dispositioned content against a tombstone trigger conflict isolation.

## Phase 14 — Failure Semantics
Explicit states required:
* DISPOSITION_COMPLETE
* DISPOSITION_INCOMPLETE
* DISPOSITION_CONFLICT
* SOURCE_UNAVAILABLE
* SOURCE_DISPOSITIONED
* REPRODUCIBILITY_IMPAIRED_SOURCE_DISPOSITIONED

## Phase 15 — Public Promise Test
New disposition commitment required: "User-requested disposition will be represented honestly; Vitalicast will not describe hidden, withdrawn, unavailable, or partially erased material as though it never existed unless the applicable destruction contract explicitly defines and successfully completes that effect."

## Phase 16 — Minimum Durable Abstraction
1. **Archive Entry**: Historical material + Portable Identity
2. **Disposition Assertion**: User-authorized statement about custody/availability.
3. **Availability State**: Sourced from custody vs tombstone.
4. **Reference State**: Resolvable vs Dangling.

## Phase 17 — Recommendation
**PRIMARY RECOMMENDATION**: Tombstone-Backed Physical Destruction + Grade B Withdrawal.
* Sovereignty is honored via physical removal.
* History is honored via tombstones (preserving entry identity).
* Correction is handled via withdrawal (retaining source).
* Grade C analyses gracefully degrade to REPRODUCIBILITY_IMPAIRED_SOURCE_DISPOSITIONED.
* No silent canonical rewrites.
* Explicit states handle partial failure and import conflicts.

**SECONDARY ALTERNATIVE**: Pure Cryptographic Erasure (rejected due to missing granular key architecture).
**REJECTED**: Silent Canonical Rewrite, Pure Hide.

**ARCHITECTURE CHALLENGE**
* Archive exists on two devices. Device 1 deletes entry (creates tombstone). Device 2 is offline. Devices merge: Tombstone conflicts with surviving Source. System flags DISPOSITION_CONFLICT.
* Export is reimported: Source bytes restored against tombstone. DISPOSITION_CONFLICT.

## Decision Classification
USER_DISPOSITION_ARCHITECTURE_DECISION_READY
