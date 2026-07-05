# Sprint 6 Phase 1: Authoritative Native Identity Consumption Boundary

## Sprint 5 Certified Baseline
- **Sprint 5 Final Classification:** SPRINT_5_CLOSED_PASS
- **Sprint 5 Closure Commit:** `140551c1c336ebf1517991f1df9c88b5b49c6f2f`
- **Certified Native Authority Promotion Run:** `28725627559`
- **Current Provider States:**
  - Successful native bounded identity enumeration: `native_authoritative`
  - Native bridge failure: `unsupported / fail-closed`, records: `[]`
  - Browser: `dev_non_authoritative_fallback`
- **Canonical Service:** `com.vitalicast.archive`
- **Legacy Omitted-Service Cohort:** legacy exact-read-only compatibility cohort
- **Native Enumeration Returns:** identity only (`storageKey`, `kind`, `label`); `rawPayloadReturned: false`

## Identity-Flow Map
1. **Provider Creation:** `createArchiveKeyListProvider()` instantiates `NativeSecureKeyListProvider` (if native) or `BrowserFallbackKeyListProvider`.
2. **List Query:** `listAvailableArchiveKeys()` is called by the consumer (e.g., `LibrarySelectionShell`).
3. **ArchiveKeyListResult:** Returns `platformAuthority`, `records`, `findings`, and `rawPayloadReturned`.
4. **Consumer Handling:** `LibrarySelectionShell` receives the result. If `unsupported`, it blocks browsing. If `native_authoritative` or `dev_non_authoritative_fallback`, it renders the list of identity records.
5. **Selection State:** User clicks a record; `selectedStorageKey` is set in local React component state.
6. **Exact-Record Detail Read:** The `selectedStorageKey` is passed to `RecordDetailShell` (or `DetailComponent`), which then calls `readSecureRecord({ storageKey })`.

## Consumer Audit
### Exact-Read Boundary
- The list/browser path (`LibrarySelectionShell`) receives identity metadata only.
- Payload access occurs exclusively after one known record is explicitly selected.
- **Exact Symbol/Function:** `VitalicastSecureStorage.readSecureRecord({ storageKey })` is called exactly once by `RecordDetailShell` upon mounting with a valid `storageKey`.
- **List-time Payload Read:** ABSENT.

### LibrarySelectionShell Audit
- Renders provider records neutrally.
- Handles `native_authoritative` inherently by rendering records (blocks if `unsupported`, warns if `dev_non_authoritative_fallback`).
- **Identity Label:** Displays raw `storageKey` directly as the primary user-facing label (`row.label || row.storageKey`). 
- **Kind:** Presented neutrally (capitalized string).
- **Selection State:** Stores identity in local React `useState` context (`selectedStorageKey`). It does NOT expose it to URL/query/history.
- **Provider Failure:** Fails closed cleanly with a calm message ("Archive browsing requires an audited platform list provider.").
- **Empty Cohort:** Renders "No records available." Could potentially be misunderstood as "no archive exists", but does not actively claim completeness.

### Archive Health Audit
- `platformAuthority` and `findings` do not trigger any claims like "all records found", "archive complete", or "100% coverage".
- `unsupported` does not silently appear as a valid empty archive; it is explicitly blocked from listing.
- `dev_non_authoritative_fallback` remains visibly/nonsemantically distinguishable (renders a warning banner).
- **Completeness Conflation:** ABSENT.

### Identity Label Audit
- The UI currently displays the raw `storageKey` to the user.
- **Assessment:** Displaying the raw storage key acts as a neutral technical identity. However, it may create excessive cognitive load and accidental trust meaning.
- **Policy:** A payload-free strategy should be considered to create better neutral labels (e.g., "Record 1", "Addendum 1") derived from a deterministic local ordinal to avoid leaking raw keys unnecessarily, though the current raw key display is not a strict security violation.

### Canonical/Addendum Relationship Audit
- Native enumeration returns both `vitalicast_canonical_` and `vitalicast_addendum_`.
- Current browser treats each as an independent selectable identity.
- Addenda are NOT automatically grouped with canonical records.
- **Sprint 6 Design Question:** Since there is currently no certified parent mapping contract embedded cleanly in the unhydrated key identity (other than prefix parsing), grouping them safely without payloads is risky. They must remain ungrouped independent identities unless a certified mapping is defined.

### Archive-Selection State Audit
- Managed via `useState<string | null>(null)` in `LibrarySelectionShell`.
- **URL/Query/History Exposure:** ABSENT. The raw `storageKey` remains entirely outside the URL.
- **Continuity:** The selected identity does NOT survive a page refresh (local state only).

### Exact Detail Read Behavior
- When selected, one known `storageKey` is passed to `RecordDetailShell`.
- `readSecureRecord` is called exactly once per selection via a `useEffect` hook with dependency on `storageKey`.
- No accidental duplicate reads or N+1 hydration.

### Verification Boundary Audit
- Archive identity authority is NOT used as verification status, provenance, hash validity, or record authenticity.
- Verification is handled entirely by `RecordIntegrityVerifier` inside `RecordDetailVerificationSection`, which only runs after the payload is loaded.
- **Automatic Verified Status:** ABSENT.

### Structural/Raw Payload Boundary Audit
- `RawPayloadViewer` is strictly invoked by `RecordDetailShell` only *after* exact selection and payload load.
- Structural parsing is similarly bounded.
- List rendering never invokes these components.

## Sprint 6 Candidate Objective
**Authoritative Archive Identity Browser Integration**
Allow the certified `native_authoritative` identity list to drive the Vitalicast Library selection experience while preserving identity-only list data, explicit selection before payload read, one-known-record exact read, separate verification lifecycle, no completeness claims, no legacy browsing claims, and no raw storageKey URL exposure.

## Non-Goals
- Legacy omitted-service enumeration
- Archive completeness scoring
- Payload preview in list
- List-time payload hydration
- Search over payload
- Automatic verification
- Chronology inference
- Migration, mutation, deletion, repair
- Export, sync, telemetry
- Medical logic or engagement optimization

## Sprint 6 Invariants
- **S6-1:** Enumeration returns identity only.
- **S6-2:** A list item selection is required before payload read.
- **S6-3:** One selected identity may trigger one exact-record read path.
- **S6-4:** `native_authoritative` means authoritative bounded native identity enumeration only.
- **S6-5:** Legacy omitted-service records remain non-enumerable.
- **S6-6:** No archive-completeness claim.
- **S6-7:** No raw `storageKey` in URL/query/history.
- **S6-8:** Verification remains independent of enumeration authority.
- **S6-9:** No list-time payload preview or structural parse.
- **S6-10:** Native provider failure remains fail-closed.
- **S6-11:** Browser listing remains `dev_non_authoritative_fallback`.
- **S6-12:** No mutation.

## Phase 2 Implementation Gates
- Consumer identity-flow map complete
- Exact-read boundary identified
- List-time payload audit clean
- Authority semantic audit clean
- Archive-health wording audit clean
- Route/storageKey audit clean
- Addendum relationship decision documented (leave ungrouped for now)
- Neutral identity label policy documented (explore local ordinal indexing)
- Selected-state lifecycle documented (local state only)
- Test plan defined

## Required Test Matrix
- **A.** `native_authoritative` records appear in Library selection
- **B.** List render does not call `readSecureRecord`
- **C.** Selecting one record calls exact read only for selected key
- **D.** Unselected records are never hydrated
- **E.** Provider failure does not invoke browser fallback
- **F.** Unsupported native result is not presented as authoritative empty archive
- **G.** Browser provider remains `dev_non_authoritative_fallback`
- **H.** Raw `storageKey` is absent from URL/query/history
- **I.** `native_authoritative` does not mark record verified
- **J.** Structural parser is not invoked during list render
- **K.** `RawPayloadViewer` is not invoked during list render
- **L.** Legacy omitted-service identities are not fabricated into the list
- **M.** Canonical/addendum kind remains neutral
- **N.** No completeness wording triggered by `native_authoritative`
- **O.** No mutation APIs introduced

## Final Decision
**SPRINT_6_OBJECTIVE_APPROVED**

## Sprint 6 Phase 2 — Authoritative Identity Browser Integration
- Sprint 6 objective approved at dd4c8c3
- native_authoritative list is consumed as identity only
- provider raw-key labels removed/neutralized if applicable
- neutral display label policy
- separate canonical/addendum ordinals
- original provider order preserved
- ordinals are display-only and nonpersistent
- internal selection remains storageKey-based
- exact-read boundary unchanged
- no list-time payload hydration
- no parent grouping for addenda
- selected storageKey remains local state only
- refresh clears selection
- no URL/query/history storageKey exposure
- authoritative empty wording remains bounded
- unsupported path remains fail-closed
- browser remains dev_non_authoritative_fallback
- verification remains independent
- tests implemented
- TypeScript result: PASS
- frontend test result: Vitest environment error (Skipped)
- no Swift changes
- no bridge changes
- no mutation
