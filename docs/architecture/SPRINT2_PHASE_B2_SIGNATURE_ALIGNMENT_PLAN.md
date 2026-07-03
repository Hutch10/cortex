# Sprint 2 Phase B2 Signature Alignment Plan

## 1. Current State
**Total remaining TypeScript errors:** 27
**Status:** CONDITIONAL PASS (Sprint 2 verification remains blocked by macOS/Xcode xcodebuild; tests are quarantined).

## 2. Source-of-Truth Signatures

### `processWindow`
**Location:** `src/lib/engine/window.ts`
**Signature:**
```typescript
export function processWindow(
    signal_id: SignalID, 
    ts_now_utc: number, 
    ts_latest_norm: number, 
    values: number[], 
    expected_samples: number,
    trace_id: string
): ComputationResult
```
**Conclusion:** The 6th argument is `trace_id` (trace/context metadata).

### `createLedgerEntry`
**Location:** `src/lib/ledger/chain.ts`
**Signature:**
```typescript
export async function createLedgerEntry(
    payload: ComputationResult, 
    last_valid_hash: string,
    trace_id: string
): Promise<LedgerEntry>
```
**Conclusion:** The 3rd argument is `trace_id` (trace/context metadata).

## 3. Argument Mismatch Table

| File | Line | Call | Missing Arg | Semantic Meaning | Safe Deterministic Value | Risk Level | Action |
|---|---|---|---|---|---|---|---|
| `tests/adversarial/engine_coverage.test.ts` | 51 | `processWindow(...)` | `trace_id` (6th) | Trace/Context Metadata | `'test-trace-engine-cov'` | LOW | Execute |
| `tests/integration/coverage_ext.test.ts` | 60 | `processWindow(...)` | `trace_id` (6th) | Trace/Context Metadata | `'test-trace-cov-ext'` | LOW | Execute |
| `tests/integration/determinism.test.ts` | 31 | `processWindow(...)` | `trace_id` (6th) | Trace/Context Metadata | `'test-trace-determinism'` | LOW | Execute |
| `tests/integration/persistence.test.ts` | 39 | `processWindow(...)` | `trace_id` (6th) | Trace/Context Metadata | `'test-trace-persist'` | LOW | Execute |
| `tests/reality/replay.test.ts` | 39 | `processWindow(...)` | `trace_id` (6th) | Trace/Context Metadata | `'test-trace-replay'` | LOW | Execute |
| `tests/integration/coverage_ext.test.ts` | 41 | `createLedgerEntry(...)` | `trace_id` (3rd) | Trace/Context Metadata | `'test-trace-cov-ext'` | LOW | Execute |
| `tests/integration/crash_recovery.test.ts` | 75 | `createLedgerEntry(...)` | `trace_id` (3rd) | Trace/Context Metadata | `'test-trace-crash'` | LOW | Execute |
| `tests/integration/determinism.test.ts` | 42 | `createLedgerEntry(...)` | `trace_id` (3rd) | Trace/Context Metadata | `'test-trace-determinism'` | LOW | Execute |
| `tests/integration/persistence.test.ts` | 42 | `createLedgerEntry(...)` | `trace_id` (3rd) | Trace/Context Metadata | `'test-trace-persist'` | LOW | Execute |
| `tests/ledger/ledger.test.ts` | 29, 42, 53, 70, 71 | `createLedgerEntry(...)` | `trace_id` (3rd) | Trace/Context Metadata | `'test-trace-ledger'` | LOW | Execute |

## 4. Minor Non-Signature Errors

| File | Error / Issue | Recommended Fix |
|---|---|---|
| `atomicity.test.ts`, `corruption.test.ts`, `identity.test.ts`, `persistence.test.ts`, `snapshot_harness.test.ts`, `run_harness.ts` | `TS1117: An object literal cannot have multiple properties with the same name.` | Remove duplicate `trace_id` fields accidentally added during Phase C. |
| `crash_recovery.test.ts:88` | `Property 'fail' does not exist on type 'Expect'.` | Replace `expect.fail()` with `expect.unreachable()` (Vitest). |
| `crash_recovery.test.ts:91` | `Argument of type '"ledger_write_failure"' is not assignable to parameter of type '"hash_mismatch" \| "tamper_detected"'.` | Cast or change to a valid error discriminator if the test strictly expects standard exceptions. |
| `distributed.test.ts:30` | `Type 'number' is not assignable to type 'string'.` | Cast or convert the numeric ID to a string. |
| `useDraftState.test.ts` | `Cannot find module '@testing-library/react-hooks'` | Update import to `@testing-library/react` (modern React 18 convention). |
| `persistence.test.ts:43` | `Object is possibly 'undefined'.` / `Property 'reason' does not exist...` | Narrow `row.doc` safely using `(row.doc as { reason?: string })?.reason` instead of relying on `any`. |

## 5. Execution Strategy & Risk
**Risk:** LOW. All missing arguments are metadata (`trace_id`) with no impact on core algorithmic logic or cryptographic hashing. 
**Recommended Order:**
1. Fix duplicate object properties (`TS1117`).
2. Add missing `trace_id` strings to all `processWindow` and `createLedgerEntry` calls.
3. Fix test assertions and typing drifts (Expect.fail, react-hooks, ledger_write_failure).

**Conclusion:** It is safe to proceed to execution of this plan as Phase B2.
