# Beta 3 Implementation Plan

## Implementation Gate
**STATUS**: Beta 2 remains explicitly frozen.
**GATE**: BETA_2_STAGE_1_EVIDENCE_REVIEW_COMPLETE
No Beta 3 implementation is authorized until Stage 1 evaluation evidence review is fully complete.

## Phase 1: Portable Archive Identity
* **Deferred**: Define the portable, export-surviving archive identity.
* **Requirement**: Must not rely on storageKey, date matching, display labels, or list position.

## Phase 2: Prospective Stance Schema
* Introduce stance (observational | prospective | unspecified) to Grade A payload schemas.
* Ensure backward compatibility for Beta 2 records (fail-closed fallback to unspecified).
* Implement strict schema compatibility registry rules without retroactively upgrading legacy payloads.

## Phase 3: Archive Relationships (Grade B)
* Introduce the neutral ppended_to relationship.
* Ensure appending does not rewrite the referenced source or alter the source's integrity attestations.

## Phase 4: First-Class Citations (Grade C)
* Implement whole-entry citation relationships (cites, derived_from).

## Phase 5: Integrity Attestation Mechanism
* Evolve the canonical hashing implementation to explicitly store algorithm identity and authoritative representation identity.
* Implement hash agility to allow multiple attestations over time.

## Phase 6: Provenance Inspector & Archive Health
* Implement Archive Health as a strict diagnostic interface (pass/fail for structural/integrity rules).
* Implement Provenance Inspector purely as a read-only visualizer over the explicit relationship graph.

## Phase 7: Self-Describing Export
* Implement independent export formats that bundle required manifest documentation.
* Verify export intelligibility without active Vitalicast cloud or proprietary framework access.

## Deferred Implementations
### Portable Archive Entry Identity
* **SCHEME IDENTITY:** italicast-entry-id-v1
* **REFERENCE SERIALIZATION:** urn:vitalicast:entry:v1:<RFC UUIDv4 canonical textual representation>
* **Rationale:** Statistical global uniqueness with offline capability. Scheme-identifying but not fully self-describing. No temporal or ordering semantics.
* **Failure Semantics:** Missing ID fails explicitly; exact duplicate + identical content coalesces but preserves surrounding provenance; duplicate + differing content fails as explicit conflict. No absolute collision guarantees.
* **Implementation Status:** Explicitly deferred pending further Stage 1 evaluations and Beta 3 authorization.

### User-Requested Deletion and Disposition
* **Selected Contract:** Controlled Custody Disposition (Custody Removal) + Grade B Withdrawal
* **Rationale:** Avoids silent canonical rewrite while honoring user sovereignty over physical custody. Uses a minimum durable abstraction: Archive Entry, Disposition Assertion, Custody/Availability State, Reference Resolution State. The Two-Scope Model ensures referential integrity via minimal tombstones for referenced entries, while permitting full removal for unreferenced entries and archive-wide destruction. Minimum durable reference-preservation evidence is required when necessary to keep surviving references or provenance historically honest. A minimal tombstone is the leading representation, but exact structural representation remains dependent on relationship and manifest architecture contracts.
* **Failure Semantics:** Explicit DISPOSITION_REINTRODUCTION_CONFLICT isolation for reimported dispositioned material. Dangling citations explicitly recognized as SOURCE_DISPOSITIONED. Availability states are assertions within a defined archive/custody scope.
* **Implementation Status:** Explicitly deferred pending further Stage 1 evaluations and Beta 3 authorization.
