# Ticket 002: add autoupdate support and bounded quality repair

- **ID**: ticket-002
- **Owner**: trusted-runner:PLF-17129
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-07

## Goal and scope

Represent the complete frozen PR diff for autoupdate support and bounded
performance/quality repairs as the single integration ticket for
autogrammar/sumd#7. The repair is bound to frozen head
`1e71fac166a4741f1b0e73e4ceff1ef648bcf10b` and target PR-diff base
`687877a4459c901d7bd3eeceba1cd42e8e955bda`.

## Acceptance criteria

- [x] AC-01: Ticket 002 is the sole active integration ticket owning every
  candidate path in the frozen PR diff and this repair delta.
- [x] AC-02: Focused repository tests for the autoupdate and quality repair pass.
- [ ] AC-03: todo2code comparison evidence is emitted for ticket2dsl,
  code2dsl, docs2dsl and service2dsl projections.

## Validation evidence

- `python3 -m json.tool project/ticket-002/intent.json`
- `PYTHONDONTWRITEBYTECODE=1 python3 .governance/governance_check.py --root . --manifest .governance/manifest.json --lock .governance/manifest.lock.json --stack-profiles .governance/stack-profiles.json` -> PASS
- `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_cli_helpers.py tests/test_extractor.py tests/test_parser.py tests/test_pipeline.py tests/test_sections.py tests/test_statement.py -q` -> 120 passed
- `todo2code`, `ticket2dsl`, `code2dsl`, `docs2dsl` and `service2dsl` were not available on PATH in this checkout.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
