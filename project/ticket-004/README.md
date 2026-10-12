# Ticket 004: Fix codeblock link false-positive and expand ignore patterns in sumd

- **ID**: ticket-004
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-12

## Goal and scope

1. Strip tilde code fences (`~~~`) and inline code spans (`` `...` ``) in addition to backtick fences in `_strip_fenced_code_blocks` (`sumd/validator.py`) so code syntax like array indexing or computed properties is not mistaken for empty markdown links.
2. Add commonly ignored directories to `_IGNORE_DIRS` in `sumd/extractor.py` (`managed_components`, `vendor`, `.pytest_tmp`, `.test-cache`, `.code2llm_cache`, `.playwright-browsers`, `.dev-data`, `.dockuri`).

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] AC-02: `_strip_fenced_code_blocks` strips backticks, tildes, and inline code spans.
- [x] AC-03: `_IGNORE_DIRS` contains common heavy directories and test caches.
- [x] AC-04: Test suite and governance checks pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
