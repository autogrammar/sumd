# Ticket 005: Optimize AST module analysis and ignore pattern matching in sumd

- **ID**: ticket-005
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-12

## Goal and scope

1. Add heavy directories to `_IGNORE_DIRS` in `sumd/extractor.py` (`c2004`, `c2004-git-backup`, `workshop`).
2. Optimize ignore patterns matching in `sumd/extractor.py` by compiling gitignore and sumdignore patterns into efficient compiled regular expressions with early directory segment pruning instead of repeated pure-Python `fnmatch` iterations.
3. Optimize Python module AST and complexity analysis in `_render_map_detail` by running `_analyse_py_module` across worker processes/threads in parallel, dropping map generation latency on large repositories from minutes to seconds.
4. Pass all test suites and repository governance checks.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] AC-02: `_IGNORE_DIRS` contains `c2004`, `c2004-git-backup`, and `workshop`.
- [x] AC-03: Ignore pattern matching uses compiled regex patterns and early pruning.
- [x] AC-04: AST module analysis is parallelized with graceful serial fallback.
- [x] AC-05: Test suite and governance checks pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
