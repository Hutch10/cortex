# Beta 3 Implementation Plan

## Implementation Gate
**STATUS**: Beta 2 remains explicitly frozen.
**GATE**: `BETA_2_STAGE_1_EVIDENCE_REVIEW_COMPLETE`
No Beta 3 implementation is authorized until Stage 1 evaluation evidence review is fully complete.

## Phase 1: Portable Archive Identity
* **Deferred**: Define the portable, export-surviving archive identity.
* **Requirement**: Must not rely on `storageKey`, date matching, display labels, or list position.

## Phase 2: Prospective Stance Schema
* Introduce `stance` (observational | prospective) to Grade A payload schemas.
* Ensure backward compatibility for Beta 2 records using a reader compatibility state equivalent to `not_present_in_source_schema`.
* Implement strict schema compatibility registry rules without retroactively upgrading legacy payloads.

## Phase 3: Archive Relationships (Grade B)
* Introduce the neutral `appended_to` relationship.
* Ensure appending does not rewrite the referenced source or alter the source's integrity attestations.

## Phase 4: First-Class Citation Relationships
* Implement whole-entry citation relationships (`cites`, `derived_from`).
* Citation is an archive relationship. Grade C derivations require explicit citations to source material under the citation relationship contract. A citation does not become Grade C merely because a Grade C derivation uses it. Preservation Grades classify provenance/material boundaries, not relationship objects.

## Phase 5: Integrity Attestation Mechanism
* Evolve the canonical hashing implementation to explicitly store algorithm identity and authoritative representation identity.
* Implement hash agility to allow multiple attestations over time.

## Phase 6: Provenance Inspector & Archive Health
* Implement Archive Health as a strict diagnostic interface (pass/fail for structural/integrity rules).
* Implement Provenance Inspector purely as a read-only visualizer over the explicit relationship graph.

## Phase 7: Self-Describing Export
* Implement independent export formats that bundle required manifest documentation.
* Verify export intelligibility without active Vitalicast cloud or proprietary framework access.

## Deferred Decision Register
1. `PORTABLE_ARCHIVE_ENTRY_IDENTITY_UNRESOLVED`: Portable citation/export identity independent of storageKey.
2. `USER_REQUESTED_DELETION_AND_IMMUTABLE_HISTORY_POLICY_UNRESOLVED`: Reconciliation of sovereignty/disposition with sealed history, citations, and integrity attestations.

## Deferred Implementations
### Portable Archive Entry Identity
* **Selected Contract:** URN-Prefixed Random Opaque Identifier (urn:vitalicast:entry:v1:<UUID>)
* **Rationale:** Maximizes portability, offline capabilities, and 50-year interpretability while avoiding metadata leakage or merge conflicts.
* **Failure Semantics:** Missing ID fails explicitly; exact duplicate deduplicates; conflicting content for same ID raises explicit failure.
* **Implementation Status:** Explicitly deferred pending further Stage 1 evaluations and Beta 3 authorization.
