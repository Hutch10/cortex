# Vitalicast Sprint 6 - Selected Record Continuity Audit

## Baseline
- **Sprint 5 Baseline:** `SPRINT_5_CLOSED_PASS`
- **Sprint 6 Phase 1/2 Certified Baseline:** `PASS_AUTHORITATIVE_IDENTITY_BROWSER_INTEGRATION` (Frontend: `9b607d7`, Outer: `c538cf9`)

## Lifecycle Audits
### Selection-to-Read Lifecycle Map
A. User selects identity A via `LibrarySelectionShell`.
B. Local state `selectedStorageKey` changes.
C. `RecordDetailShell` is updated (prop update, not remounted).
D. `useEffect` in `RecordDetailShell` fires (dependencies: `[storageKey, storage]`).
E. Synchronous reset of payload, error, and context state occurs.
F. `VitalicastSecureStorage.readSecureRecord({ storageKey })` is invoked exactly once.
G. `loading` state is set to true during fetch.
H. On success, `isCancelled` guard is checked, then `setRecordContext` and `setRawPayload` write the success state.
I. On not-found or error, `isCancelled` guard is checked, then `setErrorMsg` writes the failure state.
J. `RecordDetailVerificationSection` mounts only if record context is successfully loaded.
K. `RawPayloadViewer` activates only if record context is successfully loaded.

### Exact-Read Invocation
- **Dependencies:** `[storageKey, storage]`.
- **Classification:** `READ_ONCE_PER_SELECTED_KEY_BY_SOURCE` (with possible development double invoke due to React Strict Mode, which is harmlessly aborted by cleanup).

### Stale Result & Error Behavior
- **Stale Read Guard:** Present (`isCancelled` flag in `useEffect` closure).
- **Stale Read Classification:** `STALE_ASYNC_RESULT_RACE_GUARDED`.
- **Stale Error Guard:** Present (`isCancelled` flag in `catch` block).
- **Stale Error Classification:** `STALE_ERROR_GUARDED`.

### Transition Audits
- **Loading Transition:** Changing selected identity synchronously resets component state. Visual mismatch window is ABSENT.
- **Not-Found Transition:** `NOT_FOUND_STATE_CLEARS_PRIOR_PAYLOAD`.
- **Error Transition:** Read error safely clears prior payload and UI.

### Verification Lifecycle Coupling
- **Trigger/Input:** Record load success.
- **Verification Reset:** Controlled via `key={storageKey}` on `RecordVerificationPanel`, forcing a full React component unmount/remount on identity change.
- **Verification Stale Result Guard:** Present (via React key unmounting).
- **Verification Race Classification:** `VERIFICATION_STALE_RESULT_GUARDED`.

### Payload-View State Coupling
- **RawPayloadViewer / StructuralSchemaRenderer Persistence Risk:** ABSENT. State is nulled synchronously when identity changes, unmounting the viewers before the new read resolves.

### Detail Identity Context Audit
- **Classification:** `DETAIL_IDENTITY_CONTEXT_ABSENT`. The raw `storageKey` is masked (`vitalicast_canonical_?abcd`), but the neutral list label ("Record 1") is not passed down. The user lacks neutral context to know which record is open.

### Component Switching & React Key Behavior
- **Selection Switch Component Behavior:** One mounted `RecordDetailShell` instance with changing prop.
- **React Key:** `RecordDetailShell` lacks a `key` prop when rendered by `LibrarySelectionShell`.
- **Remount vs Update:** Prop-update behavior on the same instance.
- **Effect Cleanup Behavior:** Sets `isCancelled = true` on prop change or unmount, successfully guarding against stale async state updates.

## Race Matrix
| Race Scenario | Expected Safe Behavior | Current Source Behavior | Status |
|---|---|---|---|
| R1: A slow → B fast → A finishes last | B state remains | `isCancelled` drops A | PASS |
| R2: A slow → B fails → A finishes last | B error remains | `isCancelled` drops A | PASS |
| R3: A loaded → B loading | A payload hidden | Sync state reset hides A | PASS |
| R4: A loaded → B not found | B not found, A hidden | Sync state reset hides A | PASS |
| R5: A loaded → B bridge error | B error, A hidden | Sync state reset hides A | PASS |
| R6: A verif slow → B selected → A verif finishes | A verif drops | React `key` unmounts A | PASS |
| R7: A payload rendered → B selected/loading | A payload unmounts | Sync state reset unmounts A | PASS |
| R8: Rapid A → B → C selection | C active, A/B dropped | `isCancelled` drops A/B | PASS |

## Sprint 6 Phase 3 Invariants
- **S6-13:** Only the current selected identity may publish exact-read state.
- **S6-14:** Late reads from prior identities may not alter current detail state.
- **S6-15:** Late errors from prior identities may not alter current detail state.
- **S6-16:** Changing identity clears or hides prior payload before the new read resolves.
- **S6-17:** Not-found for the current identity cannot retain prior payload.
- **S6-18:** Read error for the current identity cannot retain prior payload-derived UI.
- **S6-19:** Verification presentation is scoped to the current selected identity/payload lifecycle.
- **S6-20:** Late verification results from prior identities may not render under the current identity.
- **S6-21:** Rapid selection converges on the latest selected identity.
- **S6-22:** No additional payload reads are introduced.
- **S6-23:** No persistence or URL exposure is introduced.
- **S6-24:** No mutation.

## Sprint 6 Phase 4 Roadmap
### Decision
**PHASE_3_LIFECYCLE_PASS**
The current lifecycle already has complete stale-read, stale-error, payload-reset, and verification guards. A closure/test-only Phase 4 is required to formalize the regression safety net and resolve the identity context gap.

### Required Phase 4 Tests
A. Selecting A starts exact read for A only.
B. Selecting B after A starts exact read for B only.
C. Late A success cannot overwrite B success.
D. Late A error cannot overwrite B success.
E. Selecting B immediately clears/hides A payload before B resolves.
F. B not-found cannot leave A payload visible.
G. B read error cannot leave A RawPayloadViewer visible.
H. B read error cannot leave A StructuralSchemaRenderer visible.
I. Selection switch resets record-level verification presentation.
J. Late A verification result cannot appear under B.
K. Rapid A → B → C leaves C as the only active detail identity.
L. No payload hydration for unselected list records.
M. `readSecureRecord` receives exact selected storageKey only.
N. No storageKey URL/query/history exposure.
O. No raw storageKey rendered as detail context.
P. `native_authoritative` does not imply verification.
Q. No mutation APIs introduced.

### Phase 4 Non-Goals
- Persistence, preload, or caching
- Adjacent record reads or list hydration
- URL storageKey or browser history identity
- Selection restoration
- Background/automatic verification
- Concurrency optimization
- Payload comparison or addendum grouping
- Mutation, export, sync, telemetry, medical logic
