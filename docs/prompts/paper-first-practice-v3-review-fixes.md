# Interview Prep OS V3 — independent review remediation

Work only in `/home/hermes/interview-prep-os` on the existing uncommitted V3 diff.

## Non-negotiable safety boundary

- Do NOT deploy, restart containers, commit, push, or touch `data/interview-prep.db`.
- All Python/app/test commands MUST have `INTERVIEW_PREP_DB=/tmp/interview-prep-v3-review.db` explicitly in their environment.
- Playwright MUST use its disposable server/DB; never set it to `127.0.0.1:8765` or the Tailscale production URL.
- Keep compatibility with the v4 production DB; migration 5 remains additive. Add migration 6 only if a schema/trigger change genuinely requires it.
- Add focused regression tests for every Critical/High issue and each Medium issue you fix.

## Required fixes

### Backend/data integrity

1. **Request-id ownership**: start-session idempotency keys must be bound to origin + problem + assignment semantics. Reusing a key for another problem, another origin, or another assignment must return a deterministic 409, never return an unrelated session. Same-request retries for the same operation must still return the original session.
2. **Attempt-id ownership/payload**: repeated attempt event IDs are idempotent only when session, problem, and normalized payload are the same. Cross-session/problem or changed-payload reuse must return 409. A valid retry must return the canonical already-recorded outcome and closed session.
3. **Concurrent attempt retry**: move duplicate/status decisions under the write transaction so concurrent identical retries converge on the same success rather than one 409.
4. **Legacy scheduled partial failure**: once the legacy action succeeds, a sync failure must preserve a durable state that causes retry to sync only, never execute the legacy action twice. Add a test that simulates action success, sync failure, then retry success and asserts one action invocation.
5. **Scheduled hint concurrency**: serialize/deduplicate scheduled legacy hint reveals so concurrent identical reveals invoke the legacy action once.
6. **Skip semantics**: skipped attempts must not create `attempt_errors` or downstream trap evidence even if a failure tag is supplied. Normalize skip failure tag appropriately and test it.
7. **Scheduled consistency**: enforce or transactionally validate that a scheduled session problem matches its assignment problem. A DB trigger is acceptable if SQLite cannot express the cross-table invariant in CHECK.
8. **Compatibility hint endpoint**: enforce the same sequential H1→H4 reveal policy. A direct H4 request before H1–H3 must fail without returning the H4 body. Preserve legitimate sequential compatibility behavior.
9. **Legacy session linkage**: after a scheduled legacy action/import succeeds, link the canonical imported attempt row to the practice session when it can be identified unambiguously. Never claim linkage if ambiguous; add tests/document exact limitation.

### Frontend/API contract

10. **Retry-safe event ID**: create one attempt event ID per finish operation/session and retain it across retries after ambiguous network failures. Do not generate a new UUID on each click. Reset it only after success, modal cancellation followed by a new finish operation, or materially changed facts.
11. **Canonical result**: attempt API response must expose canonical normalized evidence/result/independence. Route and message based on server-returned canonical facts, not stale requested facts.
12. **Exact duration preview**: freeze elapsed minutes when opening Finish and submit that exact displayed value. Timer may continue visually or pause, but preview and payload must match.
13. **Duration cap**: clamp or otherwise handle timers over 360 minutes so an old tab can still record honestly without API rejection; disclose the cap in preview if applied.
14. **Same-problem extra practice**: if Surprise me or Practice starts an ad-hoc session for the currently scheduled problem, still state clearly that the scheduled assignment remains scheduled and is not completed by this extra session.
15. **Problem-detail race**: abort or guard stale detail/lesson requests across hash navigation so previous problem data cannot overwrite the current problem.
16. **Modal accessibility**: move focus into Finish, trap focus, Escape closes, and restore focus to the trigger. Add unit coverage where practical.
17. **Library races/errors**: prevent pending bulk refresh from overwriting newer filter results and surface mutation failures.
18. **CTA fallback**: derive LeetCode URL from slug when nullable URL is absent.
19. **Filter accessibility**: active status segments expose `aria-pressed` or equivalent selected state.

### Test/deployment safety

20. **Playwright production guard**: refuse to run mutating e2e tests when `PLAYWRIGHT_BASE_URL` points at `127.0.0.1:8765`, the tailnet production hostname, or any non-explicitly-allowed external target. Prefer removing the override escape hatch entirely. Add a cheap config/unit verification if possible.
21. **Pre-migration backup**: make the documented deployment path require a verified SQLite backup before the service is recreated/migration 5 starts. Add a script or Make target if that makes the invariant executable; verify backup integrity. Document restore caveat: old image requires the v4 backup.

## Verification required before stopping

Run all from repository root, with a disposable DB environment for Python:

```bash
INTERVIEW_PREP_DB=/tmp/interview-prep-v3-review.db uv run ruff format app scripts tests
INTERVIEW_PREP_DB=/tmp/interview-prep-v3-review.db uv run ruff check app scripts tests
INTERVIEW_PREP_DB=/tmp/interview-prep-v3-review.db uv run pytest
npm test
npm run lint
npm run build
npm audit --audit-level=high
npm run test:e2e
git diff --check
```

Also hash `data/interview-prep.db` before and after and prove it did not change. Return exact counts, failures, files changed, and any finding deliberately left unresolved with rationale. Do not claim success without command output.