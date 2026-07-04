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


## Sprint 5 Phase 4: CI Infrastructure Corrective Action

### CI Run Details
- **Run ID:** 28692619360
- **Classification:** INFRA FAILURE
- **Exact Error:** xcodebuild: error: Scheme App is not currently configured for the test action.

### Probe Outcomes
- All probe outcomes were **Not Run**.
- No Keychain compatibility conclusion can be drawn.
- Production enumeration remains **blocked**.
- Native provider remains unsupported/fail-closed.

### Corrective Action Status
- **Corrective Action Attempted:** Shared scheme TestAction wiring.
- **Result:** TEST_TARGET_MISSING_OR_MALFORMED. The target VitalicastSecureStorageTests does not exist in project.pbxproj.
- **Next Step:** A separate corrective action is required to officially add the XCTest target to the Xcode project file (using Xcode/XcodeGen/CocoaPods or a proper pbxproj modifier) before the scheme can be wired to it.

### Guard Assertions
- No production Swift/TS/TSX behavior changed.
- No SecItemUpdate / SecItemDelete added.
- No 
ative_authoritative enabled.


## Sprint 5 Phase 4B: XCTest Target Injection

### Prior Blocker
- **TEST_TARGET_MISSING_OR_MALFORMED:** The XCTest target was previously missing from the project entirely.

### Corrective Action: Target Injection
- **Target Creation Mechanism:** Used the `xcodeproj` Ruby gem to deterministically inject the `VitalicastSecureStorageTests` target (`PBXNativeTarget`) into `project.pbxproj`.
- **Target UUID:** `12B4CF5D808B99A541873459`
- **Host Mode:** App-Hosted. The test target is explicitly linked to the `App` target (`504EC3031FED79650016851F`) via `TestTargetID`, `TEST_HOST`, and `BUNDLE_LOADER` to ensure `Bundle.main.bundleIdentifier` correctly evaluates during the probe.
- **Scheme TestAction:** Successfully manually generated the `App.xcscheme` file containing a `TestAction` referencing the new test target's UUID.

### Guard Assertions
- Production Swift behavior remains completely unchanged.
- Native provider remains `unsupported`/fail-closed.
- No production `SecItemCopyMatching` was implemented.
- No `SecItemUpdate` / `SecItemDelete` paths exist.
- New CI run required to execute probes.


## Sprint 5 Phase 4C: Simulator Destination Corrective Action

### CI Run Details
- **Prior Run Classification:** `SIMULATOR_DESTINATION_FAILURE`
- **Build Status:** Passed
- **Test Status:** Did not execute probes
- **Exact Error:** `Unable to find a device matching the provided destination specifier`
- **Issue:** The hardcoded `iPhone 15` destination was unavailable on the macos-latest runner.

### Probe Outcomes
- All probe outcomes remain **Not Run**.
- No Keychain compatibility conclusion has been drawn.
- Production enumeration remains **blocked**.
- Native provider remains `unsupported`/fail-closed.

### Corrective Action Status
- **Corrective Action Attempted:** Updated the `.github/workflows/vitalicast-ios-certification.yml` CI workflow to dynamically resolve the first available iPhone simulator UDID using `xcrun simctl list devices available` instead of hardcoding a specific device name.
- **Next Step:** A new CI run has been triggered to execute the tests on the dynamically resolved destination.

### Guard Assertions
- No production Swift/TS/TSX behavior changed.
- No `SecItemUpdate` / `SecItemDelete` added.
- No `native_authoritative` enabled.


## Sprint 5 Phase 4D: XCTest Product Bundle Corrective Action

### CI Run Details
- **Prior Run Classification:** `TEST_TARGET_LINKED_BUT_BUILD_FAILED`
- **Exact Error:** `Multiple commands produce App.app/PlugIns/.xctest`
- **Issue:** The XCTest target product bundle name was blank/malformed in `project.pbxproj`, leading to a collision/missing product file.

### Probe Outcomes
- All probe outcomes remain **Not Run**.
- No Keychain compatibility conclusion has been drawn.
- Production enumeration remains **blocked**.
- Native provider remains `unsupported`/fail-closed.

### Corrective Action Status
- **Corrective Action Attempted:** Used the `xcodeproj` Ruby gem to set the test target's product reference name, path, and build settings (`PRODUCT_NAME`, `PRODUCT_MODULE_NAME`, `PRODUCT_BUNDLE_IDENTIFIER`, `WRAPPER_EXTENSION`, `MACH_O_TYPE`, `PACKAGE_TYPE`, `GENERATE_INFOPLIST_FILE`) to properly produce `VitalicastSecureStorageTests.xctest`.
- **Next Step:** A new CI run has been triggered to execute the tests with the corrected product naming.

### Guard Assertions
- Production Swift behavior remains unchanged.
- No `SecItemUpdate` / `SecItemDelete` paths exist.
- No `native_authoritative` enabled.


## Sprint 5 Phase 4E: XCTest Info.plist Corrective Action

### CI Run Details
- **Prior Run Classification:** `TEST_TARGET_PRODUCT_FIXED_BUT_INFOPLIST_MISSING`
- **Exact Error:** `Build input file cannot be found: VitalicastSecureStorageTests/Info.plist`
- **Issue:** The XCTest target was looking for a physical `Info.plist` file which did not exist.

### Probe Outcomes
- All probe outcomes remain **Not Run**.
- No Keychain compatibility conclusion has been drawn.
- Production enumeration remains **blocked**.
- Native provider remains `unsupported`/fail-closed.

### Corrective Action Status
- **Corrective Action Attempted:** Used the `xcodeproj` Ruby gem to remove the `INFOPLIST_FILE` build setting from the test target and ensured `GENERATE_INFOPLIST_FILE` is set to `YES`. This allows Xcode to dynamically generate the required Info.plist during the build.
- **Next Step:** A new CI run has been triggered to execute the tests.

### Guard Assertions
- Production Swift behavior remains unchanged.
- No `SecItemUpdate` / `SecItemDelete` paths exist.
- No `native_authoritative` enabled.


## Sprint 5 Phase 4F: XCTest Capacitor Compile Dependency Corrective Action

### CI Run Details
- **App Build:** Passed
- **XCTest target and generated Info.plist:** Succeeded
- **Probes Executed:** No
- **Classification:** `TEST_COMPILE_FAILURE` / `CAPACITOR_SEARCH_PATH_MISSING`
- **Exact Error:** `error: compilation search paths unable to resolve module dependency: 'Capacitor'`

### Capacitor Dependency Analysis
- **Import Analysis:** `import Capacitor` is genuinely required. The test file explicitly relies on the `CAPPluginCall` symbol to invoke the plugin APIs (`plugin.createSecureRecord`, `plugin.readSecureRecord`, etc.) for tests inherited from Sprint 4.
- **Specific Lines:** `CAPPluginCall` is heavily used starting at line 20 (`let call = CAPPluginCall(callbackId: "1", options: ...)`).
- **Corrective Action:** None taken. Xcode `FRAMEWORK_SEARCH_PATHS` were deliberately not guessed or added to prevent broad/brittle config pollution. We must resolve the Capacitor XCTest linkage deterministically.

### Probe Outcomes
- All probe outcomes remain **Not Run**.
- No Keychain compatibility conclusion has been drawn.
- Production enumeration remains **blocked**.
- Native provider remains `unsupported`/fail-closed.

### Guard Assertions
- Production Swift behavior remains unchanged.
- No `SecItemUpdate` / `SecItemDelete` paths exist.
- No `native_authoritative` enabled.


## Sprint 5 Phase 4G: CocoaPods XCTest Search-Path Integration

### CI Run Details
- **Prior Run Classification:** `TEST_COMPILE_FAILURE` / `CAPACITOR_SEARCH_PATH_MISSING`
- **App Build:** Passed
- **XCTest Configuration:** target/product/generated Info.plist passed
- **Dependency Proof:** `CAPPluginCall` usage in `VitalicastSecureStorageTests.swift` confirms Capacitor is a genuine test dependency.

### Corrective Action Status
- **Corrective Action Attempted:** Edited `ios/App/Podfile` to nest `target 'VitalicastSecureStorageTests' do inherit! :search_paths end` within the main `App` target.
- **Dependency Mechanism:** CocoaPods test-target search-path inheritance.
- **Rejections:** Manual `FRAMEWORK_SEARCH_PATHS` mapping and SPM injection were explicitly rejected to prevent configuration pollution and dual-dependency mechanisms.
- **Next Step:** A new CI run has been triggered. The CI workflow's `npx cap sync ios` will perform the `pod install` dynamically to generate the CocoaPods workspace and xcconfig links for the test target before running xcodebuild.

### Probe Outcomes
- All probe outcomes remain **Not Run**.
- No Keychain compatibility conclusion has been drawn.
- Production enumeration remains **blocked**.
- Native provider remains `unsupported`/fail-closed.

### Guard Assertions
- Production Swift behavior remains unchanged.
- No `SecItemUpdate` / `SecItemDelete` paths exist.
- No `native_authoritative` enabled.
- Test probe semantics remain unchanged.


## Sprint 5 Phase 4H: App Module XCTest Visibility Corrective Action

### CI Run Details
- **Prior Run Classification:** `TEST_COMPILE_FAILURE` / `APP_MODULE_PLUGIN_TYPE_NOT_VISIBLE`
- **Issue:** The test target could not find `VitalicastSecureStoragePlugin` in scope because it was not added to the `App` target's compile sources in the Xcode project.

### Corrective Action Status
- **Corrective Action Attempted:** Used the `xcodeproj` Ruby gem to correctly add `VitalicastSecureStoragePlugin.swift` to the `App` target's `PBXSourcesBuildPhase`. The test target already imports the App module (`@testable import App`) and the App Debug configuration already has `ENABLE_TESTABILITY = YES`. 
- **Next Step:** A new CI run has been triggered to execute the tests. 

### Probe Outcomes
- All probe outcomes remain **Not Run**.
- No Keychain compatibility conclusion has been drawn.
- Production enumeration remains **blocked**.
- Native provider remains `unsupported`/fail-closed.

### Guard Assertions
- Production Swift behavior remains unchanged.
- No `SecItemUpdate` / `SecItemDelete` paths exist.
- No `native_authoritative` enabled.


## Sprint 5 Phase 4I: CAPPlugin Result Optional-Chaining Corrective Action

### CI Run Details
- **Prior Run Classification:** `TEST_COMPILE_FAILURE` / `CAPPLUGIN_RESULT_OPTIONAL_UNWRAP`
- **Issue:** The test target could not compile because `PluginCallResultData` is optional and requires explicit unwrapping.

### Corrective Action Status
- **Corrective Action Attempted:** Replaced all instances of `result?.data[...]` with `result?.data?[...]` in `VitalicastSecureStorageTests.swift`.
- **Constraint Checklist:** 
  - No force unwraps introduced.
  - Assertions unchanged in intent.
  - Probe semantics unchanged.
  - App dependency warning remains observed and unmodified (no project dependency graph changes made).
- **Next Step:** A new CI run has been triggered to execute the tests. 

### Probe Outcomes
- All probe outcomes remain **Not Run**.
- No Keychain behavior conclusion has been drawn.
- Production enumeration remains **blocked**.
- Native provider remains `unsupported`/fail-closed.

### Guard Assertions
- Production Swift behavior remains unchanged.
- No `SecItemUpdate` / `SecItemDelete` paths exist.
- No `native_authoritative` enabled.


## Sprint 5 Phase 4 Final Result: Outcome B — Omitted-Service Only

### Certified CI Run Details
- **CI run:** 28722199486
- **Certified commit:** 79d401f
- **Result:** `** TEST SUCCEEDED **`
- **XCTest Result:** `VitalicastSecureStorageTests` suite passed
- **Probe executed:** `testOmittedServiceKeychainBehaviorProbe` passed

### Empirical Probe Outcomes
- **Probe 1 — Legacy Creation:** `errSecSuccess` (Generic-password item created with account and data but no `kSecAttrService`).
- **Probe 2 — Omitted Service Exact Read:** `errSecSuccess`, Payload exact match passed.
- **Probe 3 — Final Service Exact Read:** `errSecItemNotFound`.
- **Probe 4 — Bundle ID Exact Read:** `errSecItemNotFound`.
- **Probe 5 — Bundle ID Attributes-Only Bounded Enumeration:** Legacy omitted-service fixture NOT FOUND.
- **Probe 6 — Omitted Service Attributes-Only Probe:** Legacy fixture FOUND. (Note: This XCTest-only query is permanently forbidden as production guidance).
- **Dummy Unrelated-Service Isolation Probe:** PASS. (Item under `com.vitalicast.unrelated_probe` was not returned by `com.vitalicast.archive`).

### Governance Classification
- **Decision Matrix Outcome:** OUTCOME B (OMITTED-SERVICE ONLY)
- **Classification:** `PASS_PROBES_EXECUTED` / `OUTCOME_B`

### Legacy Cohort Definition
**Name:** legacy exact-read-only compatibility cohort

**Rules:**
- Legacy omitted-service items are preserved.
- Exact known-key reads remain compatible.
- They are not discoverable through the tested bundle-ID bounded service query.
- They are discoverable only through the tested service-omitted broad query.
- The service-omitted broad query remains permanently forbidden in production.
- No native browse enumeration.
- No omitted-service `kSecMatchLimitAll` in production.
- No generic-password-wide traversal.
- No migration, automatic migration, copy-forward, or background normalization.
- No repair path, manifest, or UserDefaults index.
- No legacy/new count telemetry.

### Future Native Enumeration Cohort
**Canonical service:** `com.vitalicast.archive`

**Future Production Design Proposals:**
- **NEW canonical writes:** `kSecAttrService = com.vitalicast.archive`
- **NEW addendum writes:** `kSecAttrService = com.vitalicast.archive`
- **Future bounded enumeration query:**
  - `kSecClass = kSecClassGenericPassword`
  - `kSecAttrService = com.vitalicast.archive`
  - `kSecReturnData = false`
  - `kSecReturnAttributes = true`
  - `kSecMatchLimit = kSecMatchLimitAll`
- **Enumeration output constraint:** Enumeration output may use only attributes required to identify records (No payload data).
- **Prefix validation constraint:** After query return, enforce strict account prefix validation in Swift (`vitalicast_canonical_`, `vitalicast_addendum_`) and reject all other accounts.

### Phase 5B Production Exact-Read Compatibility Design Questions
Phase 5B must audit exact-record read behavior for:
A. legacy omitted-service known-key records
B. future `com.vitalicast.archive` service-tagged known-key records

The production read design must preserve exact-read compatibility without broad enumeration. Explicitly evaluate a bounded exact-read order such as:
1. exact account + `com.vitalicast.archive`
2. exact account with legacy omitted-service compatibility query

*But do not approve this order until exact query collision and ambiguity semantics are audited.*

**Important Constraint:** A legacy exact-read query with `kSecAttrService` omitted is an exact known-account read, not enumeration. It must remain `kSecMatchLimitOne` and must never become `kSecMatchLimitAll`. Phase 5B must determine whether an omitted-service exact known-account query could accidentally match a service-tagged item with the same account. Do not guess.

### Phase 5B Implementation Gates
Before production implementation approval, require:
- Exact-read collision audit
- Duplicate-account-across-services behavior analysis
- Write service-tag design
- Addendum service-tag design
- Attributes-only enumeration result shape
- Prefix validation design
- Deduplication policy if required
- Zero payload confirmation
- Zero mutation confirmation
- Static guard plan
- macOS CI test plan

### Production Status Assertions
- **native provider:** unsupported / fail-closed
- **Browser archive listing:** dev_non_authoritative_fallback
- **native_authoritative:** BLOCKED
- No production broad omitted-service `kSecMatchLimitAll` enumeration exists.
