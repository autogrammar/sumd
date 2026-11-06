# Ticket 012: Preserve Taskfile names and complete DOQL workflow steps

- **ID**: ticket-012
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-06

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requests continued implementation and
protected merging of the project analysis repairs under PLF-19979 / PLF-19985.
The native allocator bound this ticket to extractor.py and its regression tests.
Preserve Taskfile names in architectural facts and complete DOQL workflow
commands containing templates, braces, semicolons or multiple lines. Keep real
missing-step and missing-automation diagnostics. No automation command is run.

Native qualification found a separate Prolog loader defect: a dot followed by
whitespace inside a quoted command splits its fact. The remaining Oqlos finding
is reproduced by `adopt . --output`. Repair that disjoint loader dependency
through its own native ticket before requesting publication of this ticket.
That dependency was independently merged in PR #17 at a769ff88c7ab84350c2a301cf127a537f1b3a65f.

The two defects produce false workflow findings in the generated Maskservice
and Oqlos descriptors. Source repairs use this canonical delivery checkout and
its current fenced lease; the prior merged ticket-011 is preserved separately.

## Acceptance criteria

- [x] AC-01: Taskfile facts retain the extracted task names, including namespaced tasks.
- [x] AC-02: Workflow facts retain complete template and multiline commands.
- [x] AC-03: Missing automation and missing steps remain validation failures.
- [x] AC-04: Native regression/full tests and the managed gate pass; both real workspace inputs are qualified.
- [ ] AC-05: Publication uses exact-head independent validation and protected merge.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

Validation: all 301 native tests pass after integrating the quoted-Prolog
dependency. Native architectural validation with freshly generated scoped facts
reports zero findings for both real workspace inputs (previously Maskservice67
and Oqlos22). Rules are unchanged, reports are not yet refreshed, and no workflow
command was executed. Protected exact-head publication remains pending.
