# Repository Operating Instructions

## Sources of Truth

Follow explicit user instructions. For repository documents, use this precedence:

1. `docs/ASSIGNMENT.md`: original employer requirements.
2. `docs/IMPLEMENTATION_SPEC.md`: technical contract, once approved by the user.
3. `PLAN.md`: milestone order and time budget.
4. Current implementation: existing baseline.

Follow the higher-priority source when documents conflict. Use `docs/DATASET_ANALYSIS.md` as supporting evidence, not an additional authority. Do not modify the original assignment or supplied datasets to resolve conflicts. If an explicit user request changes the agreed technical contract, record the authorized decision without asking for the same permission again.

Milestone 1 is completed and is the accepted code baseline. Milestones 2-8 follow PLAN in order. Existing SQLAlchemy, SQLite, application factory, sessions, modules, and Pydantic schemas are reasonable baseline decisions. Do not rebuild Milestone 1 to match a preferred architecture. Completion, review approval, and commit status are distinct; inspect the latest user instruction and Git history/status rather than treating uncommitted work as absent.

## One Milestone at a Time

For each authorized milestone:

1. Read its relevant contract and acceptance criteria in `docs/IMPLEMENTATION_SPEC.md`.
2. Inspect existing implementation, tests, and Git changes.
3. Implement only that milestone. Preserve reasonable architecture and user changes.
4. Avoid unrelated refactors and speculative features.
5. Add/update meaningful tests for introduced behavior, including ambiguous/failure cases.
6. Run relevant tests and verify every applicable acceptance criterion.
7. Report files changed, behavior implemented, tests/results, assumptions, and any specification deviations. Distinguish completed checks from unverified claims.
8. Stop for review. Never automatically begin another milestone.

Give concise progress updates during work. Do not ask for approval for routine implementation details already within the authorized milestone. If a task is documentation-only or inspection-only, honor that boundary.

## Scope and Refactoring

Keep the project appropriate for approximately 6-8 focused hours. Prefer the simplest correct solution and the existing local patterns.

No authentication/RBAC, Redis, Celery, queues/workers, event buses, deployment/scaling/monitoring infrastructure, analytics integrations, complex audit systems, HubSpot migration tooling, speculative services, or other assignment exclusions. No frontend unless explicitly authorized after stable core work and with spare time. No automatic merging of seed records.

Do not refactor working code merely because another structure looks cleaner. Refactor only to fix correctness, satisfy the current milestone/contract, materially reduce duplication or risk, or remove an obstacle to required behavior. Keep the change proportional and explain any material effect.

## Specification Changes

Do not silently deviate from `docs/IMPLEMENTATION_SPEC.md`. If implementation reveals a material problem:

1. Stop before redesigning the affected behavior.
2. Explain the concrete problem and evidence.
3. Explain its impact on correctness, scope, or later milestones.
4. Propose the smallest reasonable contract change.
5. Wait for user approval before implementing that change.

Minor internal details that do not alter behavior or architecture need no approval. This stop rule is required by this repository's user-defined specification policy; when it applies, identify the conflicting contract section and explain why approval is needed. An explicit user authorization for the exact change is sufficient; do not request it again. Previously documented acceptance of baseline decisions is not a new deviation.

## Testing

Run tests relevant to every implementation milestone. Do not claim completion while relevant tests fail. Report command, result, and material limitations; distinguish third-party warnings from failures.

Prefer a small number of meaningful tests and parameterized cases over inflated counts/coverage targets. Use temporary file-backed databases and the existing factory. Never test mutations against the user's development database or rewrite supplied datasets. Preserve tests for existing behavior, but update assertions that intentionally describe an earlier milestone, such as health-only OpenAPI routes.

Verify changes once at the appropriate scope; repeat or broaden checks when new code, failures, or unresolved risks justify it. Do not claim accuracy or performance that was not measured.

## Commits and Continuation

Do not commit a milestone until the user approves it. Do not push or publish without authorization. Do not amend previous commits or stage unrelated user changes silently.

When the user says `Approved. Commit and continue to the next milestone.`:

1. Confirm relevant tests for the just-approved work are passing; rerun if the state changed or passing evidence is unavailable.
2. Inspect staged/unstaged changes and commit only approved work with a concise conventional commit message.
3. Identify the next unimplemented milestone in PLAN, using implementation and conversation context.
4. Read its specification and acceptance criteria.
5. Implement only that milestone.
6. Run relevant tests and verify acceptance criteria.
7. Report the result and stop for review.

Do not commit the newly implemented milestone until it receives its own approval. `Commit` alone authorizes committing the approved current work, not beginning the next milestone. Never batch multiple future milestones into one continuation. Documentation approval does not by itself authorize application implementation.

## Documentation

Update README incrementally when a milestone adds run instructions, API behavior, or design decisions useful for the final submission. Keep those updates small and factual; do not reconstruct everything at the final milestone or describe planned features as implemented.

Preserve the user's intent while keeping public claims truthful, concise, and focused on the current validated system. Public documentation is not an exhaustive development diary. Keep superseded experiments/debugging history local only when useful; do not create unnecessary historical records. Solve documentation concerns with the closest truthful implementation rather than forcing irrelevant disclosures.

Update the specification's milestone status when acceptance criteria are met; approval/commit status still follows the user. Do not alter other milestones' contracts silently. Do not modify documents outside the current task when the user expressly limits the files to change.

## Final Verification and Optional Work

For the README/fresh-start milestone:

- Verify setup from a clean environment and initialization/import into a fresh temporary database.
- Verify documented commands, real application startup, restart preservation, and the relevant complete test suite.
- Explain important normalization, deduplication, extraction, conflict, and storage choices.
- Document provider/model/approximate cost if an LLM is actually used; otherwise describe fuzzy/rules behavior truthfully.
- Include realistic next steps, clearly separated from implemented features.
- Keep source/test/data/documentation deliverables available; exclude generated environments, databases, and caches from commits.

Dashboard work is optional. Never implement it while a core requirement is incomplete or unstable. At Milestone 8, honor the user's choice of dashboard, contingency fixes, or omission, and report what was actually done.

## Code quality rule

Code should optimize for correctness, readability, and simplicity within the take-home scope.

Prefer:

- clear, descriptive names
- small cohesive functions
- straightforward control flow
- explicit behavior over clever abstractions
- reuse of business rules instead of duplicated logic
- type hints on public interfaces and important functions
- clear separation between API, persistence, normalization, deduplication, and extraction logic
- comments only where they explain non-obvious reasoning or tradeoffs

Avoid:

- unnecessary abstraction layers
- premature generic utilities
- deep inheritance
- hidden side effects
- duplicated business rules
- dead code
- speculative extensibility
- large functions doing unrelated work
- comments that merely restate the code

Before declaring a milestone complete, review the changed code for:

1. correctness against IMPLEMENTATION_SPEC.md
2. readability
3. unnecessary complexity
4. duplicated logic
5. edge-case handling
6. testability
7. scope creep

Prefer the simplest implementation that remains easy to understand and test.