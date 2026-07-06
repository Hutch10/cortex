# Package Digest Identity Precision Closure

## 1. Scope
Determine whether the accepted `PACKAGE_IDENTITY_NOT_REQUIRED_DECISION_READY` result is internally precise or whether content digest terminology silently reintroduced package identity. Clarify exactly what a digest identifies or attests to, distinguishing between representation equality, logical equivalence, historical sameness, and custody continuity.

## 2. Repository Truth
* **Branch**: main
* **HEAD**: `51579b9`
* **Prior Decision**: Model A (Package Identity Not Required) was accepted. However, terminology such as "packages are identified solely by their content digest" and "new bytes mean new package identity" was erroneously used, effectively conflating representation equality with metaphysical package identity.

## 3. Prior Decision Under Review
The substantive rejection of random package identity (Model A) is upheld. The phrasing surrounding content digests acting as identity is under precision review.

## 4. Assertion Taxonomy
* **A. Package entity identity**: ("These refer to one persistent package entity"). **UNSUPPORTED**. Packages have no persistent metaphysical identity.
* **B. Export-event identity**: ("These outputs arose from the same export operation"). **UNSUPPORTED**. Vitalicast does not track export events.
* **C. Representation equality**: ("The exact hashed byte representation is equal under algorithm A"). **SUPPORTED**. A physical digest asserts this.
* **D. Canonical-content equality**: ("The canonicalized content is equal under contract C"). **SUPPORTED**. A canonical digest asserts this.
* **E. Logical inventory equivalence**: ("The package inventories represent equivalent logical archive material"). **SUPPORTED**. Proven by manifest logical contents.
* **F. Historical ancestry**: ("Package B descended from Package A"). **UNSUPPORTED**. Ancestry exists strictly between **entries** (Grade B/C relationships), not packages.
* **G. Custody continuity**: ("Material remained within one traceable chain"). **SUPPORTED conditionally**, via Grade D external provenance artifacts. Not proven by digests internally.
* **H. Provenance observation**: ("At event E, material matching digest D was observed"). **SUPPORTED**, via provenance assertions.

## 5. A–Z Answer Audit
Prior answers improperly used "identity" to describe integrity/content equivalence:
* **C. Exact copy preserve identity?** -> `TERMINOLOGY_IMPRECISE`. Correction: An exact copy produces *representation equality*. It does not preserve identity because package identity does not exist.
* **G. Changing compression preserve identity?** -> `TERMINOLOGY_IMPRECISE`. Correction: Changing compression produces a different *physical representation digest*, though it may retain logical inventory equivalence.
* **H. Manifest regeneration create new package identity?** -> `TERMINOLOGY_IMPRECISE`. Correction: It creates a new *representation digest*.
* **I. Re-export create new package identity?** -> `TERMINOLOGY_IMPRECISE`. Correction: It generates a new *representation digest*.
* **J. Disposition re-export create new package identity?** -> `TERMINOLOGY_IMPRECISE`. Correction: It generates a new *representation digest*.
* **L. Same entry set but different identities.** -> `TERMINOLOGY_IMPRECISE`. Correction: Same entry set but different *representation digests*.
* **M. Same identity but differing bytes impossible.** -> `TERMINOLOGY_IMPRECISE`. Correction: Same *representation digest* with differing bytes is impossible (assuming collision resistance).
* **P. Source package digest remains static / source package identity survives.** -> `AUTHORITY_OVERCLAIM`. Correction: The *observed representation digest* survives as a provenance record. It is not an identity.
* **R. Merge preserves source package identities as provenance digests.** -> `TERMINOLOGY_IMPRECISE`. Correction: Merge may preserve source *representation digests* as provenance.
* **S. Merged output receives new package identity.** -> `TERMINOLOGY_IMPRECISE`. Correction: Merged output yields a distinct *representation digest*.
* **U. Package identity inferred from manifest digest.** -> `AUTHORITY_OVERCLAIM`. Correction: Manifest digest establishes *canonical-content equality* of the manifest, not package identity.
* **V. Package identity can be content-addressed.** -> `CONTRADICTS_MODEL_A`. Correction: Physical integrity is content-addressed. Package identity is explicitly rejected.
* **W. Unsupported future structures retain identity.** -> `TERMINOLOGY_IMPRECISE`. Correction: They retain *representation equality* through physical digests.

## 6. Digest-as-Identity Falsification
A cryptographic digest is NOT an identity. It is a property of a bitstring (representation).
* 1. Two byte-for-byte copies share representation equality, but Vitalicast cannot prove they share custody or historical event ancestry.
* 4. Two independent exports producing identical bytes share representation equality. They do NOT share the same export event.
* A digest establishes representation/content equality. It is not a persistent entity identifier.

## 7. Exact-Copy Precision
**Prior statement**: "A byte-for-byte copy results in the exact same physical package."
**Correction**: "A byte-for-byte copy yields a digest-equivalent representation."
Vitalicast cannot know a copy occurred. Byte equality proves representation equality, NOT historical sameness, custody continuity, or ancestry. "Same physical package" is a metaphysical claim the system cannot establish.

## 8. Provenance Digest Semantics
**Selected Model**: **MODEL P2 — Digest as observed representation reference**.
A provenance assertion recording digest D means: "source material observed matched digest D under contract C."
It does NOT mean "source package D, a persistent package entity" (Model P1). A digest proves content state only.

## 9. Physical vs Canonical Digest Scope
The current architecture has **UNRESOLVED** implementation details regarding whether the "package digest" means the physical ZIP bytes or a canonical logical Merkle root.
Statements like "new bytes mean a new package digest" are precise ONLY if referring to the *physical representation digest*. Canonical digest scope remains deferred.

## 10. Disposition/Privacy Pressure Test
If P2 contains a provenance artifact citing physical digest D for P1 (where P1 contained unreferenced entry E1), the digest D itself is an opaque hash. It does not leak E1's past existence.
However, if the system mandates the retention of P1's *manifest* as a Grade D artifact just to prove P2's lineage, that creates a backdoor ledger.
**Correction**: Retention of source manifests as Grade D provenance is explicitly **OPTIONAL/VOLUNTARY**. Vitalicast does NOT mandate retention of source package manifests to build a lineage graph.

## 11. Allowed Vocabulary
* **package identity**: PROHIBITED.
* **export-event identity**: PROHIBITED.
* **package lineage**: PROHIBITED (unless explicitly asserted by an authorized external provenance artifact).
* **representation digest**: ALLOWED.
* **canonical content digest**: ALLOWED.
* **digest equivalence**: ALLOWED.
* **logical inventory equivalence**: ALLOWED.
* **historical sameness / ancestry**: REQUIRES EXPLICIT CONTEXT (authorized strictly by Grade B/C entry relationships, never by package digests).

## 12. Surviving Assumptions
* Content digests (integrity attestations) are sufficient to identify physical representation and canonical content.
* Entry relationships (Grade B/C) are sufficient to capture historical lineage.

## 13. Unresolved Dependencies
* The exact scope and canonicalization contract for package/manifest digests (Physical ZIP hash vs. Canonical Merkle root).

## 14. Required Canonical Corrections
* Narrow updates to `PACKAGE_IDENTITY_AND_EXPORT_LINEAGE_INVESTIGATION.md`, `BETA_3_TRUST_ARCHITECTURE.md`, `BETA_3_IMPLEMENTATION_PLAN.md`, and `ARCHITECTURE_EVIDENCE_DECISION_REGISTER.md` to remove any implication that a digest serves as an "identity" for a package.

## 15. Final Precision Classification
**PACKAGE_DIGEST_IDENTITY_PRECISION_CLOSED**
