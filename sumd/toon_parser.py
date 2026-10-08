"""toon_parser — parse *.testql.toon.yaml scenario files into structured dicts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _process_config_kv(line: str, config: dict[str, str]) -> None:
    """Process a single config key-value line."""
    if m := re.match(r"^\s{2}([a-z_]+),\s*(.+)$", line):
        k, v = m.group(1), m.group(2).strip()
        if not k.startswith("detected") and "${" not in v:
            config[k] = v


def _parse_toon_block_config(lines: list[str]) -> dict[str, str]:
    """Extract CONFIG key-value pairs from toon file lines."""
    config: dict[str, str] = {}
    in_block = False
    for line in lines:
        if re.match(r"^CONFIG\[\d+\]", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^[A-Z_]+\[\d+\]", line) or line.startswith("#"):
                in_block = False
            else:
                _process_config_kv(line, config)
    return config


def _parse_toon_block_api(content: str) -> list[dict[str, Any]]:
    """Extract API endpoint rows from toon content."""
    api_rows = re.findall(
        r"^\s+(GET|POST|PUT|DELETE|PATCH),\s+(/[^\s,]+),\s+(\d+)"
        r"(?:\s+#\s*(\S+)\s+-\s*(.+)|\s+#\s*(.+))?",
        content,
        re.MULTILINE,
    )
    endpoints: list[dict[str, Any]] = []
    for method, path, status, op_id, summary_a, summary_b in api_rows:
        ep: dict[str, Any] = {"method": method, "path": path, "status": int(status)}
        if op_id:
            ep["operationId"] = op_id
        summary = (summary_a or summary_b or "").strip()
        if summary:
            ep["summary"] = summary
        endpoints.append(ep)
    return endpoints


def _parse_toon_block_assert(lines: list[str]) -> list[dict[str, str]]:
    """Extract ASSERT rows from toon file lines."""
    rows: list[dict[str, str]] = []
    in_block = False
    for line in lines:
        if re.match(r"^ASSERT\[\d+\]", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^[A-Z_]+\[\d+\]", line) or line.startswith("#"):
                in_block = False
            elif m := re.match(r"^\s{2}([a-z_]+),\s*([<>=!]+),\s*(.+)$", line):
                rows.append(
                    {
                        "field": m.group(1),
                        "op": m.group(2),
                        "expected": m.group(3).strip(),
                    }
                )
    return rows


def _parse_generic_block(
    lines: list[str],
    block_prefix: str,
    pattern: str,
    key_names: tuple[str, str],
) -> list[dict[str, str]]:
    """Extract key-value rows from a named toon block."""
    rows: list[dict[str, str]] = []
    in_block = False
    for line in lines:
        if re.match(rf"^{re.escape(block_prefix)}\[\d+\]", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^[A-Z_]+\[\d+\]", line) or line.startswith("#"):
                in_block = False
            elif m := re.match(pattern, line):
                rows.append({key_names[0]: m.group(1), key_names[1]: m.group(2).strip()})
    return rows


def _parse_toon_block_performance(lines: list[str]) -> list[dict[str, str]]:
    """Extract PERFORMANCE rows from toon file lines."""
    return _parse_generic_block(
        lines, "PERFORMANCE", r"^\s{2}([a-z_]+),\s*(.+)$", ("metric", "threshold")
    )


def _parse_toon_block_navigate(lines: list[str]) -> list[str]:
    """Extract NAVIGATE url rows from toon file lines."""
    urls: list[str] = []
    in_block = False
    for line in lines:
        if re.match(r"^NAVIGATE\[\d+\]", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^[A-Z_]+\[\d+\]", line) or line.startswith("#"):
                in_block = False
            elif stripped := line.strip():
                urls.append(stripped)
    return urls


def _parse_toon_block_gui(lines: list[str]) -> list[dict[str, str]]:
    """Extract GUI action rows from toon file lines."""
    return _parse_generic_block(
        lines, "GUI", r"^\s{2}(\w+),\s*(.+)$", ("action", "selector")
    )


def _parse_toon_file(f: Path) -> dict[str, Any]:
    """Parse a single *.testql.toon.yaml file into a scenario dict."""
    content = f.read_text(encoding="utf-8")
    lines = content.splitlines()

    def _match(pattern: str) -> str:
        m = re.search(pattern, content, re.MULTILINE)
        return m.group(1).strip() if m else ""

    return {
        "file": f.name,
        "rel_path": str(f),
        "name": _match(r"^#\s*SCENARIO:\s*(.+)") or f.stem,
        "type": _match(r"^#\s*TYPE:\s*(\S+)") or "unknown",
        "generated": _match(r"^#\s*GENERATED:\s*(\S+)") or "false",
        "detectors": _match(r"^#\s*DETECTORS:\s*(.+)"),
        "config": _parse_toon_block_config(lines),
        "endpoints": _parse_toon_block_api(content),
        "asserts": _parse_toon_block_assert(lines),
        "performance": _parse_toon_block_performance(lines),
        "navigate": _parse_toon_block_navigate(lines),
        "gui": _parse_toon_block_gui(lines),
    }


def extract_testql_scenarios(proj_dir: Path) -> list[dict[str, Any]]:
    """Scan all *.testql.toon.yaml and testql-scenarios/*.yaml files in project."""
    collected: dict[str, Path] = {}  # stem -> path, dedup by stem

    # 1. testql-scenarios/ directory (any *.yaml)
    for f in sorted((proj_dir / "testql-scenarios").glob("*.yaml")):
        collected[f.name] = f

    # 2. root-level *.testql.toon.yaml files
    for f in sorted(proj_dir.glob("*.testql.toon.yaml")):
        collected[f.name] = f

    # 3. nested <pkg>/scenarios/**/*.testql.toon.yaml
    scenarios_dir = proj_dir / proj_dir.name / "scenarios"
    if scenarios_dir.is_dir():
        for f in sorted(scenarios_dir.glob("*.testql.toon.yaml")):
            collected[f.name] = f

    scenarios = []
    for f in sorted(collected.values(), key=lambda p: p.name):
        try:
            sc = _parse_toon_file(f)
        except Exception:
            continue
        # Store relative path for display (relative to proj_dir)
        try:
            sc["rel_path"] = str(f.relative_to(proj_dir))
        except ValueError:
            sc["rel_path"] = f.name
        scenarios.append(sc)

    return scenarios
