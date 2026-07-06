# Manifest Historical Authority Architecture Investigation

## Phase 1 — Current Manifest / Export Inventory
* **Name**: Export manifest / Package inventory
* **Producer**: Vitalicast export service
* **Consumer**: End user, independent reader tools
* **Current purpose**: Provide a list of contents for a single exported archive package.
* **Current authority**: Package-scoped inventory.
* **Whether it claims completeness**: Historically undefined in Beta 2.
* **Whether it is regenerated**: Yes, regenerated upon new exports.
* **Whether it is append-only**: No.
* **Whether it is exported**: Yes.
* **Whether it is integrity-protected**: TBD in Beta 3.
* **Whether it references storageKey**: No, Beta 3 uses portable identity.
* **Whether it references portable identity**: Yes, in Beta 3.
* **Whether absence from it means nonexistence**: No.
* **Whether history proves any stronger semantics**: No, Beta 2 exports are simply data dumps.

## Phase 2 — Manifest Authority Questions
A. Describe material physically present in one package? **CURRENT_PACKAGE_CONCERN**
B. Describe all entries currently active? **BOTH** (but risky if partial)
C. Prove entry existed historically? **HISTORICAL_AUTHORITY_CONCERN**
D. Omission prove entry never existed? **HISTORICAL_AUTHORITY_CONCERN**
E. Can be regenerated after disposition? **CURRENT_PACKAGE_CONCERN**
F. Can be amended? **BOTH**
G. Two valid manifests disagree? **CURRENT_PACKAGE_CONCERN** (partial exports)
H. Partial export have its own manifest? **CURRENT_PACKAGE_CONCERN**
I. Package copy preserve manifest? **BOTH**
J. Clone produce new manifest? **BOTH**
K. Imported package preserve manifest? **BOTH**
L. Merge preserve source manifests? **BOTH**
M. Manifest cite another manifest? **NOT_REQUIRED**
N. Require portable identity? **ARCHITECTURE_DECISION_REQUIRED**
O. Require integrity attestations? **ARCHITECTURE_DECISION_REQUIRED**
P. Manifest time authoritative? **CURRENT_PACKAGE_CONCERN**
Q. Manifest ordering carry semantics? **NOT_REQUIRED**
R. Unknown future version preserved? **BOTH**
S. Archive history understandable if only manifests/entries survive? **HISTORICAL_AUTHORITY_CONCERN**
T. Survive without Vitalicast? **CURRENT_PACKAGE_CONCERN**

## Phase 3 — Distinguish Package Inventory from Historical Ledger
**Model Evaluated**: MODEL C (Package Manifest only; historical authority lives in entry/relationship/disposition artifacts).
A central "Historical Archive Ledger" creates severe architectural tension with the Two-Scope disposition policy. If an unreferenced entry can be fully destroyed without a tombstone, an immutable historical ledger would either prevent that destruction or require rewriting history.

## Phase 4 — Completeness Claims
A package manifest claims: "This manifest inventories the material intentionally included in this package under manifest scheme X."
It makes **no** claims of "complete life history" or "authoritative reality". Missing files simply mean they are not in this package.

## Phase 5 — Disposition Interaction
* **Unreferenced Entry Disposition**: Removed entirely. A newly generated package manifest simply omits it. Since no historical artifact records it (no tombstone), it is indistinguishable from "never existed" to future readers, aligning perfectly with full User Sovereignty over unreferenced material.
* **Referenced Entry Disposition**: Minimal tombstone remains. The package manifest includes the tombstone (as a valid entry) to preserve historical honesty.
* **Archive-Wide Destruction**: The archive continuity ends. No internal manifest is retained, only external destruction receipts if applicable.

## Phase 6 — Partial Export Semantics
The package manifest explicitly supports partial exports. Omission of an entry means "not included in this package", not "never existed".
* **Package Scope**: `selected_subset` or `current_archive_view`. 

## Phase 7 — Copy, Clone, Import, Merge
* **COPY**: Exact package manifest is preserved.
* **CLONE**: New archive creates its own future package manifests; original manifests are retained as provenance if included.
* **IMPORT**: Source manifest is preserved as package provenance (Grade D or non-graded evidence), not rewritten.
* **MERGE**: Source manifests survive. The merged package receives a new package manifest detailing the combined current inventory.

## Phase 8 — Portable Identity Interaction
Package manifests list portable archive entry identities. Package identity itself (if required) is distinct from entry identity, but not strictly necessary unless tracking exports globally. Do not reuse `storageKey`.

## Phase 9 — Integrity Contract Interaction
The package manifest references explicit integrity attestations (algorithm, canonicalization, digest). It identifies unsupported structures. Hash agility remains append-only on the entries themselves.

## Phase 10 — Historical Authority Failure Model
* **Missing entry in manifest**: Package is incomplete, but history is not rewritten.
* **Conflicting historical assertions**: Handled at the entry/relationship level, not by manifest majority voting.

## Phase 11 — Privacy and Metadata Leakage
A central Historical Archive Ledger leaks entry counts, cadence, and deleted-entry existence (violating unreferenced-entry disposition rules). A Package Manifest only leaks what is intentionally exported in the package.

## Phase 12 — 50-Year Archivist Test
An archivist in 2076 can read the package manifest to verify if they have all files *from that specific export event*. They rely on Grade B/C relationships and minimal tombstones to reconstruct history, avoiding the assumption that a single manifest defines the complete universe.

## Phase 13 — Model Challenge
**MODEL C** survives partial exports, archive merges, and unreferenced entry disposition without contradictions. A central ledger (MODEL B) fails the unreferenced-entry disposition test because it would require rewriting the immutable ledger.

## Phase 14 — Recommendation
**PRIMARY RECOMMENDATION**: MODEL C (Package Manifest only).
* **Package manifest role**: Inventory of current export.
* **Historical ledger role**: None (rejected).
* **Completeness claim**: Package-scoped only.
* **Disposition interaction**: Omitted if unreferenced, tombstone included if referenced.

## Phase 15 — Dependency Result
Historical archive authority can be fully derived from:
* Archive entries (Grade A)
* Disposition assertions (tombstones)
* Relationship assertions (Grade B/C)
* Integrity attestations
No separate Historical Archive Ledger is required. MODEL C is selected.

## Phase 16 — Decision Classification
**MANIFEST_HISTORICAL_AUTHORITY_DECISION_READY**
