# Community private-alpha release checklist

## Rights and visibility

- [x] License application code and generic community metadata under AGPL-3.0-or-later.
- [x] Exclude `curricula/outtalent.json` and maintainer-only deployment files from `git archive` source artifacts; permission is still required for any separate curriculum distribution.
- [ ] Make an explicit GitHub visibility decision (private is the default).
- [ ] Confirm starter metadata contains no copied problem statements.

## Security and privacy

- [ ] Run gitleaks (tracked files and full Git history) and investigate every finding.
- [ ] Scan built images with Trivy/Grype and record accepted residual CVEs.
- [ ] Verify no telemetry and no key in env, image layers, rendered Compose, browser payloads, or backups.
- [ ] Test hostile Origin/Referer against core and AI writes.
- [ ] Verify localhost-only binding and document any configured private proxy origins.

## Clean-install gates

- [ ] Build images from a clean checkout.
- [ ] Boot truly empty uniquely named core/AI volumes with AI disabled.
- [ ] Confirm health, browser smoke, 20 generic catalog entries/skills, and zero attempts, assignments, reviews, mastery/profile data.
- [ ] Confirm worker profile is absent by default and cannot mount core data.
- [ ] Start AI profile with fake unreachable configuration; verify fail-closed behavior and zero provider spend.
- [ ] Test backup, manifest/checksums, restore refusal, explicit restore, and both SQLite `quick_check`s.
- [ ] Run Ruff, pytest, TypeScript, Vitest, frontend build, and Playwright.
- [ ] Render Compose and scan for personal paths, legacy mounts, tailnet names, source mounts, public bindings, and leaked values.
- [ ] Tear down test containers, images if temporary, networks, and volumes.

## Release

- [ ] Review install/security/troubleshooting docs from a fresh operator perspective.
- [ ] Record commit SHA, image digests, exact gate outputs, and known residuals.
- [ ] Create a signed/annotated private-alpha tag only after all gates pass.
- [ ] Do not deploy or push as part of local verification unless separately authorized.
