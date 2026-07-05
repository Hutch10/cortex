# Vitalicast Beta 2 Stage 1 Evidence Readiness and Decision Protocol

## Objective
Audit and synchronize the Vitalicast Beta 2 Stage 1 evaluation methodology so the first 10–20 user observations can produce evidence capable of supporting explicit architecture decisions. The primary question is:
**Can ordinary users form a sufficiently accurate mental model of Vitalicast's preservation behavior to trust it with long-lived personal records?**

Stage 1 evaluates user understanding of trust-critical mechanics. It does not test engagement, retention, or satisfaction scoring.

## Stage 1 Hypothesis Matrix
STAGE_1_FIVE_HYPOTHESIS_BASELINE_FORMALIZED_AT_COMMIT_88b5a29`n`nThe five-point Stage 1 Hypothesis Matrix includes the following active hypotheses:

1. **Capture**: Users understand what has been recorded.
2. **Sealing / Locking**: Users understand that original source material reaches a preservation boundary and is not silently rewritten afterward.
3. **Addenda**: Users understand that later context is added beside history rather than replacing the original record.
4. **Search / Retrieval**: Users understand that search retrieves preserved material rather than generating an authoritative interpretation.
5. **Export / Ownership**: Users understand that exported archive material belongs to them and remains useful independently of normal Vitalicast use.

### Additional Evaluated Domains
6. **Provenance Boundary**: Can the user distinguish original user-authored material from later system-derived or contextual material?
7. **Trust Calibration**: Does the user trust Vitalicast for the correct reasons? (Overtrust is evidence of a mental-model failure even when positive).

## Evidence Model
The observer must distinguish:
* **Observed Behavior** (What the user did)
* **Direct User Statement** (What the user said)
* **Observer Interpretation** (What the observer infers - must never be treated as direct user evidence)
* **Open Question** (Unresolved ambiguities)

## Evidence Capture Discipline
Each observation in the active Stage 1 evidence log must record:
* Tester identifier (privacy-safe protocol)
* Session/date context
* Task or interaction context
* Exact observable behavior
* Direct quotation (when materially important and captured accurately)
* Hesitation or confusion point
* Recovery behavior
* Assistance required
* Observer interpretation, clearly separated
* Unresolved question
* Linked hypothesis or hypotheses
* Contradiction with prior evidence, if present

## Direct Question Bias Audit
Avoid leading questions like "Do you understand that records are immutable?". Use neutral prompts:
* "Tell me what you think happens to this record now."
* "What would you expect to happen if you wanted to add something tomorrow?"
* "Show me how you would find this again."
* "What do you think this export contains?"
* "What do you believe Vitalicast can tell you about this record?"

## Critical Incident Rule
A critical incident is any observed case where a tester forms a materially incorrect mental model of a trust-critical archive behavior. Examples include believing sealed text can be overwritten, believing exports require Vitalicast cloud access, or believing Vitalicast validates truth.
For every critical incident record:
* Observed behavior
* Direct statement
* Affected hypothesis
* Exact interface/context
* Whether assistance caused recovery
* Whether recovery persisted later in the session
* Whether the same misunderstanding appeared in another tester

## Stop / Decision Rules
* **PRESERVE**: Observed evidence consistently supports the intended mental model and no repeated material misunderstanding remains unresolved.
* **REVISE**: The underlying trust principle appears understandable but current implementation, language, or interaction repeatedly produces a correctable misunderstanding.
* **REJECT**: The tested architecture concept itself repeatedly leads users toward a materially wrong mental model, even after neutral exposure and reasonable recovery opportunity.
* **INSUFFICIENT_EVIDENCE**: Too few relevant observations exist, tester exposure was incomplete, evidence conflicts without a clear pattern, observer intervention contaminated the result, or the tested Beta 2 behavior did not actually expose the concept.

Cohort count (10-20 users) is an evidence opportunity target, not an automatic statistical sufficiency threshold.

## Contradiction Handling
Stage 1 must preserve contradictory evidence. Do not average contradictions into a score. The evidence review must ask if misunderstanding is isolated, clusters around a screen, naturally recovers, etc. Do not silently resolve disagreement through majority vote.

## 25-Year / 50-Year Trust Test
Could this user's archive remain understandable enough that the user or a technically competent future reader can distinguish original human-authored source material, later user additions, system-derived conclusions, and archive integrity information without silently mistaking one for another?
* **USER EVIDENCE**: Direct Stage 1 empirical data.
* **LONG-HORIZON ARCHITECTURE INFERENCE**: Extrapolated conclusions. Stage 1 cannot certify the long-horizon goal itself but can reveal mental-model problems that threaten it.

## Beta 3 Evidence Boundary
* **Prospective Grade A stance**: NOT TESTED BY BETA 2 STAGE 1
* **Preservation Grades**: NOT TESTED BY BETA 2 STAGE 1
* **Provenance Inspector**: NOT TESTED BY BETA 2 STAGE 1
* **Archive Health**: NOT TESTED BY BETA 2 STAGE 1
* **First-Class Citations**: NOT TESTED BY BETA 2 STAGE 1
* **Canonical/integrity attestations**: NOT TESTED BY BETA 2 STAGE 1
* **Export Independence**: INDIRECTLY INFORMED BY STAGE 1
* **Durable schema evolution**: NOT TESTED BY BETA 2 STAGE 1
* **Self-describing manifests**: NOT TESTED BY BETA 2 STAGE 1
* **Public Stability Promise**: NOT TESTED BY BETA 2 STAGE 1
* **Portable archive entry identity**: NOT TESTED BY BETA 2 STAGE 1
* **Deletion/immutability reconciliation**: NOT TESTED BY BETA 2 STAGE 1

## Stage 1 Review Gate
`BETA_2_STAGE_1_EVIDENCE_REVIEW_COMPLETE` requires an evidence review artifact that:
1. Inventories all Stage 1 evidence collected.
2. Maps evidence to every active Stage 1 hypothesis.
3. Identifies critical incidents.
4. Preserves contradictory evidence.
5. Separates user evidence from observer interpretation.
6. Issues PRESERVE / REVISE / REJECT / INSUFFICIENT_EVIDENCE decisions.
7. Identifies concepts not actually tested.
8. Records implications for Beta 3 planning.
9. Identifies whether any Beta 2 trust-critical behavior must be reconsidered before Beta 3.
10. Receives an explicit founder architecture decision.

Until those conditions are met, `BETA_2_STAGE_1_EVIDENCE_REVIEW_COMPLETE = FALSE`. No implementation task is authorized by the evidence protocol.


## Field Package Authority
The explicit authority chain for Stage 1 evidence collection is:

`STAGE_1_EVIDENCE_PROTOCOL.md`
|
v
`STAGE_1_OBSERVER_FIELD_GUIDE.md`
|
v
`STAGE_1_EVIDENCE_LOG_TEMPLATE.md`
|
v
Actual observation records
|
v
Stage 1 evidence review artifact
|
v
Founder architecture decision

* The evidence protocol defines methodology.
* The observer field guide defines session conduct.
* The evidence log template defines capture structure.
* Actual observations contain evidence.
* The final evidence review issues hypothesis decisions.

Do not let the field guide redefine architectural hypotheses.
Do not let individual evidence logs change decision rules.
