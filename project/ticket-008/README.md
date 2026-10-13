# Ticket 008: Optimize map toon refresh and fast ignore pattern matching in sumd

- **ID**: ticket-008
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

1. Avoid redundant map regeneration in `_refresh_map_toon`: If `project/map.toon.yaml` already exists and is code2llm-owned (`_is_code2llm_owned_map`), skip `generate_map_toon` instead of spending 25+ seconds generating a map that will be discarded.
2. Optimize project logic fact extraction: Pass pre-collected file list into `_facts_project_files` and `_facts_python_analysis` instead of scanning the entire project filesystem twice.
3. Optimize gitignore and sumdignore pattern matching in `sumd/extractor.py` with fast literal dir/file matching and regex-based matching instead of repeated per-file linear fnmatch loops.
4. Add `maskservice.local` to `_IGNORE_DIRS`.
5. Guard `@server.list_tools()` and `@server.call_tool()` in `sumd/mcp_server.py` for compatibility with modern MCP SDKs.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] AC-02: `_refresh_map_toon` avoids calling `generate_map_toon` when a code2llm-owned map already exists.
- [x] AC-03: `generate_project_logic` collects files once instead of multiple filesystem walks.
- [x] AC-04: Ignore pattern matching uses fast literal/regex lookups.
- [x] AC-05: `sumd/mcp_server.py` imports cleanly without AttributeError.
- [x] AC-06: All tests and repository governance checks pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
