# Beta 3 Trust Architecture

## Foundation
Vitalicast is infrastructure for trustworthy personal records.

## Portable Archive Entry Identity
* **SCHEME IDENTITY:** italicast-entry-id-v1
* **REFERENCE SERIALIZATION:** urn:vitalicast:entry:v1:<RFC UUIDv4 canonical textual representation>
* **ENTITY SEMANTICS:** Identifies one historical archive-entry entity.
* **UNIQUENESS MODEL:** Statistical global uniqueness under correct UUIDv4 generation.
* **GENERATION AUTHORITY:** Local/offline generation permitted using a conforming sufficiently strong random source.
* **CONTENT RELATIONSHIP:** Entry identity is independent of content digest.
* **TEMPORAL SEMANTICS:** None.
* **ORDERING SEMANTICS:** None.
* **USER SEMANTICS:** None.
* **DEVICE SEMANTICS:** None.
* **COPY:** Identity preserved.
* **CLONE:** Existing entry identities preserved; newly created entries receive new identities under the scheme.
* **IMPORT:** Portable identity preserved when source identity is trusted as an archival assertion; import provenance remains separately preserved.
* **MERGE:** 
  * Same ID + entry-equivalent authoritative content: identity-equivalent material; preserve all non-identical surrounding archival context.
  * Same ID + differing authoritative content: explicit unresolved identity conflict.
* **PARTIAL EXPORT:** Identity preserved.
* **CITATION:** Whole-entry citations reference portable entry identity.
* **HASH EVOLUTION:** Identity unchanged.
* **SCHEMA EVOLUTION:** Identity unchanged.
* **FAILURE:** Missing, malformed, unsupported-scheme, or conflicting identity conditions fail explicitly.
* **Implementation Status:** Explicitly deferred.

## User-Requested Deletion and Disposition
* **Selected Contract:** Tombstone-Backed Physical Destruction + Grade B Withdrawal.
* **Rationale:** Reconciles User Sovereignty over physical custody with Immutable History. Physical bytes are destroyed on request, but a tombstone preserves the historical fact of the entry's existence, retaining the portable entry identity. Mistakes are corrected via Withdrawal (Grade B assertion) rather than silent canonical rewrite.
* **Failure Semantics:** Explicit states are required (DISPOSITION_COMPLETE, DISPOSITION_CONFLICT, SOURCE_DISPOSITIONED, REPRODUCIBILITY_IMPAIRED_SOURCE_DISPOSITIONED). Conflicts arising from merges with offline surviving copies trigger explicit isolation.
* **Public Promise:** "User-requested disposition will be represented honestly; Vitalicast will not describe hidden, withdrawn, unavailable, or partially erased material as though it never existed unless the applicable destruction contract explicitly defines and successfully completes that effect."
* **Implementation Status:** Explicitly deferred.
