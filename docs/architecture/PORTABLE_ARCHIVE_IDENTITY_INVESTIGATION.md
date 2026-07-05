# Portable Archive Entry Identity Architecture Investigation

## Phase 1 — Current Identity Inventory
**storageKey**
* **Producer:** Caller of `createSecureRecord` / `appendAddendum`
* **Consumer:** Native Secure Storage plugin, `ArchiveKeyListProvider`, exact readers
* **Format:** `vitalicast_canonical_{recordId}` or `vitalicast_addendum_{recordId}_{addendumId}`
* **Scope of Uniqueness:** Device-local native secure storage namespace
* **Persistence Boundary:** Application storage boundary
* **Payload Inclusion:** No (`VitalicastBatchPayload` contains no explicit `recordId`)
* **Exported:** Not currently exported (Beta 2 export boundary remains undefined for identity)
* **Human-Visible:** Strictly prohibited (Sprint 6 requirement)
* **Mutable:** Value itself is immutable; but the identity is not bound cryptographically to the content
* **Collision Assumptions:** Relies on application-provided uniqueness for `recordId` and `addendumId`
* **Implementation Meaning:** An internal, device-local exact-read implementation identifier only

**Conclusion on storageKey:** It is an internal exact-read pointer. It cannot serve as the portable long-lived archive identity.

## Phase 2 — Portable Identity Requirements
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
* T. **Duplicate content**: ARCHITECTURE_DECISION_REQUIRED (Should identical payloads on different devices share identity?)
* U. **Identical timestamps**: MUST_SURVIVE
* V. **Offline creation**: MUST_SURVIVE
* W. **Multiple-device creation**: MUST_SURVIVE
* X. **Clock drift**: MUST_SURVIVE
* Y. **Clock rollback**: MUST_SURVIVE
* Z. **Future application replacement**: MUST_SURVIVE

## Phase 3 — Identity Versus Content Integrity
Identity and Content Digest MUST remain separate concerns.
1. Two independent source records contain byte-identical content: They are two distinct archival entries if generated at different times or contexts.
2. A Grade B addendum contains exactly the same text: Identity must remain distinct.
3. Hash algorithm is upgraded: Identity remains unchanged; attestations are added.
4. New integrity attestation added: Identity remains unchanged.
5. Copied entry: Retains identity.
6. Citation graph changes: Entry identity remains unchanged.
7. Addendum appended: Original identity remains unchanged.

## Phase 4 — Identity Model Candidates
**1. RANDOM OPAQUE IDENTIFIER (UUIDv4-like)**
* Uniqueness: Statistically globally unique
* Offline: Excellent
* Merge behavior: Excellent, zero-collision assumption
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

## Phase 5 — Archive Identity Context
Portable Archive Entry Identity must be **GLOBALLY UNIQUE** (statistically).
Archive namespaces require authorities, and when archives are merged, split, or cloned, namespaces fracture. Opaque, globally unique entry identifiers allow entries to float freely across boundaries, exports, and imports without namespace resolution failures.

## Phase 6 — Copy, Clone, Import, and Merge Semantics
* **COPY**: An exact duplicate. Retains identical entry identity. Two archives with identical entries are just two locations of the same historical entity.
* **CLONE**: An independently evolving archive initialized from existing material. Entries retain original identity.
* **IMPORT**: Bringing external material into an archive. Retains original identity if generated by Vitalicast. Collisions are handled as identical entities if bytes match, or conflicts if bytes differ.
* **MERGE**: Two archive histories combined. Identical entry IDs with identical content deduplicate. Identical IDs with conflicting content raise a structural failure (unresolved conflict).

## Phase 7 — Citation Requirements
Citations must reference the target's opaque portable identity. This supports whole-entry citation that survives partial export, relocation, and schema evolution. If a target is missing from a partial export, the citation remains perfectly intact (dangling reference), which is historically correct.

## Phase 8 — Provenance Requirements
* **Grade A/B/C/D**: All require a portable entry identity to be referencable.
* **Relationship objects / Manifests**: Require their own identities if they are first-class archive entries (e.g., formal Grade B links). Integrity attestations do not strictly require independent identity unless treated as separate archival entries.

## Phase 9 — Privacy and Correlation Threat Model
Opaque identifiers (UUIDv4) prevent:
* Embedding creation timestamps (UUIDv7 fails this)
* Device identifiers (MAC addresses)
* Account correlation
Opaque random identifiers prevent third parties from determining when a record was created or what device created it just by looking at the identifier.

## Phase 10 — Identity Failure Model
* **Duplicate ID / Identical Content**: Deduplicate transparently.
* **Duplicate ID / Different Content**: Critical failure. Identity fork. Preserve both as conflicting, do NOT merge or choose oldest/newest.
* **Missing ID**: Fail explicitly. Cannot be cited.

## Phase 11 — Identity Versioning
Identity scheme should be self-describing through a URN-like prefix (e.g., `urn:vitalicast:entry:v1:[uuid]`). This avoids forcing the interpreter to assume the identity type, satisfying the 50-year survival test.

## Phase 12 — 50-Year Survival Test
A URN-prefixed random opaque identifier (`urn:vitalicast:entry:v1:8a3b...`) is completely self-describing. An archivist in 2076 will know it is a Vitalicast entry identifier, version 1, and the opaque value carries no hidden time or device semantics. 

## Phase 13 — Recommendation

**PRIMARY RECOMMENDATION**: URN-Prefixed Random Opaque Identifier (e.g., `urn:vitalicast:entry:v1:<UUIDv4>`)
* Uniqueness: Global
* Offline/Multi-device: Perfect
* Merge/Copy: Zero collision
* Privacy: Maximum (no metadata leakage)
* Versioning: Self-describing via URN

**SECONDARY ALTERNATIVE**: Pure UUIDv4 (relies on external manifest for versioning, slightly less self-describing).
**REJECTED**: Content-addressed (violates hash agility), UUIDv7 (leaks time), Sequential (fails merge).

**ARCHITECTURE CHALLENGE**
* What if RNG breaks? Collision occurs. Failure mode: Identical IDs with differing content trigger conflict isolation.
* What if Vitalicast dies? The URN prefix remains globally understandable and statistically unique.

## Decision Classification
PORTABLE_ARCHIVE_ENTRY_IDENTITY_DECISION_READY
