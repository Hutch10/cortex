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
