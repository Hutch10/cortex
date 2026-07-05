# Beta 3 Implementation Plan

## Phases
1. Phase 1
2. Phase 2

## Deferred Implementations
### Portable Archive Entry Identity
* **SCHEME IDENTITY:** italicast-entry-id-v1
* **REFERENCE SERIALIZATION:** urn:vitalicast:entry:v1:<RFC UUIDv4 canonical textual representation>
* **Rationale:** Statistical global uniqueness with offline capability. Scheme-identifying but not fully self-describing. No temporal or ordering semantics.
* **Failure Semantics:** Missing ID fails explicitly; exact duplicate + identical content coalesces but preserves surrounding provenance; duplicate + differing content fails as explicit conflict. No absolute collision guarantees.
* **Implementation Status:** Explicitly deferred pending further Stage 1 evaluations and Beta 3 authorization.

### User-Requested Deletion and Disposition
* **Selected Contract:** Controlled Custody Disposition (Custody Removal) + Grade B Withdrawal
* **Rationale:** Avoids silent canonical rewrite while honoring user sovereignty over physical custody. Uses a minimum durable abstraction: Archive Entry, Disposition Assertion, Custody/Availability State, Reference Resolution State. The Two-Scope Model ensures referential integrity via minimal tombstones for referenced entries, while permitting full removal for unreferenced entries and archive-wide destruction.
* **Failure Semantics:** Explicit DISPOSITION_REINTRODUCTION_CONFLICT isolation for reimported dispositioned material. Dangling citations explicitly recognized as SOURCE_DISPOSITIONED. Availability states are assertions within a defined archive/custody scope.
* **Implementation Status:** Explicitly deferred pending further Stage 1 evaluations and Beta 3 authorization.
