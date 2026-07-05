# Sprint 8: Archive Presentation Compatibility and Schema Evolution Safety

## Archive Identity Cohort vs. Certified Payload Schema

Vitalicast fundamentally separates **Archive Identity Cohort** from **Certified Payload Schema**:

1. **Archive Identity Cohort**: Determined by authoritative native enumeration (e.g., storage key prefix `vitalicast_canonical_` or `vitalicast_addendum_`). This proves the record is an authentic archive member and dictates its lifecycle/neutral display. It **does not** prove the shape of the exact-read payload.
2. **Certified Payload Schema**: Determined strictly by examining the parsed payload content against a `SchemaCompatibilityRegistry`. Only payloads that explicitly match a certified, producer-proven shape receive structural presentation support.

## Schema Inventory & Producer Evidence

During Phase 1, we audited all archive producer paths across the frontend repository and native shell.

### Producer-Proven Schema Families
* **`telemetry_batch`**: Proven by `src/modules/vitalicast/batching/TelemetryBatcher.ts`, which actively constructs and flushes a payload with `domain: 'vitalicast'`, `type: 'telemetry_batch'`, `timestamp` (string), and `samples` (array of objects with `timestamp` string and `heartRate` number).

### Reachable Identity Cohorts with Unproven Payload Schemas
* **`telemetry_addendum`**: Enumeration actively returns `vitalicast_addendum_` prefixed keys (a reachable identity cohort). However, **no actual production writer** constructs a `telemetry_addendum` payload. The schema interface in `schema.ts` is not sufficient proof. Thus, the payload schema is classified as **REACHABLE_IDENTITY_COHORT_PAYLOAD_SCHEMA_UNPROVEN**.

## Schema Compatibility Registry

We defined `SchemaCompatibilityRegistry` as the single deterministic compatibility authority.

### Certified Schema Identities
* `telemetry_batch_legacy_signature_1`: Derived exactly from `TelemetryBatcher.ts`.

### Explicit Rules
* **Exact Domain/Type Requirement**: `domain` must strictly be `'vitalicast'`, `type` must strictly be `'telemetry_batch'`.
* **Required Top-Level Fields**: `domain` (string), `type` (string), `timestamp` (string), `samples` (array).
* **Nested Structure Policy**: Closed. Each sample must have exactly `timestamp` (string) and `heartRate` (number). Any missing, mistyped, or extra fields in the nested structure result in a fail-closed schema mismatch.
* **Additive Top-Level Policy**: Open. Unknown top-level fields (e.g., `newSymptom`) are permitted as long as all required fields perfectly match the signature. These fields are preserved and rendered as "Additional archived fields".
* **Ambiguity Result**: Fail-closed. If a payload misses a `type` but has `samples`, it fails closed. It does not guess.

### Versioning Rule
Because historical `telemetry_batch` payloads do not possess an explicit `schemaVersion` or equivalent discriminator, an uncertified version discriminator contract (e.g. encountering a new `schemaVersion` field) fails closed if it violates the existing closed nested structure or is an unhandled explicitly defined version field. We enforce fail-closed for any encountering of unhandled `['schemaVersion', 'schema_version', 'version', 'formatVersion', 'revision']` fields to prevent silent structural presentation of a structurally incompatible future version.

## Golden Fixtures

We established immutable golden fixtures in `src/modules/vitalicast/core/schema/fixtures/`:
* `golden_telemetry_batch.json`: Traces directly to `TelemetryBatcher.ts` production behavior.

*Note: No golden fixture exists for `telemetry_addendum` because no producer evidence exists for its payload shape.*

## Presentation Provenance Safety

When `StructuralSchemaRenderer` receives a payload that successfully matches a certified registry entry, it displays:
> "Presented from the original archived payload. No archived values were changed."

When a payload fails closed to `structurally_unknown_payload` (including all `telemetry_addendum` payloads currently), it displays:
> "Structural presentation is not available for this archived payload. The archived payload remains available for read-only inspection."

## Unresolved Forward Schema Identity Question
Currently, we rely on implicit structural signatures (duck-typing the exact required fields). Future writers should introduce an explicit, certified `schemaVersion` or `schema_id` discriminator to simplify schema evolution without relying exclusively on structural shape inference.
