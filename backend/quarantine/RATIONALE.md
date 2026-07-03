# Quarantine Rationale

The following components were removed from the Cortex Core repository during the Universal Epistemological Ledger migration:

### ai_sidecar.py
**Reason:** Agent runtime and execution code. Cortex Core is an epistemological ledger, not an agent framework. Agents operate as external actors writing to the ledger, not built-in components.

### advisor_contract.py
**Reason:** Governance and agent interface logic. Belongs in an external product or agent module, not the core ledger.

### action_mediation.py
**Reason:** Enforces action policy execution. Cortex Core only enforces epistemological invariants (e.g. claims must have evidence), not domain-specific action mediation.

### operational.py
**Reason:** Contains kill-switch and deployment logic. This is product-level or infrastructure-level code, outside the scope of the core ledger.

### export.py
**Reason:** Obsidian export logic. UI and export formatting are interface concerns that sit above the Universal Epistemological Ledger.
