# Tombstone Retention vs Full User Destruction Constitutional Policy Investigation

## Phase 1 — Constitutional Boundaries
* **Policy Tension Statement**: User Sovereignty permits authorized disposition of archive material, while historical non-rewriting prohibits silently falsifying surviving archive history.

## Phase 2 — Destruction Scopes
* **ENTRY-SCOPED FULL DESTRUCTION**: User requests removal of source material and all locally controlled metadata indicating a specific entry identity ever existed.
* **ARCHIVE-WIDE CUSTODY DESTRUCTION**: User requests termination and removal of the entire archive under the defined current Vitalicast-controlled custody scope.

## Phase 3 — Entry-Scoped Destruction Graph Test
* **CASE A (No dependencies)**: Full destruction WITHOUT history rewrite is POSSIBLE.
* **CASE B (Grade B appended)**: Full destruction WITHOUT history rewrite is IMPOSSIBLE if the Grade B relation is retained as it creates a dangling reference that cannot be honestly resolved without a minimal tombstone.
* **CASE C (Grade C derived)**: Full destruction WITHOUT history rewrite is IMPOSSIBLE because the Grade C artifact would have a source citation removed silently or impaired without explanation.
* **CASE D (Multiple citations)**: Requires graph traversal. Full destruction WITHOUT history rewrite is IMPOSSIBLE unless all dependent materials are also dispositioned.
* **CASE E (Manifests/Attestations)**: Full destruction WITHOUT history rewrite is CONDITIONALLY_POSSIBLE depending on whether the manifest is a historical ledger (immutable) or a current index (mutable).

## Phase 4 — Cascading Destruction Analysis
* **Model 1 (Non-Cascading)**: Destroy A only. Dependent references remain. Surviving material implies A existed.
* **Model 2 (Reference Rewrite)**: Destroy A and rewrite references. Falsifies surviving provenance. (Rejected).
* **Model 3 (Cascading Destruction)**: Recursive deletion. High risk of unwanted destruction. (Rejected for automatic use).
* **Model 4 (Minimal Tombstone)**: Destroy A's source content, retain minimal identity/disposition evidence. Honest historical resolution.

## Phase 5 — The "Right to Erase Existence" Claim
User Sovereignty (the right to control custody and remove material) is NOT equivalent to the right to rewrite surviving historical provenance. The current Constitution does not grant a right to silently rewrite history to make it look like an event never happened if surviving dependent material relies on that fact.

## Phase 6 — Entry-Scoped Minimum Tombstone Test
* **TOMBSTONE CORE**: Portable entry identity, availability/disposition state.
* **OPTIONAL**: A separate disposition assertion entry (with its own identity, time, and context).
Tombstones must not automatically retain original grade, type, timestamps, digest, or other metadata unless strictly necessary for referential integrity.

## Phase 7 — No-Reference Entry Case
If entry A has no citations, derivations, or surviving external archive relationships, it can be fully removed from current archive custody without rewriting surviving historical material. Mandatory tombstone retention for *every* entry is unnecessarily restrictive. A tombstone is required only when necessary to preserve surviving archive referential/provenance integrity.

## Phase 8 — Archive-Wide Custody Destruction Test
Archive-wide custody destruction terminates the archive and removes material from the defined Vitalicast-controlled custody scope. It does not require retaining an internal tombstone graph because the entire local continuity is intentionally destroyed. It makes no claim to erase prior independent copies or external obligations. This aligns with User Sovereignty without violating the Public Stability Promise (which applies to surviving archive continuity).

## Phase 9 — Partial Archive / Copy Divergence
No single copy has the authority to declare "A never existed." Reimport, merge, or clone operations respect the explicit disposition states to resolve conflicts honestly, preserving the distinction between intentional disposition and unexplained corruption.

## Phase 10 — Grade C and Dependent Artifact Policy
Dependent material requires separate explicit disposition scope. We do not automatically cascade destruction.

## Phase 11 — Manifest and Integrity History
Historical manifests, if immutable, cannot be rewritten to erase evidence of A. Current export manifests can simply omit A. Unresolved architecture dependency on manifest design remains, but does not block the core policy.

## Phase 12 — Policy Models Evaluated
* **POLICY A (Universal Mandatory Tombstone)**: Too restrictive for unreferenced entries.
* **POLICY B (Referential-Integrity Tombstone)**: Good for entry-scoped destruction, balances sovereignty and honesty.
* **POLICY C (Full User Erasure with Cascade)**: Dangerous automatic destruction.
* **POLICY D (No Entry Destruction)**: Violates sovereignty.
* **POLICY E (Two-Scope Model)**: Entry-scoped disposition follows referential-integrity rules. Archive-wide custody destruction terminates the entire local archive continuity and does not require internal tombstone retention.

## Phase 13 — Public Promise Test
Archive-wide custody destruction terminates the current archive under the defined custody scope; it does not assert that prior independent copies never existed. Disposition of one entry does not authorize silent rewriting of surviving archive provenance.

## Phase 14 — 50-Year Archivist Test
Policy E allows an archivist to correctly interpret dangling references (via minimal tombstones), detect missing independent sources without assuming corruption, and understand when an entire archive continuity was legally/intentionally terminated.

## Phase 15 — Recommendation
**PRIMARY POLICY RECOMMENDATION**: POLICY E (Two-Scope Model).
* Constitutional Interpretation: User Sovereignty governs physical custody removal. Historical non-rewriting governs surviving provenance integrity.
* No-Reference Rule: Unreferenced entries may be fully removed without tombstones.
* Referenced-Entry Rule: Minimal tombstones are required to prevent falsifying surviving references.

## Phase 16 — Constitutional Conflict Test
CONSTITUTION_INTERPRETATION_REQUIRED_BUT_CURRENT_TEXT_SUPPORTS_POLICY

## Phase 17 — Decision Result
USER_DISPOSITION_ARCHITECTURE_DECISION_READY

