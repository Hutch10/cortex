# Package Identity and Export Lineage Authority Investigation

## 1. Scope
Determine whether Vitalicast export packages require a portable package identity and define exactly what identity means across package operations. Ensure no accidental reuse of `storageKey` or other metadata as package identity.

## 2. Existing Repository Truth
* **Branch**: main
* **HEAD**: `606909e`
* **Existing package identity behavior**: `packageId` and `exportId` are virtually non-existent in the codebase. Beta 2 exports are simply data dumps. The `MANIFEST_HISTORICAL_AUTHORITY_INVESTIGATION.md` explicitly noted that "Package identity itself (if required) is distinct from entry identity, but not strictly necessary unless tracking exports globally."

## 3. Identity Taxonomy
* **A. Archive identity**: The portable identity of an archive or archive lineage (if defined).
* **B. Entry identity**: The portable identity of an archive entry (`urn:vitalicast:entry:v1`).
* **C. Package identity**: The identity of one particular exported package.
* **D. Manifest identity**: The identity of the manifest document itself.
* **E. Package lineage**: Describing one package as derived, copied, or merged from another.

* `archive identity == package identity`? **NO**. An archive can produce infinite, distinct packages (including partial exports).
* `package identity == manifest identity`? **UNRESOLVED/NOT_REQUIRED**. If a package needs no identity, the manifest's content hash establishes the representation equality of the manifest itself.
* `manifest digest == manifest identity`? **YES**. Content-addressing is the safest identification for static artifacts.
* `package digest == package identity`? **YES**. Content-addressing perfectly establishes representation equality of the physical package.
* `entry identity == storageKey`? **NO**. Explicitly rejected in Beta 3 Trust Architecture.

## 4. Questions A–Z
* **A.** Every export require package identity? **NO**.
* **B.** Package exist without package identity? **YES**.
* **C.** Exact copy preserve identity? **TERMINOLOGY IMPRECISE**. An exact copy produces representation equality. It does not preserve identity because package identity does not exist. (if content-addressed, bytes are identical).
* **D.** Rename preserve identity? **YES** (filename is outside the logical package).
* **E.** Transport preserve identity? **YES**.
* **F.** Changing outer FS metadata preserve? **YES**.
* **G.** Changing compression preserve identity? **TERMINOLOGY IMPRECISE**. Changing compression yields a distinct physical representation digest..
* **H.** Manifest regeneration create new package identity? **TERMINOLOGY IMPRECISE**. It creates a distinct representation digest..
* **I.** Re-export same state create new package identity? **TERMINOLOGY IMPRECISE**. It generates a distinct representation digest. (timestamps or new signatures change bytes).
* **J.** Re-export after unrelated entry disposed create new package identity? **TERMINOLOGY IMPRECISE**. It generates a distinct representation digest..
* **K.** Partial export require own package identity? **NO** (it just has a different manifest digest).
* **L.** Two packages contain same entry set but different identities? **TERMINOLOGY IMPRECISE**. Same entry set, differing representation digests. (exported at different times).
* **M.** Two packages same identity but differing bytes? **TERMINOLOGY IMPRECISE**. Same representation digest with differing bytes is impossible (assuming collision resistance). (impossible if content-addressed; if random ID, yes, which is dangerous).
* **N.** Two manifests describe same package? **YES** (e.g., different format manifests).
* **O.** One manifest describe multiple packages? **NO**.
* **P.** Import preserve source package identity? **AUTHORITY OVERCLAIM**. The observed representation digest survives as a provenance record. It is not an identity..
* **Q.** Clone preserve source package identity? **TERMINOLOGY IMPRECISE**. Clones initialize from entries; future exports yield distinct representation digests. (clones generate new packages).
* **R.** Merge preserve source package identities? **TERMINOLOGY IMPRECISE**. Merge may optionally preserve source representation digests as provenance..
* **S.** Merged output receive new package identity? **TERMINOLOGY IMPRECISE**. Merged output yields a distinct representation digest. (it is a new set of bytes).
* **T.** Inferred from archive identity + timestamp? **NO** (partial exports can occur simultaneously).
* **U.** Inferred from manifest digest? **AUTHORITY OVERCLAIM**. Manifest digest establishes canonical-content equality, not package identity..
* **V.** Package identity can be content-addressed? **CONTRADICTS MODEL A**. Physical integrity is content-addressed. Package identity is explicitly rejected..
* **W.** Unsupported future structures retain identity? **TERMINOLOGY IMPRECISE**. Retain representation equality through physical digests. (digests don't require semantic parsing).
* **X.** Package lineage survive without Vitalicast? **YES** (via nested provenance manifests).
* **Y.** Package identity create privacy leakage? **YES**, if a random UUID is used, it acts as a global tracking beacon.
* **Z.** Conflict with full destruction? **YES**, if package lineage is tracked in a ledger, it forces retention of export events that may leak deleted unreferenced entries.

*(Concerns fall strictly under `INTEGRITY_CONCERN`, `DISPOSITION_CONCERN`, or `NOT_IDENTITY_BEARING`.)*

## 5. Candidate Models Evaluated
* **MODEL A — No package identity**: Packages possess representation equality established by content digests. Lineage exists between entries, not packages.
* **MODEL B — Random portable package identity**: Rejected. Acts as a tracking identifier and leaks export cadence.
* **MODEL C — Content-addressed package identity**: The canonical package digest or manifest digest establishes only representation equality.
* **MODEL D — Manifest-addressed package identity**: A subset of Model C.
* **MODEL E — Dual identity**: Rejected. Unnecessary complexity.
* **MODEL F — Archive-scoped export sequence**: Rejected. Leaks export counts and forces a centralized counter.

## 6. Identity vs Integrity Distinction
* “These are the same historical package”: **Historical/package identity**. If packages have no random identity, this claim does not exist. A package is a transport vessel, not a historical entity.
* “These package contents are byte-for-byte identical”: **Physical/content integrity** (Digest equivalence).
* “These packages contain equivalent logical archive material”: **Logical inventory equivalence** (Manifest entry list equivalence).
The architecture explicitly delegates historical authority to **Entries** and **Relationships**. Packages do not need historical identity.

## 7. Exact Copy Semantics
If P1 is copied byte-for-byte, it yields a digest-equivalent representation. Vitalicast does not know a copy occurred, nor should it. A copy is a custody/transport event, not an architectural identity event.

## 8. Re-Export Semantics
If Archive A exports P1, and later exports the same logical material, the new package P2 will have a new manifest (due to time/context changes) and a new digest. It is content-distinct, logical-equivalent, and has NO lineage relationship to P1. Packages do not have children.

## 9. Import and Clone Semantics
When P1 is imported, its manifest and entries are ingested. An observed digest of P1 is recorded as provenance. The import event does not "become" the archive identity. Clone operations initialize from entries, not packages; future exports from the clone are entirely new packages.

## 10. Merge Semantics
Merging Archive A and Archive B results in a new current inventory. The source manifests from A and B may be retained as Grade D provenance (recording their observed representation digests), but the merged package has no random identity. No "package lineage" graph is generated.

## 11. Disposition and Privacy Pressure Test
If unreferenced entry E1 is disposed, a new export P2 omits E1.
If package lineage (P2 derived from P1) were enforced, P2 would cite P1. Citing P1 would leak that P1 existed, and inspecting P1 would reveal E1. Thus, **package lineage forces a backdoor historical ledger**, violating the Two-Scope disposition policy. Model A (No Package Identity/No Package Lineage) completely avoids this.

## 12. 50-Year Archivist Test
In 2076, an archivist finds two packages. They can hash them to prove physical equality. They can read the manifests to prove logical equivalence. They rely on the entry relationships (`appended_to`, `cites`) to understand historical ancestry. They do NOT need a random "Package UUID" to understand the archive. 

## 13. Surviving Assumptions
* Content digests (integrity attestations) are sufficient to establish representation equality for physical packages and manifests.
* Entry identities and relationships are sufficient to capture historical lineage.

## 14. Unresolved Dependencies
None block this decision.

## 15. Primary Recommendation
**MODEL A — No package identity (Content-addressed physical integrity only)**.
Packages are merely transport vessels. They possess content digests for physical integrity but no random historical identity. Package lineage is explicitly NOT tracked, preventing metadata leakage and backdoor ledgers.

## 16. Secondary Alternative
**MODEL C / D** (Manifest-addressed identity), which is practically identical to Model A but formalizes the manifest digest as the package identity.

## 17. Rejected Models
MODEL B, MODEL E, MODEL F. All introduce tracking identifiers or backdoor ledgers.

## 18. Implementation Consequences
Do not generate random UUIDs for exports. Do not track `exportId`. Use content digests when provenance must refer to a specific external package.

## 19. Final Architecture Classification
**PACKAGE_IDENTITY_NOT_REQUIRED_DECISION_READY**

