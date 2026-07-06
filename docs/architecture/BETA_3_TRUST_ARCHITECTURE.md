# Beta 3 Trust Architecture

## Foundation Model
The architecture synchronizes around five durable foundations:
1. **Archive Material / Source Content**: Preserved user source records, addenda, derivations, and external/imported material under explicit provenance boundaries (Grades A-D).
2. **Archive Relationships**: A narrow conceptual relationship layer equivalent to ppended_to, cites, and derived_from.
3. **Integrity Attestations**: Verification mechanism defining the target identity, algorithm, canonicalization, and digest.
4. **Portability and Archive Identity**: Separation of runtime exact-read identity (storageKey) from the portable permanent archive entry identity.
5. **Self-Describing Export**: The archive must preserve sufficient format, provenance, manifest, and contract documentation to support independent interpretation without dependence on current Vitalicast services.

## Grade A Canonical Source Record
A Grade A source record encompasses user-authored source material after sealing.
The architecture implements a **record stance** property:
- observational
- prospective (A first-class stance oriented toward a future or unresolved state)

Descriptive kinds (e.g., intention, goal, prediction) are secondary vocabulary. Vitalicast does not implement an eight-object taxonomy or taxonomy engine.

## Temporal Honesty
A prospective stance does not automatically certify that the record existed before the eventual outcome. The architecture explicitly separates capture time, seal time, user-asserted reference time, and eventual event time. There is no "prospective truth" semantics.

## Beta 2 Legacy Classification
Existing Beta 2 source records remain unchanged. The architecture forbids retroactive semantic reclassification, keyword-based taxonomic inference, or mass-upgrades of legacy Beta 2 payloads. Beta 2 source material remains source material under Grade A provenance rules with reader compatibility state: `not_present_in_source_schema`. The certified legacy source schema did not contain a stance field; absence of a stance field is not an archived stance value.

## Relationships & First-Class Citation Relationships
Later outcomes or reflections remain append-only Grade B material related via a neutral `appended_to` relationship. 
First-Class Citations identify the citing archive entry, the cited portable archive entry identity, relationship kind, and creation context. Citation is an archive relationship; `cites` and `derived_from` are relationship semantics. Grade C is derived archive material provenance. Grade C derivations require explicit citations to relevant source material under the citation relationship contract. A citation does not become Grade C merely because Grade C material uses it, and Preservation Grades do not automatically apply to relationship assertions.
Scope prioritizes whole-entry citation. No character-offset or JSON Pointer citation is required initially.
Causal relationships (e.g. `outcome_of`) are explicitly not required core relationships. Conceptual relationship semantics are established; durable relationship-assertion identity remains unresolved (`RELATIONSHIP_ASSERTION_IDENTITY_MODEL_UNRESOLVED`).

## Integrity and Canonical Hashing
Constitutional Invariant: Alteration of preserved archival material must be independently detectable.
The architecture explicitly defines:
* Authoritative representation or bytes
* Integrity algorithm identity
* Canonicalization identity
* Digest
Hash agility guarantees append-only attestation evolution; old attestations are never erased to upgrade cryptography. The architecture avoids silently normalizing source content just to obtain a hash.

## Archive Health & Provenance Inspector
* **Archive Health**: A derived diagnostic checking explicit conditions (e.g., integrity checks passed/failed, unresolved citations). It does not issue composite trust scores, completion percentages, or penalize "unfulfilled commitments".
* **Provenance Inspector**: A read-only derived view. It reads explicit archived provenance and relationship information and does not become a second authority that invents its own lineage interpretation.

## Architecture Weaknesses & Simplifications
* **Simplification**: Removed the eight-object taxonomy (intention, goal, etc.) as distinct archive root classes, replacing it with a single "prospective" stance on Grade A records.
* **Simplification**: Removed complex causal relationships (`outcome_of`); standardized on `appended_to`, `cites`, and `derived_from`.
* **Migration Hazard**: Future implementations must be extremely careful to avoid implicit classification of Beta 2 records.

## Portable Archive Entry Identity
* **SCHEME IDENTITY:** italicast-entry-id-v1
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
* **Implementation Status:** Architecture decision ready; implementation deferred.

## User-Requested Deletion and Disposition
* **Selected Contract:** Controlled Custody Disposition (Custody Removal) + Grade B Withdrawal.
* **Rationale:** Reconciles User Sovereignty over physical custody with Immutable History through a Two-Scope Model (Policy E). Entry-scoped disposition preserves a minimal reference tombstone only when necessary to avoid rewriting surviving archive provenance. Unreferenced entry material may be fully removed from current archive custody without retaining an internal tombstone. Minimum durable reference-preservation evidence is required when necessary to keep surviving references or provenance historically honest. A minimal tombstone is the leading representation, but exact structural representation remains dependent on relationship and manifest architecture contracts. Archive-wide custody destruction may terminate the archive continuity under the defined Vitalicast-controlled custody scope without preserving an internal tombstone graph. Prior independent copies remain outside the destruction promise.
* **Failure Semantics:** Explicit states are required (DISPOSITION_COMPLETE, DISPOSITION_REINTRODUCTION_CONFLICT, SOURCE_DISPOSITIONED, REPRODUCIBILITY_IMPAIRED_SOURCE_DISPOSITIONED). Conflicts arising from merges with offline surviving copies trigger explicit isolation. Reimported exports with valid pre-disposition sources against a tombstone are flagged as DISPOSITION_REINTRODUCTION_CONFLICT, preserving both historical validity and the disposition assertion.
* **Public Promise:** "User-requested disposition will be represented honestly. Vitalicast will distinguish withdrawal, visibility changes, custody-scoped source removal, and stronger erasure operations according to the effect actually completed. Vitalicast will not describe material as destroyed beyond the scope and assurance supported by the applicable disposition contract. Archive-wide custody destruction terminates the current archive under the defined custody scope; it does not assert that prior independent copies never existed."
* **Implementation Status:** Architecture decision ready; implementation deferred.

## Manifest Historical Authority
* **Selected Contract:** Package Manifest only (Model C).
* **Rationale:** Historical archive authority is fully distributed across archive entries, disposition assertions, relationship assertions, and integrity attestations. A central immutable Historical Archive Ledger contradicts the Two-Scope disposition policy allowing unreferenced material destruction. A Package Manifest acts merely as a current package inventory, explicitly supporting partial exports and making no claims of complete life history.
* **Failure Semantics:** Missing files mean they are not in the package, not that they never existed. Re-exports omit unreferenced dispositioned material without rewriting history.
* **Implementation Status:** Architecture decision ready; implementation deferred.
