# Portable Archive Entry Identity Architecture Investigation

## Phase 1 - Current Identity Inventory
**storageKey**
* **Producer:** Caller of createSecureRecord / ppendAddendum
* **Consumer:** Native Secure Storage plugin, ArchiveKeyListProvider, exact readers
* **Format:** italicast_canonical_{recordId} or italicast_addendum_{recordId}_{addendumId}
* **Scope of Uniqueness:** Device-local native secure storage namespace
* **Persistence Boundary:** Application storage boundary
* **Payload Inclusion:** No (VitalicastBatchPayload contains no explicit ecordId)
* **Exported:** Not currently exported (Beta 2 export boundary remains undefined for identity)
* **Human-Visible:** Strictly prohibited (Sprint 6 requirement)
* **Mutable:** Value itself is immutable; but the identity is not bound cryptographically to the content
* **Collision Assumptions:** Relies on application-provided uniqueness for ecordId and ddendumId
* **Implementation Meaning:** An internal, device-local exact-read implementation identifier only

**Conclusion on storageKey:** It is an internal exact-read pointer. It cannot serve as the portable long-lived archive identity.

## Phase 2 - Portable Identity Requirements
The minimum durable identity contract evaluated against a 50-year horizon:
* A. **Application restart**: MUST_SURVIVE
* B. **Application upgrade**: MUST_SURVIVE
* C. **Database replacement**: MUST_SURVIVE
* D. **Native secure-storage replacement**: MUST_SURVIVE
* E. **Device replacement**: MUST_SURVIVE
* F. **Standard archive export**: MUST_SURVIVE
* G. **Archive import**: MUST_SURVIVE
* H. **File relocation**: MUST_SURVIVE
* I. **Export package renaming**: MUST_SURVIVE
* J. **Copying an archive package**: MUST_SURVIVE
* K. **Copying an individual archive file**: MUST_SURVIVE
* L. **Merging two archives from the same person**: MUST_SURVIVE
* M. **Merging archives from different people**: MUST_SURVIVE
* N. **Partial export**: MUST_SURVIVE (identity must remain intact even if citations break)
* O. **Citation from one exported entry to another**: MUST_SURVIVE
* P. **Missing citation target**: MUST_SURVIVE (the identity of the referring entry remains intact)
* Q. **Schema evolution**: MUST_SURVIVE
* R. **Hash algorithm evolution**: MUST_SURVIVE
* S. **Canonicalization evolution**: MUST_SURVIVE
* T. **Duplicate content**: ARCHITECTURE_DECISION_REQUIRED
* U. **Identical timestamps**: MUST_SURVIVE
* V. **Offline creation**: MUST_SURVIVE
* W. **Multiple-device creation**: MUST_SURVIVE
* X. **Clock drift**: MUST_SURVIVE
* Y. **Clock rollback**: MUST_SURVIVE
* Z. **Future application replacement**: MUST_SURVIVE

## Phase 3 - Identity Versus Content Integrity
Identity and Content Digest MUST remain separate concerns.
1. Two independent source records contain byte-identical content: They are two distinct archival entries if generated at different times or contexts.
2. A Grade B addendum contains exactly the same text: Identity must remain distinct.
3. Hash algorithm is upgraded: Identity remains unchanged; attestations are added.
4. New integrity attestation added: Identity remains unchanged.
5. Copied entry: Retains identity.
6. Citation graph changes: Entry identity remains unchanged.
7. Addendum appended: Original identity remains unchanged.

## Phase 4 - Identity Model Candidates
**1. RANDOM OPAQUE IDENTIFIER (RFC UUIDv4)**
* Uniqueness: Statistical global uniqueness under the documented random-generation contract.
* Offline: Excellent
* Merge behavior: Minimal expected collision assumption
* 50-year interpretability: High (well-understood primitive)

**2. TIME-ORDERED OPAQUE IDENTIFIER (UUIDv7/ULID)**
* Time leakage: High (metadata leak in identity)
* Multi-device collision: Resolvable via randomness
* Mistaken interpretation: Users/archivists may mistake the ID timestamp for the *authoritative* payload timestamp

**3. CONTENT-ADDRESSED IDENTITY**
* Hash agility: Poor (forces identity migration when hash changes)
* Duplicate-content collapse: Destroys independent entry history
* Result: Unsuitable for primary entry identity

**4. ARCHIVE-SCOPED SEQUENTIAL IDENTITY (Namespace + Seq)**
* Merge complexity: High (sequential collisions when archives merge)

**5. COMPOSITE IDENTITY (Namespace + Random)**
* Complexity: High, requires namespace authority

**6. SELF-CERTIFYING / CRYPTOGRAPHIC IDENTITY**
* Key-lifecycle complexity: Excessive for 50-year horizons without active maintenance

## Phase 5 - Archive Identity Context
Portable Archive Entry Identity must have **statistical global uniqueness**.
Archive namespaces require authorities, and when archives are merged, split, or cloned, namespaces fracture. Opaque entry identifiers allow entries to float freely across boundaries, exports, and imports without namespace resolution failures.

## Phase 6 - Copy, Clone, Import, and Merge Semantics
* **COPY**: An exact duplicate. Retains identical entry identity.
* **CLONE**: An independently evolving archive initialized from existing material. Existing entry identities preserved; newly created entries receive new identities under the scheme.
* **IMPORT**: Portable identity preserved when source identity is trusted as an archival assertion; import provenance remains separately preserved.
* **MERGE**: 
  * Same ID + entry-equivalent authoritative content: identity-equivalent material; implementations may coalesce identity-equivalent entry material for storage or presentation only when surrounding non-identical archival context remains preserved.
  * Same ID + differing authoritative content: explicit unresolved identity conflict. Preserve both conflicting materials and expose an unresolved identity conflict condition.

## Phase 7 - Citation Requirements
Citations must reference the target's opaque portable identity. This supports whole-entry citation that survives partial export, relocation, and schema evolution. If a target is missing from a partial export, the citation remains perfectly intact (dangling reference), which is historically correct.

## Phase 8 - Provenance Requirements
* **Grade A/B/C/D**: All require a portable entry identity to be referencable when they are independently referenceable archive material. Citations and relationships reference portable entry identities.
* **Relationship objects / Manifests**: Preservation Grades do not automatically apply to relationship objects. The architecture question RELATIONSHIP_ASSERTION_IDENTITY_MODEL_UNRESOLVED remains deferred.

## Phase 9 - Privacy and Correlation Threat Model
Opaque identifiers (UUIDv4) prevent:
* Embedding creation timestamps (UUIDv7 fails this)
* Device identifiers (MAC addresses)
* Account correlation
Opaque random identifiers prevent third parties from determining when a record was created or what device created it just by looking at the identifier.

## Phase 10 - Identity Failure Model
* **Duplicate ID / Identical Content**: identity-equivalent material; preserve all non-identical surrounding archival context. Coalesce material only if non-identical context remains preserved.
* **Duplicate ID / Different Content**: Explicit unresolved identity conflict. Preserve both conflicting materials.
* **Missing ID**: Fail explicitly. Cannot be cited.
* **Collision Handling**: Collisions are not mathematically impossible. Correct generation depends on a sufficiently strong random source. Suspected or observed identity collision fails explicitly. No timestamp or content comparison may silently repair a collision.

## Phase 11 - Identity Versioning
The serialized identifier is scheme-identifying through its Vitalicast namespace and scheme-version marker. Archival semantics remain defined by the published identity contract. The identifier text alone does not define copy, clone, merge, conflict, provenance handling, relationship handling, or integrity-attestation behavior.

## Phase 12 - 50-Year Survival Test
A URN-prefixed random opaque identifier (urn:vitalicast:entry:v1:8a3b...) is scheme-identifying. An archivist in 2076 will know it is a Vitalicast entry identifier, version 1. The identifier contains no archival time semantics, identifier ordering has no temporal meaning, the UUID value is not a content digest, user identifier, or device identifier. 

## Phase 13 - Recommendation

**PRIMARY RECOMMENDATION**: URN-Prefixed Random Opaque Identifier (e.g., urn:vitalicast:entry:v1:<RFC UUIDv4 canonical textual representation>)
* Uniqueness: Statistical global uniqueness
* Offline/Multi-device: Supported via correct UUIDv4 generation
* Privacy: Maximum (no metadata leakage)

**SECONDARY ALTERNATIVE**: Pure UUIDv4
**REJECTED**: Content-addressed, UUIDv7 (leaks time), Sequential.

**ARCHITECTURE CHALLENGE**
* What if RNG breaks? Collision occurs. Failure mode: Identical IDs with differing content trigger explicit conflict isolation.

## Decision Classification
PORTABLE_ARCHIVE_ENTRY_IDENTITY_DECISION_READY
