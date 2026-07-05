# Vitalicast Governance Constitution

## Mission
Vitalicast is:
"Infrastructure for trustworthy personal recordkeeping over the course of a lifetime."

Vitalicast exists to preserve lived experience with verifiable integrity, giving individuals enduring ownership of their observations while enabling transparent, reproducible exploration of patterns without rewriting history or substituting algorithmic judgment for human memory.

## Historical Context Doctrine
Vitalicast preserves statements in their historical context; it does not promote the propositions within those statements to fact.

## Constitutional Principles
1. **User Sovereignty**: Users retain enduring ownership and ultimate authority over their archive.
2. **Observational Fidelity**: Lived experiences and source statements are preserved exactly as observed or authored.
3. **Transparent Derivation**: Any algorithmic analysis or insight generated from source material must remain non-canonical, explicit in its methods, and clearly distinguishable from source material.
4. **Explicit Provenance**: Every entry in the archive must possess clear lineage and boundaries.
5. **Explainability**: Archival relationships and structures must remain comprehensible independently of opaque mechanisms.

## Preservation Grades (Provenance Boundaries)
A grade describes provenance and preservation relationship, not truth, accuracy, medical validity, confidence, or archive integrity. A Grade A source record may contain a mistaken belief and still remain Grade A.

* **Grade A**: User-authored source records preserved as canonical historical material after sealing.
* **Grade B**: Append-only user-authored material explicitly related to existing archive material and preserved without rewriting the referenced source.
* **Grade C**: Derived analyses that remain non-canonical, explicitly cite source material, and preserve sufficient method identity, version, and parameters to support reproduction or determination that reproduction is no longer possible.
* **Grade D**: Externally sourced or imported material preserved with explicit source provenance and acquisition context.

## Public Stability Promise
This is a narrow governance commitment to guarantee the durability of the Life Archive.
1. Original archived source material will not be silently rewritten.
2. Later user additions remain distinguishable from original source material.
3. Derived analyses remain distinguishable from canonical source material.
4. Standard independent exports will not knowingly require proprietary Vitalicast cloud access for interpretation.
5. Unsupported archive structures will be identified rather than guessed, and published archive format contracts will remain documented under the project's preservation policy.

## Principles vs Implementation Separation
There is an explicit architecture separation between:
1. **Constitutional Principles**: Long-lived invariants.
2. **Architecture Contracts**: Format, identity, provenance, relationship, integrity, and export rules that implement the principles.
3. **Current Implementation**: Current technology choices and application mechanics (e.g., React, Supabase, SHA-256). No current implementation detail is promoted into the Constitution.
