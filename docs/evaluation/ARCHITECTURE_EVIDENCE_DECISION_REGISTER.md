# Architecture Evidence Decision Register

| Concept | Current Architecture Status | Relevant Stage 1 Hypothesis | Evidence State | Current Decision | Decision Rationale | Contradictory Evidence | Unresolved Question | Implementation Gate Impact |
|---|---|---|---|---|---|---|---|---|
| Capture | FROZEN_BASELINE | 1. Capture Hypothesis | Pending Data | INSUFFICIENT_EVIDENCE | Stage 1 collection ongoing | N/A | None | Blocks Beta 3 |
| Sealing / Locking | FROZEN_BASELINE | 2. Sealing / Locking Hypothesis | Pending Data | INSUFFICIENT_EVIDENCE | Stage 1 collection ongoing | N/A | None | Blocks Beta 3 |
| Addenda | FROZEN_BASELINE | 3. Addenda Hypothesis | Pending Data | INSUFFICIENT_EVIDENCE | Stage 1 collection ongoing | N/A | None | Blocks Beta 3 |
| Search / Retrieval | FROZEN_BASELINE | 4. Search / Retrieval Hypothesis | Pending Data | INSUFFICIENT_EVIDENCE | Stage 1 collection ongoing | N/A | None | Blocks Beta 3 |
| Export / Ownership | FROZEN_BASELINE | 5. Export / Ownership Hypothesis | Pending Data | INSUFFICIENT_EVIDENCE | Stage 1 collection ongoing | N/A | None | Blocks Beta 3 |
| Prospective Grade A stance | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Preservation Grades | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Provenance Inspector | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Archive Health | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| First-Class Citations | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Canonical/integrity attestations | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Export Independence | Beta 3 Planning | 5. Export / Ownership Hypothesis | Indirect | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Durable schema evolution | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Self-describing manifests | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Public Stability Promise | Beta 3 Planning | N/A | Untested | NOT_TESTED | Unimplemented in Beta 2 | N/A | None | N/A |
| Portable archive entry identity | Beta 3 Planning | N/A | Investigated | DECISION_READY_IMPLEMENTATION_DEFERRED | URN-Prefixed RFC UUIDv4 | N/A | None | Deferred |
| User Disposition Architecture | Beta 3 Planning | N/A | Investigated | DECISION_READY_IMPLEMENTATION_DEFERRED | Two-Scope Model Policy E | N/A | None | Deferred |
| Relationship Assertion Identity | Beta 3 Planning | N/A | Untested | RELATIONSHIP_ASSERTION_IDENTITY_MODEL_UNRESOLVED | Deferred pending architecture resolution | N/A | Should durable archive relationships have independent IDs? | N/A |
| Manifest Historical Authority | Beta 3 Planning | N/A | Investigated | DECISION_READY_IMPLEMENTATION_DEFERRED | Model C (Package Manifest Only) | N/A | None | Deferred |
| Package Identity and Export Lineage | Beta 3 Planning | N/A | Investigated | DECISION_READY_IMPLEMENTATION_DEFERRED | Package Identity Not Required (Model A) | N/A | None | Deferred |
| Package Digest Scope and Canonicalization | Beta 3 Planning | N/A | Investigated | PACKAGE_DIGEST_SCOPE_CANONICALIZATION_DECISION_READY | Model C (Canonical manifest digest + per-material digests) | N/A | None | Deferred |
| Manifest Canonicalization and Digest Anchor | Beta 3 Planning | N/A | Investigated | MANIFEST_CANONICALIZATION_DIGEST_ANCHOR_DECISION_READY | Schema-Normalized Projection + Comparison-Only Anchor | N/A | None | Deferred |

| Comparison-Only Manifest Digest Authority | Beta 3 Planning | N/A | Investigated | COMPARISON_ONLY_MANIFEST_DIGEST_AUTHORITY_CLOSED | Manifest authority is Comparison-Only (Model A4) | N/A | None | Deferred |

| Package Manifest Semantic Schema | Beta 3 Planning | N/A | Investigated | PACKAGE_MANIFEST_SEMANTIC_SCHEMA_DECISION_READY | Hybrid Tagged Union Record Model + No Self-Inventory (Model R5 + M1) | N/A | None | Deferred |

| Manifest Artifact Reference and Multiplicity | Beta 3 Planning | N/A | Investigated | MANIFEST_ARTIFACT_REFERENCE_MULTIPLICITY_DECISION_READY | Manifest-Local Reference + Explicit Assertion Identity (Model M4 + I4) | N/A | None | Deferred |

| Tombstone Minimal State and Assertion Identity | Beta 3 Planning | N/A | Investigated | TOMBSTONE_MINIMAL_STATE_ASSERTION_IDENTITY_DECISION_READY | Canonical Minimal Absence-State (Model T2) | N/A | None | Deferred |

| Merge Authority Tombstone Live Conflict | Beta 3 Planning | N/A | Investigated | MERGE_TOMBSTONE_LIVE_CONFLICT_DECISION_READY | Conflict-Preserving Merge (Model M4) + Assertion-like Conflict Artifact (Model C4) | N/A | None | Deferred |

| Availability Conflict Observation Authority | Beta 3 Planning | N/A | Investigated | AVAILABILITY_CONFLICT_OBSERVATION_AUTHORITY_CLOSED | Conflict state plus observation artifact (Model C4) | N/A | None | Deferred |

| Portable Entry State Conflict Orphan Reconciliation | Beta 3 Planning | N/A | Investigated | ORPHAN_PORTABLE_ENTRY_STATE_ARCHITECTURE_RECONCILED | Delete as scratch/orphan (Model R1) | N/A | None | Deferred |

| Portable Identity & Live Material Reference | Beta 3 Planning | N/A | Investigated | PORTABLE_IDENTITY_LIVE_MATERIAL_REFERENCE_DECISION_READY | portableMaterialIdentity for live material reference; URN UUIDv4 syntax | N/A | None | Deferred |

