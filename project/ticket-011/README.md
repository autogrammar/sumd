# Ticket 011: Validate declared files independently of analysis exclusions

- **ID**: ticket-011
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-05

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested continuing the tellmesh
analysis repairs and merging reviewed changes on 2026-11-05. Coordination:
Planfile PLF-19979. Protected independent review and merge remain required.

Validate files declared by SUMD markpact blocks against actual presence inside
the project. Source-analysis exclusions must not turn existing generated reports
or test contracts into missing files. Preserve errors for missing files,
directories, dangling links and external targets.

Owned implementation: `sumd/validator.py`, `tests/test_architectural_logic.py`.

## Acceptance criteria

- [x] AC-01: User authorized the bounded repair and protected publication.
- [x] AC-02: Existing excluded/non-source declared files pass existence checks.
- [x] AC-03: Missing or out-of-project declared targets remain errors.
- [x] AC-04: 17 focused tests, all 280 tests and the managed gate pass.
- [ ] AC-05: Independent review and merge bind the exact frozen head.

## Tracking boundary

Validation: `pytest -q` — 280 passed; fatal Ruff checks passed; the managed
gate reported zero errors/warnings. Reading the real tellmesh fixture with the
candidate validator returns no architectural errors (previously six false
missing-file findings). Cached source facts cannot hide a new missing declaration.

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
