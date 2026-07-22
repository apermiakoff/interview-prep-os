# Claude Code prompt — community AI frontend design review

Review the community AI frontend as a senior product designer, accessibility engineer, and security-minded frontend architect. Do not redesign unrelated screens or modify files unless asked. Inspect the running app at desktop 1366px and mobile 390px and review the code/contracts.

Evaluate:
- whether Coach feels like a paper-first learning instrument rather than generic chat SaaS;
- explicit assisted/non-independent disclosure and strict separation from hidden canonical hints;
- disabled, empty, queued, generating, failed, retry, cancellation, and budget/conflict states;
- stable retry idempotency and honest durable SSE/polling behavior (no fake streaming);
- active-session exclusion of problem-scoped AI, with navigation to the exact session Coach;
- immediate non-independent Finish state after an accepted session AI request, including polling failures;
- artifact version/provenance visibility and text-only lesson safety;
- semantic visualization validation, fallback, controls, and absence of model HTML/JS execution;
- diagnosis epistemics: observations versus unconfirmed hypotheses, confidence/evidence, sparse-data language, user-action interventions, and no mastery mutation;
- setup guidance, server-only secrets, masked status, and absence of credential inputs/values;
- keyboard order, mobile background inertness/body lock/Shift+Tab trapping/Escape restoration, non-modal desktop dock behavior, labels, contrast, 44px mobile controls, and horizontal overflow at 390px;
- consistency with existing typography, spacing, theme tokens, and paper-first hierarchy.

Return a prioritized report with severity, evidence (route, viewport, selector/file), user impact, and a concrete recommendation. Include a short “what works” section, accessibility blockers, security/privacy concerns, and screenshot suggestions. Distinguish contract defects from visual polish. Do not claim a test passed unless you ran it.
