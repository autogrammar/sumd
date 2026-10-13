# Ticket 009: Add mcp.json to governance manifest and fix hardcoded cwd path

- **ID**: ticket-009
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

1. Add `mcp.json` to `integration.ownedPaths` in `.governance/manifest.json`.
2. Fix hardcoded `/home/tom` path in `mcp.json` by setting `"cwd": "."` adhering to `wellmanifest/nohardcode` (`NOHARDCODE-009`).

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] AC-02: `mcp.json` is declared under `integration.ownedPaths` in `.governance/manifest.json`.
- [x] AC-03: `mcp.json` uses `"cwd": "."` without hardcoded user directories.
- [x] AC-04: Repository governance check passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
