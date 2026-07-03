# Sprint 2 Frontend Drift Log

## Verification Status
**Frontend build**: Fails during TypeScript compilation.

The Next.js Turbopack application build compiles successfully and cleanly passes all Server/Client boundary checks after resolving the initial drift, but the overarching Next.js build and `npx tsc` fail due to widespread typing drift in the pre-existing `tests/` and test-harness files, which are outside the Vitalicast Sprint 2 scope. 

## Remaining Blockers (TypeScript Drift)

### 1. Database Client Export Mismatches
Various test files refer to unexported legacy properties rather than their getter functions.
- `tests/integration/determinism.test.ts`: Missing `vortexQueueDB`, `pulseLedgerDB`, `quarantineDB` (Suggests replacing with `getVortexQueueDB()`, etc.)
- `tests/integration/persistence.test.ts`: Same
- `tests/integration/timing_drift.test.ts`: Same
- `tests/ledger/ledger.test.ts`: Same
- `tests/reality/identity.test.ts`: Same
- `tests/reality/multi_process.test.ts`: Same

### 2. Type/Signature Mismatches
- `tests/integration/crash_recovery.test.ts`: Implicit `any`, `fail` missing on `Expect`, `ledger_write_failure` not assignable to strict error types.
- `tests/reality/atomicity.test.ts` & `corruption.test.ts`: `median` does not exist on `BaselineResult` (likely renamed to `mean` or `median` dropped).
- `tests/reality/persistence.test.ts` & `identity.test.ts`: `trace_id` is missing but required by `ComputationResult`.
- `tests/reality/snapshot_harness.test.ts` & `run_harness.ts`: Template literal `` `signal_${number}` `` is no longer directly assignable to `SignalID`.
- `tests/reality/worker_sim.ts`: Catch block error `e` is of type `unknown` and requires explicit narrowing before access.

These test-harness failures are explicitly quarantined as external to the Sprint 2 secure-storage implementation scope.
