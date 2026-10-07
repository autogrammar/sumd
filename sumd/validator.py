"""SUMD Validator — validate markdown structure and fenced codeblocks."""

import re
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Codeblock format validators
# ---------------------------------------------------------------------------

_CODEBLOCK_RE = re.compile(
    r"^```(?P<lang>\w+)(?:[ \t]+(?P<meta>[^\n]*))?$\n(?P<body>[\s\S]*?)\n^```[ \t]*$",
    re.MULTILINE,
)

_MARKPACT_META_RE = re.compile(r"markpact:(?P<kind>\w+)(?:[ \t]+(?P<attrs>.*))?")


@dataclass
class CodeBlockIssue:
    line: int
    lang: str
    kind: str  # 'error' | 'warning'
    message: str
    meta: str = ""


def _validate_yaml_body(body: str, path: str) -> list[str]:
    """Check YAML body is parseable."""
    try:
        import yaml

        yaml.safe_load(body)
        return []
    except Exception as e:
        return [f"invalid YAML in {path}: {e}"]


def _validate_less_css_body(body: str, path: str) -> list[str]:
    """Basic sanity: balanced braces."""
    opens = body.count("{")
    closes = body.count("}")
    if opens != closes:
        return [f"unbalanced braces in {path}: {opens} open vs {closes} close"]
    return []


def _validate_mermaid_body(body: str, path: str) -> list[str]:
    """Check mermaid block starts with a valid diagram type."""
    first = body.strip().split("\n")[0].strip()
    valid_starts = (
        "flowchart",
        "graph",
        "sequenceDiagram",
        "classDiagram",
        "stateDiagram",
        "erDiagram",
        "gantt",
        "pie",
        "journey",
    )
    if not any(first.startswith(s) for s in valid_starts):
        return [f"mermaid block in {path} has unknown diagram type: {first!r}"]
    return []


def _validate_toon_body(body: str, path: str) -> list[str]:
    """Check toon block has at least one recognised section header."""
    headers = re.findall(r"^[A-Z_]+(?:\[.*?\])?(?:\{.*?\})?:", body, re.MULTILINE)
    if not headers:
        return [
            f"toon block in {path} has no section headers (e.g. HEALTH, ALERTS, MODULES)"
        ]
    return []


def _validate_bash_body(body: str, path: str) -> list[str]:
    """Check bash block is non-empty and doesn't contain obvious placeholders."""
    if not body.strip():
        return [f"empty bash block in {path}"]
    if "<YOUR_" in body or "TODO" in body:
        return [f"unresolved placeholder in bash block at {path}"]
    return []


def _validate_deps_body(body: str, path: str) -> list[str]:
    """Each line of a deps block should be a valid pip requirement or empty."""
    issues = []
    for i, line in enumerate(body.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # PEP 508 / npm lookalike: name with optional extras/version
        if not re.match(r"^(?:@[A-Za-z0-9_\-\.]+\/)?[A-Za-z0-9_\-\.]+", line):
            issues.append(f"deps line {i} in {path} looks invalid: {line!r}")
    return issues


_LANG_VALIDATORS = {
    "yaml": _validate_yaml_body,
    "less": _validate_less_css_body,
    "css": _validate_less_css_body,
    "mermaid": _validate_mermaid_body,
    "toon": _validate_toon_body,
    "bash": _validate_bash_body,
    "text": _validate_deps_body,  # markpact:deps python
}

_VALID_MARKPACT_KINDS = {
    # generic
    "file",
    "deps",
    "run",
    "test",
    "bootstrap",
    "publish",
    # semantic (Phase 2)
    "doql",
    "openapi",
    "testql",
    "taskfile",
    "pyqual",
    "analysis",
    "swop",
}
_MARKPACT_REQUIRED_ATTRS = {
    "file": "path",
    "doql": "path",
    "openapi": "path",
    "testql": "path",
    "taskfile": "path",
    "pyqual": "path",
    "analysis": "path",
    "swop": "path",
}


def _validate_markpact_meta(
    mp: re.Match, line_no: int, lang: str, meta: str, issues: list
) -> None:
    """Check markpact annotation kind and required attributes."""
    kind = mp.group("kind")
    attrs = mp.group("attrs") or ""
    if kind not in _VALID_MARKPACT_KINDS:
        issues.append(
            CodeBlockIssue(
                line_no,
                lang,
                "error",
                f"unknown markpact kind {kind!r} (valid: {', '.join(sorted(_VALID_MARKPACT_KINDS))})",
                meta,
            )
        )
    req_attr = _MARKPACT_REQUIRED_ATTRS.get(kind)
    if req_attr and f"{req_attr}=" not in attrs:
        issues.append(
            CodeBlockIssue(
                line_no,
                lang,
                "error",
                f"markpact:{kind} requires {req_attr}=... but got: {attrs!r}",
                meta,
            )
        )


def _extract_group(m: re.Match, name: str) -> str:
    """Safely extract and strip a regex group."""
    val = m.group(name)
    return val.strip() if val else ""


def _check_one_codeblock(
    m: re.Match, content: str, source: str
) -> list[CodeBlockIssue]:
    """Validate a single fenced code block match. Returns zero or more issues."""
    issues: list[CodeBlockIssue] = []
    lang = _extract_group(m, "lang")
    meta = _extract_group(m, "meta")
    body = _extract_group(m, "body")
    line_no = content[: m.start()].count("\n") + 1
    ctx = f"{source}:{line_no}"

    # ── markpact annotation checks ──────────────────────────────────
    mp = _MARKPACT_META_RE.search(meta)
    if mp:
        _validate_markpact_meta(mp, line_no, lang, meta, issues)

    # ── body emptiness ──────────────────────────────────────────────
    if not body:
        issues.append(
            CodeBlockIssue(line_no, lang, "warning", f"empty code block (lang={lang!r})", meta)
        )
        return issues

    # ── language-specific body validation ───────────────────────────
    if lang == "toon":
        if "markpact:testql" in meta:
            return issues

    validator = _LANG_VALIDATORS.get(lang)
    if validator:
        for msg in validator(body, ctx):
            issues.append(CodeBlockIssue(line_no, lang, "error", msg, meta))

    return issues


def validate_codeblocks(content: str, source: str = "SUMD.md") -> list[CodeBlockIssue]:
    """Validate all fenced code blocks in *content*.

    Checks:
    - markpact annotation syntax (kind, required attrs)
    - language-specific body format (yaml parseable, braces balanced, etc.)
    - non-empty bodies
    """
    issues: list[CodeBlockIssue] = []
    for m in _CODEBLOCK_RE.finditer(content):
        issues.extend(_check_one_codeblock(m, content, source))
    return issues


# ---------------------------------------------------------------------------
# Markdown structure validators
# ---------------------------------------------------------------------------

_REQUIRED_H2 = {
    "metadata",
    "intent",
    "architecture",
    "deployment",
}
_REQUIRED_H2_REFACTOR = {"metadata", "architecture", "refactoring analysis"}
_RECOMMENDED_H2 = {"interfaces"}  # present in API projects but not required

_METADATA_FIELDS = {"name", "version"}  # required metadata bullet keys


def _check_h1(lines: list[str], source: str) -> list[str]:
    """Return error if H1 title is missing."""
    if not any(re.match(r"^# [^#]", line) for line in lines):
        return [f"{source}: missing H1 title"]
    return []


def _check_required_sections(
    lines: list[str], source: str, profile: str = "rich"
) -> list[str]:
    """Return errors for any missing required H2 sections."""
    found_h2 = {
        re.sub(r"`.*?`", "", line[3:]).strip().lower()
        for line in lines
        if line.startswith("## ")
    }
    required = _REQUIRED_H2_REFACTOR if profile == "refactor" else _REQUIRED_H2
    return [
        f"{source}: missing required section '## {req.title()}'"
        for req in required
        if not any(req in h for h in found_h2)
    ]


def _check_metadata_fields(lines: list[str], source: str) -> list[str]:
    """Return errors for missing required metadata bullet fields."""
    in_meta = False
    meta_found: set[str] = set()
    for line in lines:
        if line.startswith("## Metadata"):
            in_meta = True
            continue
        if in_meta and line.startswith("## "):
            break
        if in_meta:
            m = re.match(r"- \*\*(\w+)\*\*:", line)
            if m:
                meta_found.add(m.group(1).lower())
    return [
        f"{source}: metadata section missing '**{req}**' field"
        for req in _METADATA_FIELDS
        if req not in meta_found
    ]


def _check_unclosed_fences(lines: list[str], source: str) -> list[str]:
    """Return error if there is an odd number of ``` fence markers."""
    if sum(1 for line in lines if re.match(r"^```", line)) % 2 != 0:
        return [f"{source}: unclosed fenced code block (odd number of ``` markers)"]
    return []


def _strip_fenced_code_blocks(content: str) -> str:
    """Remove fenced code blocks so code syntax like arr[i]() is not validated as markdown links."""
    return re.sub(r"```[\s\S]*?```", "", content)


def _check_empty_links(content: str, source: str) -> list[str]:
    """Return errors for markdown links with empty href outside fenced code blocks."""
    stripped = _strip_fenced_code_blocks(content)
    return [
        f"{source}: empty link href for [{text}]()"
        for text in re.findall(r"\[([^\]]+)\]\(\s*\)", stripped)
    ]


def validate_markdown(
    content: str, source: str = "SUMD.md", profile: str = "rich"
) -> list[str]:
    """Validate SUMD markdown structure.

    Checks:
    - H1 title present
    - Required H2 sections present (profile-aware)
    - Metadata section has name and version bullets
    - No broken markdown links [text]() with empty href
    - No unclosed fenced code blocks
    """
    lines = content.splitlines()
    return (
        _check_h1(lines, source)
        + _check_required_sections(lines, source, profile)
        + _check_metadata_fields(lines, source)
        + _check_unclosed_fences(lines, source)
        + _check_empty_links(content, source)
    )


# ---------------------------------------------------------------------------
# Combined validator
# ---------------------------------------------------------------------------


def _is_project_root_for_validation(proj_dir: Path) -> bool:
    """Return False for dummy / partial directories used in dogfood tests."""
    return any(
        (proj_dir / marker).exists()
        for marker in ("app.doql.less", "Makefile", "Taskfile.yml")
    )


def _load_prolog_db(proj_dir: Path):
    """Build and return a loaded PrologDB or None if rules file is missing."""
    from sumd.extractor import generate_project_logic
    from sumd.prolog_engine import PythonPrologDB

    facts_text = generate_project_logic(proj_dir)
    rules_path = Path(__file__).parent / "rules.pl"
    if not rules_path.exists():
        return None
    rules_text = rules_path.read_text(encoding="utf-8")
    db = PythonPrologDB()
    db.parse_and_load(facts_text)
    db.parse_and_load(rules_text)
    return db


def _query_prolog_violations(db) -> list[str]:
    """Run invalid(Error) query and return formatted violation strings."""
    from sumd.prolog_engine import PythonPrologEngine

    engine = PythonPrologEngine(db)
    return sorted(
        f"architecture inconsistency: {r['Error']}"
        for r in engine.query("invalid(Error)")
        if r.get("Error")
    )


def validate_project_architecture(proj_dir: Path) -> list[str]:
    """Run Prolog-based architectural consistency checks on the project.

    Returns:
        list[str]: list of logic-based consistency errors.
    """
    try:
        if not _is_project_root_for_validation(proj_dir):
            return []
        db = _load_prolog_db(proj_dir)
        if db is None:
            return []
        return _query_prolog_violations(db)
    except Exception as e:
        return [f"failed to execute architectural logic validation: {e}"]


def validate_sumd_file(path: Path, profile: str = "rich") -> dict:
    """Run all validators on a SUMD.md file.

    Returns:
        {
          "source": str,
          "markdown": list[str],        # structural issues
          "codeblocks": list[CodeBlockIssue],  # format issues
          "logic": list[str],            # architectural logic issues
          "ok": bool,
        }
    """
    content = path.read_text(encoding="utf-8")
    source = path.name
    md_issues = validate_markdown(content, source, profile)
    cb_issues = validate_codeblocks(content, source)
    
    # Run logic validation if it's a project SUMD
    proj_dir = Path(path).parent.resolve()
    logic_issues = validate_project_architecture(proj_dir)
    
    return {
        "source": str(path),
        "markdown": md_issues,
        "codeblocks": cb_issues,
        "logic": logic_issues,
        "ok": not md_issues and not logic_issues and not any(c.kind == "error" for c in cb_issues),
    }
