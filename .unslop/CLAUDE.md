# unslop

This repository adopted unslop. Existing code keeps its findings, recorded in `.unslop/baseline/`; new and changed code meets the full bar.

- `scripts/fast-check` must pass before you stop. It rejects comments on lines you add, new suppressions or skipped tests, edits to existing tests, any lint or type finding beyond the baseline, failing tests, and changed lines no test covers.
- When a check names a finding, fix the code. Never move code to dodge a count, and never add a suppression.
- Fixing old findings is welcome; say so in your final message so a human can run `scripts/rebaseline`.
- You cannot edit `.unslop/`, `scripts/`, build files, lockfiles or CI. If you need a change there, say what and why in your final message.
- Decisions that bind every change are in `.unslop/decisions/`.
