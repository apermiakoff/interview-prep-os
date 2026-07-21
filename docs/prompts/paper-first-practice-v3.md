# Interview Prep OS V3 — Paper-first flexible practice

You are implementing a production-grade product correction in `/home/hermes/interview-prep-os`.

## User feedback

The current Solve room looks raw and poor. The user solves on paper and will never use an in-browser scratchpad. The single active Critical Connections assignment locks Solve. The user wants to search/filter the Library and launch any problem for additional learning without replacing the scheduled assignment. Critical Connections is the only problem with a real lesson/hints; all problems need honest instructional support.

## Hard boundaries

- Do not deploy, commit, push, run Docker Compose, mutate `data/interview-prep.db`, or write to `/home/hermes/.hermes/leetcode-coach`.
- Use temporary/test databases only.
- Preserve all existing evidence, scheduled assignments, reviews, memory, and curriculum rows.
- Keep Today's active scheduled assignment independent from extra practice.
- No public exposure or auth changes.
- No runtime LLM/network call in a GET endpoint.
- Never label generated/template-derived material as curated.
- Never expose unrevealed hint bodies in bootstrap, problem detail, or session GET responses.
- Preserve dark and paper themes.
- Keep navigation `Today · Brain · Roadmap · Library`.
- Run tests yourself but do not claim deployment.

## Product invariant

Model three distinct entities:

1. Scheduled assignment — formal commitment.
2. Practice session — execution context, origin `scheduled` or `ad_hoc`.
3. Attempt event — immutable learner evidence.

An ad hoc session may produce attempt/memory/review/skill evidence, but must never modify any scheduled assignment row, call the legacy coach subprocess, or claim the daily assignment was completed.

## Backend requirements

### Migration

Add atomic forward-only migrations after current version 4:

- `practice_sessions`: id, problem_id, nullable assignment_id, origin scheduled/ad_hoc, active/completed/abandoned status, mode, goal, timebox, highest_hint, request_id unique, started/updated/completed timestamps; enforce origin/assignment consistency.
- `session_hint_events`: unique session+level and timestamps.
- nullable `attempt_events.session_id` + index.
- optional `content_artifacts`/`hint_steps` if useful, or implement an equally explicit deterministic content resolver without overengineering. Existing low-link lesson remains curated.

Do not rebuild historical evidence tables merely to add strict checks. Failed migrations must roll back DDL and version marker. Existing rows get `session_id NULL`.

### APIs

Implement typed schemas and routes:

- `POST /api/problems/{problem_id}/practice-sessions` — start idempotent ad hoc session.
- `POST /api/assignments/{assignment_id}/sessions` — start/continue scheduled session.
- `GET /api/practice-sessions/{session_id}` — session plus problem and instructional availability; no unrevealed hint bodies.
- `POST /api/practice-sessions/{session_id}/hints/{level}/reveal` — reveal only the next allowed hint, record assistance idempotently, return one body.
- `POST /api/practice-sessions/{session_id}/attempts` — record immutable evidence.
- `POST /api/practice-sessions/{session_id}/abandon` — close only the session.
- `GET /api/problems/{problem_id}/lesson` — lazy full lesson, provenance-aware.

Keep old assignment mutation endpoints temporarily for compatibility.

### Attempt service

Extract common attempt evidence logic from assignment-only recording:

- any hint makes Green normalize to Yellow and independent false;
- skipped creates no memory penalty;
- non-skipped attempts update memory and adaptive review;
- structured failure error insertion remains honest;
- scheduled session transitions its assignment exactly as before;
- ad hoc session closes only itself; scheduled assignment remains byte-for-byte unchanged;
- ad hoc routes must never invoke `_run_legacy_action` or `_sync_legacy`.
- duplicate request/event/hint IDs must not duplicate evidence.

### Instructional content

All 88 existing problems are mapped to at least one of 30 skills. Implement a deterministic resolver so every mapped problem has honest support:

- Critical Connections retains the curated low-link semantic lesson and its curated hint ladder where present.
- Other problems receive a problem-aware instructional scaffold assembled at runtime from stored deterministic metadata: title, LeetCode number, difficulty, core/supporting skills, skill descriptions, prerequisites, and pattern. This is `provenance=generated`, `generator=deterministic-skill-scaffold/1.0`, never `curated`.
- Lesson stages: Understand, Derive, Implement, Test, Reflect. Avoid pretending to know a problem-specific recurrence or code if metadata cannot justify it. Ask useful targeted questions using mapped skill names/descriptions and prerequisites.
- Four hints must progress from recognition → structural direction → invariant/state → implementation/testing checklist. They must be problem-aware and skill-aware. Do not return the other three bodies when one is revealed.
- Resolution metadata: availability, provenance curated/generated/unavailable, scope problem/skill/pattern, generator/version, and label.
- Problem detail returns availability/metadata only; lesson endpoint returns full body.
- A content view does not create learner evidence.

### Problem detail/library

Every problem detail must expose `can_start_ad_hoc=true`, content availability/provenance, and whether a scheduled assignment exists for that problem. An open ad hoc session must not set catalog status `active`; that status remains scheduled-only. A separate optional open-practice indicator is fine.

## Frontend requirements

### Routing and launch

- Solve routes by explicit session ID: `#solve/{sessionId}`.
- Bare `#solve` creates/continues a scheduled session for compatibility.
- Every Library row has actual `Practice` and external `↗` actions.
- Every Problem Detail has `Start paper attempt`, even when another scheduled problem is active.
- Starting ad hoc practice must not present a destructive active-assignment conflict. Show concise copy: `Extra practice. Critical Connections remains scheduled for July 21.`
- Include `Surprise me` / random practice using the currently filtered result set or a server endpoint; it must create an ad hoc session, not replace scheduled work.
- Fix the existing bulk refresh bug by retaining `track`.

### Premium paper-first Solve redesign

Visual stance: **editorial command cockpit** — Linear/Raycast precision, sparse technical typography, fewer cards/pills, rules and spacing instead of nested gray panels. It must not look like an IDE, form builder, or generic admin dashboard.

Remove from default UI and code:

- scratchpad textarea;
- notes autosave state/API traffic;
- permanently expanded outcome panel;
- giant circular timer;
- always-visible Reset;
- four repetitive `Hidden until requested` blocks;
- authored trigger/bottleneck/invariant answers shown before solving.

Desktop structure:

1. Sticky session command bar below masthead:
   - Back to Library
   - Scheduled assignment / Extra practice label
   - title + #id/difficulty/timebox
   - `Open on LeetCode ↗` prominent
   - compact timer (`READY 35:00 Start`, `LIVE 27:14 Pause`)
   - `Finish attempt` primary command
2. Main grid: paper attempt brief + 320px sticky hint rail.
3. Paper brief:
   - goal;
   - `Read on LeetCode. Reason on paper. Implement there.`
   - three ruled columns: Clarify (inputs/constraints/edge cases), Derive (brute force/bottleneck/invariant), Verify (dry run/complexity/counterexample).
   - generic prompts only; no leaked answers.
4. Hint rail:
   - H0 independent / highest used;
   - sequential staircase; only next hint enabled;
   - first reveal has explicit confirmation that attempt becomes assisted;
   - revealed hints remain visible;
   - future hints compactly locked;
   - generated/curated provenance visible but quiet.
5. Finish attempt opens modal/sheet. First select one mutually exclusive outcome: Independent, Assisted/slow, Needed solution, Skipped. Then facts:
   - Accepted by LeetCode separate;
   - blocker required for Yellow/Red;
   - explanation quality optional;
   - independent derived from outcome and hint use, not a contradictory checkbox;
   - final line previews exact record;
   - one `Record attempt` submit button.

Timer:

- compact command, no ring;
- elapsed seconds persist in sessionStorage keyed by session ID through route changes/reload;
- Start/Pause state-dependent control; reset in overflow or secondary control with confirmation;
- reaching zero does not auto-submit.

Responsive:

- >=1100px two columns, hint rail sticky.
- 760–1099 one column and hint drawer.
- <760 two-row session bar; full-width LeetCode CTA; Hints and Finish >=44px; framework stacked; finish as bottom sheet; no horizontal overflow at 390px.

### Library redesign

- Task copy: `Practice any problem.`
- Search/filters before oversized status dashboard.
- Fewer visible status segments: All, Due, Learning, Backlog; other statuses remain filterable.
- Remove density toggle; use one premium ~62px row.
- Four columns desktop: Problem+metadata, Evidence, State/due, Actions.
- Practice button is discoverable, not hover-only; external link separate.
- Loading over existing rows must be visible.
- Search placeholder supports title, number, or slug.
- Keep server pagination maximum 25.
- Mobile retains pattern and real action buttons.

## Tests / acceptance

Backend:

- migration preservation, idempotency, and forced rollback;
- ad hoc start while Critical Connections scheduled;
- ad hoc Green/Yellow/Red/skip and abandon preserve scheduled assignment byte-for-byte;
- real attempt links session; assignment_id null for ad hoc;
- memory/review update for non-skipped ad hoc attempts;
- skip/abandon no memory penalty;
- duplicate session/event/hint is idempotent;
- unavailable/unknown/mismatched/completed conflicts;
- ad hoc routes prove legacy subprocess not called;
- all mapped problems resolve available generated or curated lesson + hint metadata;
- resolver provenance and curated precedence;
- session GET and bootstrap contain no unrevealed hint bodies;
- hint endpoint returns only requested next hint;
- content views create no evidence.

Frontend/Playwright:

- Library → arbitrary different problem → Practice → Solve shows that problem;
- Today still shows Critical Connections scheduled;
- ad hoc attempt records on selected problem and leaves scheduled assignment active;
- every rendered Library row has Practice and external actions;
- problem details always offer Practice and honest content labels;
- paper-first Solve has no textarea/autosave UI;
- hints are sequential and policy-confirmed;
- Finish modal derives evidence facts correctly;
- mobile 390px no overflow and touch controls >=44px;
- both themes render coherently.

Run:

- Ruff format/check
- full Pytest
- Vitest
- TypeScript/Vite build
- npm audit
- Playwright desktop/mobile
- git diff --check

Do not deploy, commit, push, or touch the live DB. Finish with exact changed files, tests, known limitations, and migration/deployment notes.