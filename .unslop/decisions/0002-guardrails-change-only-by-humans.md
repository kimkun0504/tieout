---
status: accepted
date: 2026-11-19
decision-makers: Kun Kim
---

# Guardrail files change only through human review

## Context and Problem Statement

Agents under pressure to finish weaken the checks instead of fixing the code: they relax lint rules, lower thresholds, edit tests or replace a check script with one that always passes.

## Decision Outcome

Lint, type, test, build and CI configuration, the `scripts/` folder, `.claude/`, `CLAUDE.md`, dependency manifests, lockfiles and the accepted records in this folder are guardrail files. Agents cannot write them. A change to them comes from a human in a reviewed pull request. An agent may add a new record with status `proposed`; it takes effect when a human merges it.

Existing tests are guardrails too. An agent adds tests but does not modify or delete existing ones; a human applies the `tests-reviewed` label when a test change is intended.

### Confirmation

Claude Code permission deny rules, sandbox `denyWrite` and the protect-paths hook block agent writes locally. `scripts/check-diff` fails CI when existing tests change without the label. CODEOWNERS plus the branch ruleset require the owner's review for guardrail files.
