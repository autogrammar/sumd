"""Scan helpers — extracted from cli.py to reduce god-module size."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

from sumd.parser import SUMDParser, parse_file, validate_sumd_file
from sumd.pipeline import RenderPipeline
from sumd.extractor import extract_package_json, extract_pyproject
from sumd.cli_doql import _detect_project_type, _generate_doql_less
_SKIP_DIRS = {
    ".venv",
    "venv",
    "node_modules",
    ".git",
    "__pycache__",
    ".sumd-tools",
    "site-packages",
    "dist",
    "build",
    "target",
    "state",
    "artifacts",
    ".tox",
    ".mypy_cache",
    ".worktrees",
    "twinerd-bench-results",
    "benchmarks",
    "bench-results",
}

_PROJECT_MARKER_FILES: frozenset[str] = frozenset({
    # Python
    "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "requirements.txt",
    # JavaScript / TypeScript / Node / Deno / Bun
    "package.json", "deno.json", "deno.jsonc", "bun.lockb",
    # Rust
    "Cargo.toml",
    # Go
    "go.mod",
    # Java / Kotlin / Scala / Groovy
    "pom.xml", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts", "build.sbt",
    # Ruby
    "Gemfile",
    # PHP
    "composer.json",
    # Swift / Apple
    "Package.swift",
    # Dart / Flutter
    "pubspec.yaml",
    # Elixir
    "mix.exs",
    # Haskell
    "stack.yaml", "cabal.project",
    # Clojure
    "project.clj", "deps.edn",
    # C / C++ / native
    "CMakeLists.txt", "meson.build", "configure.ac", "Makefile", "GNUmakefile",
    # Generic / DevOps
    "Taskfile.yml", "Taskfile.yaml",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    # SUMD-specific markers (already-described projects)
    "SUMD.md", "SUMR.md", "app.doql.less", "app.doql.css", "goal.yaml",
})

_PROJECT_MARKER_GLOBS: tuple[str, ...] = (
    "*.csproj", "*.fsproj", "*.vbproj", "*.sln",   # .NET
    "*.gemspec",                                    # Ruby gems
    "*.cabal",                                      # Haskell
    "*.podspec",                                    # CocoaPods
)


def _is_project_dir(d: Path) -> bool:
    """Return True if *d* contains any known project-marker file."""
    try:
        names = {p.name for p in d.iterdir() if p.is_file()}
    except (PermissionError, OSError):
        return False
    if names & _PROJECT_MARKER_FILES:
        return True
    for pattern in _PROJECT_MARKER_GLOBS:
        try:
            if next(d.glob(pattern), None) is not None:
                return True
        except (PermissionError, OSError):
            continue
    return False


def _should_skip_dir(d: Path) -> bool:
    """Return True if directory should be skipped during project walk."""
    if not d.is_dir():
        return True
    if d.name.startswith("."):
        return True
    if d.name in _SKIP_DIRS:
        return True
    return False


def _process_walk_entry(d: Path, projects: list[Path], max_depth: int | None, depth: int) -> None:
    """Process a single directory entry during project walk."""
    if _should_skip_dir(d):
        return
    try:
        if _is_project_dir(d):
            projects.append(d)
        else:
            _walk_projects(d, projects, max_depth, depth + 1)
    except PermissionError:
        pass


def _walk_projects(
    path: Path, projects: list[Path], max_depth: int | None, depth: int
) -> None:
    """Recursively collect project directories (containing any known marker)."""
    if max_depth is not None and depth > max_depth:
        return
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name)
    except PermissionError:
        return
    for d in entries:
        _process_walk_entry(d, projects, max_depth, depth)


def _detect_projects(workspace: Path, max_depth: int | None = None) -> list[Path]:
    """Return sorted list of subdirectories that look like project roots.

    A directory is considered a project if it contains any file listed in
    :data:`_PROJECT_MARKER_FILES` or matching :data:`_PROJECT_MARKER_GLOBS`
    (pyproject.toml, package.json, Cargo.toml, go.mod, pom.xml, Gemfile,
    composer.json, Dockerfile, Taskfile.yml, Makefile, …).
    """
    projects: list[Path] = []
    _walk_projects(workspace, projects, max_depth, 0)
    return projects


def _ensure_venv(tools_dir: Path, venv_dir: Path, tool_list: list[str]) -> None:
    """Create virtual env and install tools if not already present."""
    if venv_dir.exists():
        return
    tools_dir.mkdir(exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], capture_output=True)
    pip_path = venv_dir / "bin" / "pip"
    if not pip_path.exists():
        pip_path = venv_dir / "Scripts" / "pip.exe"
    for pkg in tool_list:
        subprocess.run([str(pip_path), "install", "-q", pkg], capture_output=True)


def _tool_bin(bin_dir: Path, name: str) -> Path:
    """Return path to *name* executable, preferring non-.exe variant."""
    plain = bin_dir / name
    return plain if plain.exists() else bin_dir / f"{name}.exe"


# Tool-specific CLI argument templates
_TOOL_ARGS: dict[str, list[str]] = {
    "code2llm": ["{proj_dir}", "-f", "all", "-o", "{out}", "--no-chunk"],
    "redup":    ["scan", "{proj_dir}", "--format", "toon", "--output", "{out}"],
    "vallm":    ["batch", "{proj_dir}", "--recursive", "--format", "toon", "--output", "{out}"],
}


def _run_one_tool(tool: str, bin_dir: Path, proj_dir: Path, project_output: Path) -> None:
    """Run a single analysis tool if its arg template is known."""
    template = _TOOL_ARGS.get(tool)
    if template is None:
        return
    args = [
        a.replace("{proj_dir}", str(proj_dir)).replace("{out}", str(project_output))
        for a in template
    ]
    subprocess.run([str(_tool_bin(bin_dir, tool))] + args, capture_output=True, cwd=str(proj_dir))


def _run_analysis_tools(
    proj_dir: Path,
    tool_list: list[str],
    skip_tools: "set[str] | None" = None,
) -> None:
    """Install and run code2llm/redup/vallm analysis tools for a project.

    skip_tools: tools already run by _refresh_analysis_files() that should
                not be executed again (avoids double-running on --analyze).
    """
    skip_tools = skip_tools or set()
    tools_dir = proj_dir / ".sumd-tools"
    venv_dir = tools_dir / "venv"
    project_output = proj_dir / "project"

    _ensure_venv(tools_dir, venv_dir, tool_list)

    bin_dir = venv_dir / "bin"
    if not bin_dir.exists():
        bin_dir = venv_dir / "Scripts"

    project_output.mkdir(exist_ok=True)

    for tool in tool_list:
        if tool not in skip_tools:
            _run_one_tool(tool, bin_dir, proj_dir, project_output)


def _export_sumd_json(proj_dir: Path, doc) -> None:
    """Write sumd.json for a project."""
    json_path = proj_dir / "sumd.json"
    data = {
        "project_name": doc.project_name,
        "description": doc.description,
        "sections": [
            {
                "name": s.name,
                "type": s.type.value,
                "content": s.content,
                "level": s.level,
            }
            for s in doc.sections
        ],
    }
    json_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _render_write_validate(
    proj_dir: Path,
    sumd_path: Path,
    raw: bool,
    profile: str,
) -> tuple:
    """Render SUMD content, write file, validate. Returns (doc, md_issues, cb_errors, cb_warnings, sources)."""
    content, sources = RenderPipeline(proj_dir, raw_sources=raw).run(
        profile=profile, return_sources=True
    )
    sumd_path.write_text(content, encoding="utf-8")
    result = validate_sumd_file(sumd_path, profile=profile)
    md_issues = result["markdown"]
    cb_errors = [c for c in result["codeblocks"] if c.kind == "error"]
    cb_warnings = [c for c in result["codeblocks"] if c.kind == "warning"]
    doc = parse_file(sumd_path)
    return doc, md_issues, cb_errors, cb_warnings, sources


def _echo_scan_result(proj_dir: Path, doc, sources: list, cb_warnings: list) -> None:
    """Print success line for a scanned project."""
    warn_str = f" \u26a0 {len(cb_warnings)} warnings" if cb_warnings else ""
    click.echo(
        f"  \u2705 {proj_dir.name:<18} {'ok':<10} {len(doc.sections):<10} {', '.join(sources)}{warn_str}"
    )


def _maybe_generate_doql(proj_dir: Path, fix: bool) -> None:
    """Generate app.doql.less BEFORE rendering SUMD so it gets included.

    Pull name/version from the most specific manifest available and
    pick language-appropriate defaults for the boilerplate.
    """
    project_type = _detect_project_type(proj_dir)
    pyproj = extract_pyproject(proj_dir)
    pkg_json = extract_package_json(proj_dir) if project_type == "node" else {}
    project_name = (
        pyproj.get("name")
        or pkg_json.get("name")
        or proj_dir.name
    )
    version = (
        pyproj.get("version")
        or pkg_json.get("version")
        or "0.1.0"
    )
    doql_path = _generate_doql_less(
        proj_dir, project_name, version,
        force=fix, project_type=project_type,
    )
    if doql_path:
        click.echo(f"   📝 Generated {doql_path.name} ({project_type})")


def _maybe_generate_testql(proj_dir: Path) -> None:
    """Generate testql scenarios via testql generate if none exist physically.

    Only runs when no *.testql.toon.yaml files are found in the project.
    Requires the testql CLI to be installed and available on PATH.
    """
    # Fast bounded check for existing testql files without traversing all nested subdirs
    has_testql = False
    for candidate in [proj_dir / "testql-scenarios", proj_dir / "tests", proj_dir]:
        if candidate.is_dir():
            try:
                if any(candidate.glob("*.testql.toon.yaml")) or any(candidate.glob("*/*.testql.toon.yaml")):
                    has_testql = True
                    break
            except (PermissionError, OSError):
                pass
    if has_testql:
        return

    try:
        result = subprocess.run(
            ["testql", "generate", str(proj_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            click.echo(f"   🧪 Generated testql scenarios")
        else:
            click.echo(f"   ⚠️  testql generate failed: {result.stderr[:200]}")
    except FileNotFoundError:
        click.echo("   ⚠️  testql not installed — skipping testql generation")
    except Exception as exc:
        click.echo(f"   ⚠️  testql generate error: {exc}")


def _run_doql_sync(proj_dir: Path, doql_sync: bool) -> None:
    """Run DOQL sync if enabled and required files exist."""
    if not doql_sync:
        return
    has_less = (proj_dir / "app.doql.less").exists()
    has_css = (proj_dir / "app.doql.css").exists()
    if not (has_less or has_css):
        return
    
    click.echo("   ⚙️  Syncing DOQL...")
    r = subprocess.run(
        ["doql", "sync"],
        cwd=str(proj_dir),
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        click.echo("   ✅ DOQL sync complete")
    else:
        click.echo(f"   ⚠️  DOQL sync failed: {r.stderr.strip() or r.stdout.strip()}", err=True)


def _finalize_scan(
    proj_dir: Path,
    doc,
    sources: list,
    cb_warnings: list,
    export_json: bool,
    run_analyze: bool,
    tool_list: list[str],
    doql_sync: bool,
    sumd_path: Path,
) -> dict:
    """Run post-scan actions: export JSON, run analysis, DOQL sync."""
    _echo_scan_result(proj_dir, doc, sources, cb_warnings)

    if export_json:
        _export_sumd_json(proj_dir, doc)

    if run_analyze:
        click.echo("   🔬 Running analysis...")
        _run_analysis_tools(proj_dir, tool_list)
        click.echo(f"   ✅ Analysis complete → {proj_dir / 'project'}/")

    _run_doql_sync(proj_dir, doql_sync)

    return {
        "status": "OK",
        "project_name": doc.project_name,
        "sections": len(doc.sections),
        "sources": sources,
        "path": str(sumd_path),
        "warnings": [c.message for c in cb_warnings],
    }


def _handle_scan_errors(proj_dir: Path, sumd_path: Path, doc, sources: list, md_issues: list, cb_errors: list) -> dict | None:
    """Format and return error dict if any issues are found, otherwise None."""
    all_errors = md_issues + [c.message for c in cb_errors]
    if not all_errors:
        return None

    click.echo(
        f"  \u274c {proj_dir.name:<18} {'invalid':<10} {len(doc.sections):<10} {', '.join(sources)}"
    )
    for e in all_errors:
        click.echo(f"       \u2193 {e}")
    return {"status": "INVALID", "errors": all_errors, "path": str(sumd_path)}


def _scan_one_project(
    proj_dir: Path,
    fix: bool,
    raw: bool,
    export_json: bool,
    run_analyze: bool,
    tool_list: list[str],
    parser_inst: "SUMDParser",
    profile: str = "rich",
    generate_doql: bool = False,
    doql_sync: bool = False,
    generate_testql: bool = False,
) -> dict:
    """Generate SUMD.md (or SUMR.md for refactor profile) for one project."""
    output_name = "SUMR.md" if profile == "refactor" else "SUMD.md"
    sumd_path = proj_dir / output_name

    if sumd_path.exists() and not fix:
        dash = "\u2013"
        click.echo(
            f"  {'~'} {proj_dir.name:<18} {'skip':<10} {dash:<10} already exists (use --fix to overwrite)"
        )
        return {"status": "SKIP", "path": str(sumd_path)}

    try:
        if generate_doql:
            _maybe_generate_doql(proj_dir, fix)

        if generate_testql:
            _maybe_generate_testql(proj_dir)

        doc, md_issues, cb_errors, cb_warnings, sources = _render_write_validate(
            proj_dir, sumd_path, raw, profile
        )
        
        error_result = _handle_scan_errors(proj_dir, sumd_path, doc, sources, md_issues, cb_errors)
        if error_result:
            return error_result

        return _finalize_scan(
            proj_dir, doc, sources, cb_warnings,
            export_json, run_analyze, tool_list, doql_sync, sumd_path,
        )

    except Exception as exc:
        dash = "\u2013"
        click.echo(f"  \u274c {proj_dir.name:<18} {'error':<10} {dash:<10} {exc}")
        return {"status": "ERROR", "error": str(exc)}
