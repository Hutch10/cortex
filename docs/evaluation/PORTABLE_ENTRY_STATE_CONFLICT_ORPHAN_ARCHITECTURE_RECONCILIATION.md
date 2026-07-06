# Portable Entry State Conflict Orphan Architecture Reconciliation

## 1. Scope
Determine the status, provenance, and canonical authority of the untracked file `PORTABLE_ENTRY_STATE_CONFLICT_AND_MERGE_AUTHORITY_INVESTIGATION.md`. Establish whether it contains blocking prerequisites or unincorporated precision, and reconcile its presence with the accepted canonical architecture.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `45c934f`

## 3. Untracked Artifact Identity and Path
*   **Filename**: `PORTABLE_ENTRY_STATE_CONFLICT_AND_MERGE_AUTHORITY_INVESTIGATION.md`
*   **Exact Path**: `docs/architecture/PORTABLE_ENTRY_STATE_CONFLICT_AND_MERGE_AUTHORITY_INVESTIGATION.md`

## 4. Tracked and Ignored Status
*   **Tracked Status**: Untracked (`??` in `git status --short`).
*   **Ignored Status**: Not ignored (no `.gitignore` rules apply).

## 5. Full-Content Classification
*   **Title**: Portable Entry State Conflict and Merge Authority Investigation
*   **Stated Scope**: Determine how Vitalicast must reason when two independently valid archive/package states concerning the same `portableEntryIdentity` disagree about material availability (specifically, a minimal tombstone in Archive A vs. live entry material in Archive B).
*   **Decision Token**: `PORTABLE_ENTRY_STATE_CONFLICT_MERGE_AUTHORITY_DECISION_READY`
*   **Selected Model**: MODEL M6 (Custody-scoped state)
*   **Completeness**: Appears complete, with no placeholders.
*   **Provenance**: Generated during the Beta 3 architecture evidence phase.

## 6. Temporal Relationship
*   **Classification**: `CLEARLY_PREDATES_ACCEPTED_CHAIN`.
*   **Evidence**: The document references `b9f2e21` as its HEAD. The accepted architecture chain continued from `b9f2e21` to establish Model M4 in `cf60196` and refined it in `45c934f`. The untracked document specifically selects Model M6 (Custody-scoped state), a model explicitly rejected in the later tracked commit `cf60196` (`MERGE_AUTHORITY_TOMBSTONE_LIVE_CONFLICT_INVESTIGATION.md`).

## 7. Decision-Overlap Matrix
| Proposition | Classification |
| :--- | :--- |
| Live/tombstone precedence | `CONFLICTS_ACCEPTED` (Untracked says live transfer overwrites tombstone without conflict artifact) |
| Conflict-preserving merge | `CONFLICTS_ACCEPTED` (Untracked rejects preserving conflict, accepted selects Model M4) |
| Active-state semantics | `CONFLICTS_ACCEPTED` (Untracked says active state is live without conflict, accepted says CONFLICTED) |
| Resolution semantics | `CONFLICTS_ACCEPTED` (Untracked requires no resolution, accepted requires explicit assertion) |
| Conflict as observation vs assertion | `UNRELATED` (Untracked does not address conflict records) |

## 8. Accepted-Chain Conflict Audit
The untracked document explicitly contradicts the accepted canonical architecture by advocating for Model M6 (Custody-scoped state) which silently drops the tombstone evidence when merging with live material. The accepted canonical architecture (Model M4 + Model C4) mandates preserving both states as an unresolved conflict.

## 9. Unincorporated Precision Audit
None. The untracked document does not contain finer precision that survived into the accepted models; its entire premise was rejected in subsequent canonical work.

## 10. Portable-Entry-State Prerequisite Audit
The untracked document does not define a broader unaddressed state machine. It restricts itself exclusively to "a minimal tombstone in Archive A vs. live entry material in Archive B", a problem space entirely subsumed by the accepted conflict observation architecture.

## 11. Live/Live Conflict Prerequisite Result
The document does NOT address same-entry live/live conflicts (e.g., distinct valid material representations for the same identity). This remains a legitimately deferred scope but is not a blocker originating from this untracked file.

## 12. Canonical Terminology Audit
*   **Terminology Only Gap**: The canonical documents use "live material" and "minimal tombstone state" without relying on an undefined broader "portable entry state" abstraction.
*   **Result**: `NO_GAP`. Canonical terminology is self-sufficient based on the recent conflict observation definitions.

## 13. Reconciliation Models Evaluated
*   **MODEL R1 (Delete as scratch/orphan)**: **SELECTED**. The file has no surviving architecture value, contradicts established canonical truth, and leaving it risks future ambiguity.
*   **MODEL R2 (Preserve outside canonical architecture)**: Rejected. Merely moves the ambiguity.
*   **MODEL R3 (Archive as superseded investigation evidence)**: Rejected. The repository already cleanly records the accepted path in Git; adding an untracked superseded document litters the workspace.
*   **MODEL R4 (Incorporate surviving precision and delete)**: Rejected. No surviving precision exists.
*   **MODEL R5 (Promote as canonical prerequisite)**: Rejected. Not a prerequisite.
*   **MODEL R6 (Canonical regression/conflict stop)**: Rejected. Not a canonical regression, just leftover untracked material.

## 14. Temporal-Authority Rule
A newer canonical decision (e.g., Model M4/C4 in `cf60196`/`45c934f`) explicitly overrides older untracked scratch material (Model M6) that shares the same parent commit (`b9f2e21`). An older untracked document must not overwrite later accepted precision.

## 15. Worktree Ambiguity Result
Leaving the overlapping architecture file untracked creates search contamination, future prompt pickup risk, and implementation ambiguity, especially since its title closely mirrors canonical documents.

## 16. Selected Reconciliation Action
**MODEL R1 (Delete as scratch/orphan)**. The untracked file `PORTABLE_ENTRY_STATE_CONFLICT_AND_MERGE_AUTHORITY_INVESTIGATION.md` will be permanently deleted from the worktree.

## 17. Surviving Assumptions
Manifest is a transport artifact. The Two-Scope disposition policy is maintained. Conflict-preserving merge remains accepted.

## 18. Unresolved Dependencies
None.

## 19. Final Classification
**ORPHAN_PORTABLE_ENTRY_STATE_ARCHITECTURE_RECONCILED**
