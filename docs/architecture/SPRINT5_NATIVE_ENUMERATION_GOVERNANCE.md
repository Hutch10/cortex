# Vitalicast Sprint 5 Native Enumeration Governance

## Sprint 5 Phase 1 Scope
- This phase represents **governance and design only**.
- No native implementation has occurred.
- No `SecItemCopyMatching` implementation for enumeration exists yet.
- The native provider remains strictly `unsupported` / fail-closed.
- No production archive browsing claim is made yet.

## Rejected Alternatives
- **Central Index/Manifest Record:** Unsafe mutation risks and synchronization failures (split brain).
- **UserDefaults Key Tracking:** Brittle, non-secure pairing; orphaned keys or leaked existence.
- **Broad/Wildcard Keychain Scraping:** Security violation; massive threat model expansion.
- **Payload-Reading Enumeration:** Memory bloat and security risk (payloads loaded unnecessarily).
- **Mutation-Based Cleanup or Repair:** Violates strict append-only/create-only invariants.

## Threat Model
- **Overscoped Keychain Queries:** Retrieving other app/framework secrets unexpectedly.
- **Accidental Return of Unrelated App Secrets:** If boundaries aren't strictly filtered.
- **Payload Decryption During Enumeration:** Severe memory pressure and unauthorized plaintext exposure.
- **Memory Pressure from Bulk Data Return:** Parsing payloads for 10,000+ records would crash the app.
- **TOCTOU (Time-of-Check to Time-of-Use):** Enumerated key presence does not prove record integrity until the exact payload is read and manually verified.
- **Bridge Serialization Pressure:** Moving thousands of records across the Capacitor bridge could cause bottlenecks.
- **Legacy Compatibility Risk:** If older records lack the final service attribute, they may become invisible.

## Allowed Future Keychain Query Policy
If native enumeration is built, it **must** adhere strictly to the following bounds:
- `kSecClass` = `kSecClassGenericPassword`
- Strict static `kSecAttrService` boundary. Proposed value: `com.vitalicast.archive`
- `kSecReturnData` = `false` (Critical)
- `kSecReturnAttributes` = `true`
- `kSecMatchLimit` = `kSecMatchLimitAll`
- Swift-side prefix validation must filter exclusively for:
  - `vitalicast_canonical_`
  - `vitalicast_addendum_`
- Return keys/attributes only.
- **Never return payload data.**
- Malformed/foreign keys are ignored, not repaired or deleted.

## Forbidden Future Keychain Behavior
- No payload reads during enumeration.
- No `kSecReturnData = true` in the list path.
- No cross-service/domain queries.
- No broad generic password dump.
- No `SecItemUpdate`.
- No `SecItemDelete`.
- No `delete` / `update` / `clear` / `reset` / `repair` methods.
- No auto-repair of malformed or orphaned keys.
- No verification during enumeration.
- No medical/diagnostic interpretation logic.

## Provider Contract
- The existing `ArchiveKeyListProvider` is structurally sufficient.
- No TypeScript contract change is required in Phase 1.
- Future native implementation may eventually return: `platformAuthority: "native_authoritative"`.
- Current native provider must remain: `platformAuthority: "unsupported"`.
- `rawPayloadReturned` must remain `false`.

## Future Test Vectors
- Bounded retrieval returns only Vitalicast service keys.
- Dummy secret under a different `kSecAttrService` is ignored.
- Payload exclusion verifies `kSecReturnData = false`.
- Prefix filtering drops malformed/foreign account names.
- Empty Keychain returns calm empty array.
- Large archive cap/serialization behavior is measured.
- No `SecItemUpdate` / `SecItemDelete` paths exist.
- Native provider changes to `native_authoritative` only after CI passes.

## CI Certification Requirements
- Requires `macos-latest` runner.
- `npx cap sync ios`
- `xcodebuild build`
- `xcodebuild test`
- XCTest coverage for enumeration bounds.
- No sensitive artifacts in workflow outputs.
- No simulator Keychain artifact upload.
- Sprint 4 certification must remain `PASS`.

## Implementation Gates for Future Phase 2
Future implementation is blocked until GG approves:
1. Final `kSecAttrService` value.
2. Compatibility plan for any existing records lacking that service tag.
3. Maximum returned key count or UI cap strategy.
4. XCTest design.
5. Fail-closed fallback behavior.
6. Documentation update requirements.


## Sprint 5 Phase 2: Service Compatibility Strategy

### Discovered Current Behavior
- **Exact kSecAttrService string:** None. The `kSecAttrService` attribute is currently **omitted** from all Keychain queries.
- **Canonical and Addendum Records:** Both share the same omitted service behavior (via `addKeychainItem`).
- **ReadSecureRecord:** Uses the same omitted service behavior.
- **Current records enumerable under final boundary:** Unknown. Because `kSecAttrService` is omitted, compatibility is unresolved pending macOS/Xcode Keychain behavior audit.

### Preferred Future Compatibility Strategy
**Explicit Service Allowlist / Bounded Service Queries.**

**Rules:**
- Future native enumeration may query only an explicit hardcoded allowlist of known Vitalicast service identifiers.
- Each query must remain strictly service-bounded.
- No broad generic password dump.
- No cross-domain Keychain scan.
- No wildcard search.
- No payload reads during enumeration.
- Merge/deduplicate returned account keys in memory.
- Swift-side prefix validation required: `vitalicast_canonical_`, `vitalicast_addendum_`.
- Malformed/foreign keys are ignored, not repaired.

### Final/Proposed Service Policy
- **Proposed final service value:** `com.vitalicast.archive`
- **Legacy allowlist candidates:** None found (service omitted).
- **Unresolved Risk:** Because the current source omits the service, native_authoritative enumeration remains blocked until behavior is tested on macOS/Xcode (to determine if iOS defaults to bundle ID or if a migration/fallback read is strictly required).

### Permanently Forbidden Migration Mechanisms
- No `SecItemUpdate`.
- No `SecItemDelete`.
- No `delete` / `update` / `clear` / `reset` / `repair` paths.
- No background migration.
- No copy-forward migration without separate future audit.
- No UserDefaults mirror index.
- No central mutable manifest/index.
- No payload-reading migration.
- No telemetry about legacy/new ratio.

### Future Test Vectors
- Records under final service enumerate.
- Records under explicitly allowlisted legacy service enumerate (if applicable).
- Duplicate service results are deduplicated in memory.
- Unrelated service dummy secret is ignored.
- Malformed account prefix is ignored.
- Empty allowlisted service returns calm empty array.
- `kSecReturnData` remains false for all service queries.
- No `SecItemUpdate` / `SecItemDelete` present.
- Exact-key read remains available for known legacy keys.
- No-service records follow documented unresolved/deferred policy until audited on macOS.

### Implementation Gates for Sprint 5 Phase 3
- **GG approval required** before any Swift implementation.
- Final service allowlist must be approved.
- Behavior for omitted-service records must be resolved.
- XCTest vectors must be approved.
- Native provider must remain unsupported until CI passes.
- Docs must be updated with exact CI run after implementation.


## Sprint 5 Phase 3: Omitted Service Behavior Probe

### Probe Purpose
To determine how iOS Keychain handles generic-password items created without `kSecAttrService` using an XCTest behavior probe. This does not authorize production enumeration.

### Exact Probes Implemented
1. **Legacy Creation:** Creates item without service.
2. **Omitted Service Exact Read:** Reads item without service (Baseline).
3. **Final Service Exact Read:** Reads exact item using `com.vitalicast.archive` service.
4. **Bundle ID Exact Read:** Reads exact item using the app bundle ID.
5. **Bundle ID Attributes-Only Bounded Enumeration:** Queries attributes using bundle ID service.
6. **Omitted Service Attributes-Only Probe:** Unbounded generic password attribute query for dynamic test account.

### Dummy Unrelated-Service Isolation Probe
- Implemented and asserts that `com.vitalicast.unrelated_probe` item does not appear in `com.vitalicast.archive` final-service enumeration.

### Governance Outcomes Matrix
- **Outcome A:** Omitted-service records are accessible via bundle ID service. (Implication: Explicit service allowlist may include bundle ID if approved.)
- **Outcome B:** Omitted-service records require omitted-service query. (Implication: Legacy omitted-service records remain exact-read-only; production enumeration covers only future service-tagged records.)
- **Outcome C:** Omitted-service records are not safely enumerable. (Implication: Same as Outcome B.)
- **Baseline Failure Policy:** If omitted-service exact read fails, Keychain probe is inconclusive and Phase 4 implementation remains blocked.

### Status
- Native provider remains `unsupported` until later implementation passes CI.
- No production enumeration added.
- No `SecItemUpdate`/`SecItemDelete` added.
- No `delete`/`update`/`clear`/`reset` added.
- Static guards confirm absence of all forbidden mutation methods.
