---
status: accepted
date: 2026-11-19
decision-makers: Kun Kim
---

# No code comments

## Context and Problem Statement

Agents copy whatever the codebase shows. Comments drift from the code, excuse workarounds, and teach the next change to add more of both.

## Decision Outcome

Source files contain no comments. Meaning lives in names, types, small functions and tests. Prose that explains a decision lives in this folder.

Allowed exceptions, each enforced by the checker's allowlist rather than by judgment:

- A shebang line.
- Tool directives that change behaviour and have no other syntax: Go `//go:`, `//line` and `//export`, TypeScript `/// <reference>`, `// swift-tools-version`, Dockerfile `# syntax=`, and a Python encoding declaration on the first two lines.
- Generated files whose first five lines contain `Code generated … DO NOT EDIT` or `@generated`.

Configuration and documentation files (YAML, TOML, JSON, Markdown, HTML) are not source and may contain comments.

Suppression directives (`eslint-disable`, `@ts-expect-error`, `//nolint`, `# noqa`, `# type: ignore`, `@Suppress`) are not exceptions. They are banned separately.

### Confirmation

`scripts/check-comments` parses every source file and runs in `scripts/fast-check`, in the end-of-session check and in CI. A comment fails the build.
