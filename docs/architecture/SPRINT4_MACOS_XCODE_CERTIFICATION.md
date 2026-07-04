# Vitalicast Sprint 4 macOS/Xcode Certification

## Purpose
The macOS/Xcode certification path is required to clear the known Windows native runtime block (LevelDB/PouchDB static build defect) and prove that the native iOS shell and secure storage bridge compile and link correctly on a real Apple toolchain. This path runs via GitHub Actions `macos-latest` runners.

## Expected Working Directories
- Frontend web app: `frontend`
- iOS Shell app: `apps/vitalicast-ios-shell`
- Xcode project: `apps/vitalicast-ios-shell/ios/App`

## Exact Commands (CI)
```bash
# Frontend
npm ci
npx tsc --noEmit

# iOS Shell
npm ci
npx cap sync ios

# Xcodebuild
xcodebuild -workspace App.xcworkspace -scheme App -sdk iphonesimulator clean build
```

## Pass/Fail Criteria
- **Pass:** The `xcodebuild` command completes successfully without native compilation errors or linkage failures in the secure-storage bridge.
- **Fail:** Any compilation error in Swift/Objective-C boundaries, missing dependencies, or unlinked frameworks.

## Interpreting Windows Native Runtime Caveat
Running `npm run build` on Windows succeeds in Turbopack compilation but fails during Next.js static page generation when it attempts to load native binary bindings (e.g., LevelDB/PouchDB). This is expected. The authoritative native certification must happen on macOS.

## Scope Constraints
- **Native iOS Key Enumeration:** Explicitly out of scope. The native provider returns `unsupported` (fail-closed).
- **Sprint 2/3 Trust Boundaries:** Unchanged. The workflow does not inject Mapbox tokens, does not deploy, and does not alter any feature logic.

## Runtime Bridge Verification Plan
To fully verify the bridge natively, future simulator UI tests (or manual runbooks) must assert:
1. `createSecureRecord` creates exactly once.
2. Duplicate `create` attempts do not overwrite the canonical record.
3. `appendAddendum` appends without mutating the canonical record.
4. `readSecureRecord` successfully reads an exact key.
5. Unsupported enumeration remains fail-closed.
6. No `SecItemUpdate` path is exposed or reachable.
