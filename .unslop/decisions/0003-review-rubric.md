---
status: accepted
date: 2026-11-19
decision-makers: Kun Kim
---

# Review rubric

## Context and Problem Statement

Tools enforce style, types, coverage and boundaries. Judgement calls remain, and a reviewer asked to find problems always finds some. The reviewer needs a narrow mandate.

## Decision Outcome

A change is blocked only for a concrete failing scenario in one of these areas:

1. An acceptance criterion in `SPEC.md` is not met, or no test proves it.
2. Correctness or security fails for a specific input.
3. A speculative abstraction, option or extension point has no current caller.
4. Untyped input is checked deep inside instead of parsed once at the boundary.
5. A combination of booleans or nullable fields allows a state that should be impossible.
6. A layer only passes calls through, or an interface is as large as its implementation.
7. Business logic performs I/O.
8. A test would still pass with the behaviour deleted.
9. The change contradicts an accepted decision record.
10. An error is not an RFC 9457 problem detail, an API change breaks consumers, or a new event field is required.

Style, naming and formatting are out of scope.

### Confirmation

The `reviewer` agent reads this record and ends every review with `VERDICT: PASS` or `VERDICT: BLOCK`. A feature is marked passing in `feature_list.json` only after a `PASS`.
