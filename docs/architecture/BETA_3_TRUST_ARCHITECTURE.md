# Beta 3 Trust Architecture

## Foundation Model
The architecture synchronizes around five durable foundations:
1. **Archive Material / Source Content**: Preserved user source records, addenda, derivations, and external/imported material under explicit provenance boundaries (Grades A-D).
2. **Archive Relationships**: A narrow conceptual relationship layer equivalent to `appended_to`, `cites`, and `derived_from`.
3. **Integrity Attestations**: Verification mechanism defining the target identity, algorithm, canonicalization, and digest.
4. **Portability and Archive Identity**: Separation of runtime exact-read identity (storageKey) from the portable permanent archive entry identity.
5. **Self-Describing Export**: The archive remains fully intelligible without the current Vitalicast application or cloud services.

## Grade A Canonical Source Record
A Grade A source record encompasses user-authored source material after sealing.
The architecture implements a **record stance** property:
- `observational`
- `prospective` (A first-class stance oriented toward a future or unresolved state)
- `unspecified` (for legacy material where appropriate)

Descriptive kinds (e.g., intention, goal, prediction) are secondary vocabulary. Vitalicast does not implement an eight-object taxonomy or taxonomy engine.

## Temporal Honesty
A prospective stance does not automatically certify that the record existed before the eventual outcome. The architecture explicitly separates capture time, seal time, user-asserted reference time, and eventual event time. There is no "prospective truth" semantics.

## Beta 2 Legacy Classification
Existing Beta 2 source records remain unchanged. The architecture forbids retroactive semantic reclassification, keyword-based taxonomic inference, or mass-upgrades of legacy Beta 2 payloads. Beta 2 source material remains source material under Grade A provenance rules with an unspecified stance.

## Relationships & First-Class Citations
Later outcomes or reflections remain append-only Grade B material related via a neutral `appended_to` relationship. 
First-Class Citations identify the citing archive entry, the cited portable archive entry identity, relationship kind, and creation context. 
Scope prioritizes whole-entry citation. No character-offset or JSON Pointer citation is required initially.
Causal relationships (e.g. `outcome_of`) are explicitly not required core relationships.

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
* **Weakness/Deferred Decision**: The specific portable archive-level identity (independent of `storageKey`) remains an unresolved prerequisite architecture decision that must survive export and device change.
* **Migration Hazard**: Future implementations must be extremely careful to avoid implicit classification of "unspecified" Beta 2 records.
