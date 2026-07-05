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
* **Selected Contract:** Controlled Custody Disposition (Custody Removal) + Grade B Withdrawal.
* **Rationale:** Reconciles User Sovereignty over physical custody with Immutable History through a Two-Scope Model (Policy E). Entry-scoped disposition preserves a minimal reference tombstone only when necessary to avoid rewriting surviving archive provenance. Unreferenced entry material may be fully removed from current archive custody without retaining an internal tombstone. Archive-wide custody destruction may terminate the archive continuity without preserving an internal tombstone graph. Prior independent copies remain outside the destruction promise.
* **Failure Semantics:** Explicit states are required (DISPOSITION_COMPLETE, DISPOSITION_REINTRODUCTION_CONFLICT, SOURCE_DISPOSITIONED, REPRODUCIBILITY_IMPAIRED_SOURCE_DISPOSITIONED). Conflicts arising from merges with offline surviving copies trigger explicit isolation. Reimported exports with valid pre-disposition sources against a tombstone are flagged as DISPOSITION_REINTRODUCTION_CONFLICT, preserving both historical validity and the disposition assertion.
* **Public Promise:** "User-requested disposition will be represented honestly. Vitalicast will distinguish withdrawal, visibility changes, custody-scoped source removal, and stronger erasure operations according to the effect actually completed. Vitalicast will not describe material as destroyed beyond the scope and assurance supported by the applicable disposition contract. Archive-wide custody destruction terminates the current archive under the defined custody scope; it does not assert that prior independent copies never existed."
* **Implementation Status:** Explicitly deferred.
