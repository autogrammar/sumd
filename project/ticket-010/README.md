# Ticket 010: Fix hardcoded paths in .cursor/mcp.json

- **ID**: ticket-010
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

Eliminate hardcoded `/home/tom` user paths from `.cursor/mcp.json` in accordance with `wellmanifest/nohardcode` rule `NOHARDCODE-009`.

## Acceptance criteria

- [x] AC-01: Replace hardcoded absolute user home paths with `${workspaceFolder}` and generic `koru` command.
- [x] AC-02: Governance check passes (`GOV-PASS`).
- [x] AC-03: All test suites pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
