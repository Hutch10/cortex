# Sprint 2 Test Harness Alignment Plan

This document outlines the precise, manual repair plan for resolving the frontend TypeScript drift strictly isolated within the `tests/` directory, without risking syntax regressions through bulk regex replacements or broad `any` casts.

## Current State
**Remaining Test Errors**: ~54 TypeScript errors across 12 test files.
**Production Status**: The core Vitalicast application and Next.js Turbopack build cleanly pass.
**Sprint 2 Status**: CONDITIONAL PASS (Awaiting macOS/Xcode `xcodebuild` execution).

## Source-of-Truth Inspections
Before determining the safe fix for each error, the following production contracts were inspected:
1. `src/lib/db/client.ts`: Exports getter functions `getVortexQueueDB()`, `getPulseLedgerDB()`, `getQuarantineDB()`, and `closeDBs()`. It no longer exports direct database instances.
2. `BaselineResult` (`src/lib/engine/baseline.ts`): Requires `type: 'mean' | 'median'` and uses `mean`, `stddev`, `med`, `mad` rather than `median`.
3. `ComputationResult` (`src/lib/engine/window.ts`): Requires a `trace_id: string` property.
4. `SignalID` (`src/lib/ingestion/queue.ts`): A strict union type `'kp_index' | 'seismic_count' | 'solar_flux' | 'hrv'`.
5. `processWindow` (`src/lib/engine/window.ts`): Requires 6 arguments: `signal_id`, `ts_now_utc`, `ts_latest_norm`, `values`, `expected_samples`, and `trace_id`.

## Line-Level Repair Recommendations

### A. Database Client Export Mismatches
**Files affected**: `tests/integration/determinism.test.ts`, `persistence.test.ts`, `timing_drift.test.ts`, `tests/ledger/ledger.test.ts`, `tests/reality/multi_process.test.ts`
- **Broken Pattern**: `import { vortexQueueDB } from "../../src/lib/db/client";`
- **Source of Truth**: `export function getVortexQueueDB()`
- **Safe Fix**: Update imports to `getVortexQueueDB`, `getPulseLedgerDB`, `getQuarantineDB`. Update usages from `vortexQueueDB.allDocs()` to `getVortexQueueDB().allDocs()`. Update `vi.mock` returns from `{ vortexQueueDB: new PouchDB(...) }` to `{ getVortexQueueDB: () => new PouchDB(...) }`.
- **Scope**: Test code only.
- **Risk**: LOW.

### B. Schema/Type Expectations & Argument Signatures
**Files affected**: `tests/reality/atomicity.test.ts`, `corruption.test.ts`, `replay.test.ts`, `integration/determinism.test.ts`
- **Broken Pattern**: Expected 6 arguments, got 5 in `processWindow`. Missing `type` and `median` on `BaselineResult`.
- **Source of Truth**: `processWindow` requires `expected_samples` (number). `BaselineResult` requires `type: 'mean' | 'median'` and uses `mean` instead of `median`.
- **Safe Fix**: Inject a deterministic `expected_samples` integer (e.g., `10`) as the 5th argument in `processWindow` test calls. Rename `median` to `mean` and add `type: 'mean'` in `BaselineResult` mock fixtures.
- **Scope**: Test code only.
- **Risk**: MEDIUM.

### C. Missing Required Fields in Test Fixtures
**Files affected**: `tests/reality/identity.test.ts`, `persistence.test.ts`
- **Broken Pattern**: `Argument of type '{...}' is not assignable to parameter of type 'ComputationResult'` (missing `trace_id`).
- **Source of Truth**: `ComputationResult` requires `trace_id: string`.
- **Safe Fix**: Add `trace_id: "test-trace-id"` to all mock `ComputationResult` objects.
- **Scope**: Test code only.
- **Risk**: LOW.

### D. Catch Narrowing & Implicit Any Issues
**Files affected**: `tests/reality/worker_sim.ts`, `integration/crash_recovery.test.ts`
- **Broken Pattern**: `catch (e) { console.log(e.message) }` and `(r) => r.id`.
- **Source of Truth**: Strict TypeScript settings enforce `unknown` on catch clauses and explicit parameter types.
- **Safe Fix**: Refactor catch blocks to `if (e instanceof Error) { ... } else { ... }`. Explicitly type callback parameters: `(r: any) => r.id` (or better, use the actual pouchdb row type).
- **Scope**: Test code only.
- **Risk**: LOW.

### E. Template Literal Mismatches
**Files affected**: `tests/reality/snapshot_harness.test.ts`
- **Broken Pattern**: `` signal_id: `signal_${i}` `` assigned to `SignalID`.
- **Source of Truth**: `SignalID` is a strict union.
- **Safe Fix**: Replace dynamic template literals with a valid deterministic union value, e.g., `signal_id: 'seismic_count' as SignalID`.
- **Scope**: Test code only.
- **Risk**: LOW.

## Proposed Repair Sequence
1. **Phase A**: Fix stale database imports and accessors.
2. **Phase B**: Update function argument signatures (primarily `processWindow`).
3. **Phase C**: Align mock fixtures with current `BaselineResult` and `ComputationResult` schemas.
4. **Phase D**: Perform strict TypeScript cleanup (`unknown` catch blocks, implicit `any`).
5. **Phase E**: Final Verification (`npx tsc --noEmit`).

**Highest-Risk Repair Area**: Phase B (Function argument signatures). Manually injecting arbitrary variables (like `expected_samples`) into `processWindow` could theoretically mask test failures if the deterministic data doesn't align with the engine's internal checks. Care must be taken to ensure test semantics are preserved.
