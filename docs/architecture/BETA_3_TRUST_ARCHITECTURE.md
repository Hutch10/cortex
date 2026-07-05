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
* **Rationale:** Reconciles User Sovereignty over physical custody with Immutable History. Physical bytes are removed from the defined active custody scope, but Vitalicast limits claims of "physical destruction" based on erasure assurance realities. A tombstone minimizes retained source content while preserving selected historical identity/disposition metadata (portable entry identity, disposition fact, disposition time), though it is not categorically privacy-preserving. Mistakes are corrected via Withdrawal (Grade B assertion).
* **Failure Semantics:** Explicit states are required (DISPOSITION_COMPLETE, DISPOSITION_REINTRODUCTION_CONFLICT, SOURCE_DISPOSITIONED, REPRODUCIBILITY_IMPAIRED_SOURCE_DISPOSITIONED). Conflicts arising from merges with offline surviving copies trigger explicit isolation. Reimported exports with valid pre-disposition sources against a tombstone are flagged as DISPOSITION_REINTRODUCTION_CONFLICT, preserving both historical validity and the disposition assertion.
* **Public Promise:** "User-requested disposition will be represented honestly. Vitalicast will distinguish withdrawal, visibility changes, custody-scoped source removal, and stronger erasure operations according to the effect actually completed. Vitalicast will not describe material as destroyed beyond the scope and assurance supported by the applicable disposition contract."
* **Implementation Status:** Explicitly deferred pending further research on Mandatory Tombstone Retention vs Full User Destruction.
