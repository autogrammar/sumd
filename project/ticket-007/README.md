# Ticket 007: Add sumd path to application workstream in governance manifest

- **ID**: ticket-007
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

Add `sumd/**` to `application.ownedPaths` in `.governance/manifest.json` so that application-level changes to `sumd` pass governance check.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] AC-02: `.governance/manifest.json` includes `sumd/**` under `application.ownedPaths`.
- [x] AC-03: `bash project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
