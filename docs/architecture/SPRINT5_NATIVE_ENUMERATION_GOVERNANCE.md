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
