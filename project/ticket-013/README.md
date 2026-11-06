# Ticket 013: Preserve quoted atoms when loading Prolog clauses

- **ID**: ticket-013
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-06

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user directs continued project analysis
repairs and protected publication under PLF-19979 / PLF-19985. This disjoint
dependency of ticket-012 repairs the native Prolog loader: punctuation inside
quoted command atoms must remain data. Do not change architectural rules,
execute commands or alter the prior ticket's lease/worktree.

## Acceptance criteria

- [x] AC-01: Quoted dots, percent signs, comment delimiters and rule/operator text remain literal atom data.
- [x] AC-02: Escaped quotes, backslashes and multiline text round-trip correctly, including a trailing backslash before another argument.
- [x] AC-03: Actual comments, clauses, rules and inequality terms retain their behavior.
- [x] AC-04: Native regression/full tests and managed governance pass.
- [ ] AC-05: Exact-head independent validation and protected merge complete before ticket-012 publication.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

Validation: the new tests reproduced nine failures before the repair and pass
10/10 afterward. The full native suite passes 290 tests with the original
managed governance plugin. No architecture rule or application automation was
changed. Protected exact-head publication is still pending.
