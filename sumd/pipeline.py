"""sumd.pipeline — RenderPipeline: collect → build_sections → render → toc.

RenderPipeline is the new entry point for SUMD generation.
It replaces the monolithic generate_sumd_content() but currently runs
alongside it — generate_sumd_content() is unchanged and still works.

CURRENT STATE (Faza 1 scaffold):
  Only MetadataSection is registered. Other sections fall back to the
  existing _render_* functions in renderer.py (via _render_legacy_sections).
  This approach allows incremental migration one section at a time — each
  section can be extracted without breaking the output.

MIGRATION PATH:
  1. Add new Section class to sumd/sections/
  2. Add to SECTION_REGISTRY in sumd/sections/__init__.py
  3. Remove the corresponding _render_* call from _render_legacy_sections()
  4. Verify output is bit-identical, tests pass

ACCEPTANCE (Faza 1 complete):
  _render_legacy_sections() is empty, generate_sumd_content() is a thin
  wrapper calling RenderPipeline.run(profile='rich').
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from sumd.extractor import (
    extract_docker_compose,
    extract_dockerfile,
    extract_doql,
    extract_env,
    extract_goal,
    extract_makefile,
    extract_openapi,
    extract_package_json,
    extract_project_analysis,
    extract_pyproject,
    extract_pyqual,
    extract_python_modules,
    extract_readme_title,
    extract_requirements,
    extract_source_snippets,
    extract_swop,
    extract_taskfile,
    generate_map_toon,
    generate_project_logic,
    required_tools_for_profile,
)
from sumd.sections import PROFILES, SECTION_REGISTRY
from sumd.sections.base import RenderContext
from sumd.toon_parser import extract_testql_scenarios


def _map_module_count(text: str) -> int:
    """Extract the module count from a map.toon.yaml `M[<n>]:` header line, or -1 if absent."""
    m = re.search(r"^M\[(\d+)\]:", text, re.MULTILINE)
    return int(m.group(1)) if m else -1


def _is_code2llm_owned_map(text: str) -> bool:
    """Return whether the canonical map declares code2llm ownership."""
    return "# producer: code2llm | artifact: map.toon.yaml" in text[:2048]


def _refresh_map_toon(proj_dir: Path) -> None:
    """Regenerate project/map.toon.yaml and project/logic.pl from current source before embedding.

    Called automatically by RenderPipeline._collect() so that every
    `sumd scan` / `sumd .` / `sumr .` embeds up-to-date analysis and Prolog logic files.

    generate_map_toon() only introspects Python modules in depth (via `ast`);
    other languages are listed but not analysed for imports/exports/functions.
    A richer map.toon.yaml may already be on disk (e.g. written by `code2llm`
    just before sumd runs in the same pipeline) — never regress that file to
    one covering fewer modules, since that would silently drop information
    instead of refreshing it.

    Silently skips if generation fails.
    """
    try:
        map_path = proj_dir / "project" / "map.toon.yaml"
        skip_generate = False
        existing = ""
        if map_path.exists():
            try:
                with map_path.open("r", encoding="utf-8", errors="ignore") as f:
                    header = f.read(2048)
                if _is_code2llm_owned_map(header):
                    skip_generate = True
                else:
                    existing = map_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

        if not skip_generate:
            content = generate_map_toon(proj_dir)
            if content:
                regresses = False
                if existing:
                    regresses = _is_code2llm_owned_map(existing) or (
                        _map_module_count(existing) > _map_module_count(content)
                    )
                if not regresses:
                    map_path.parent.mkdir(parents=True, exist_ok=True)
                    map_path.write_text(content, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    try:
        logic_content = generate_project_logic(proj_dir)
        if logic_content:
            logic_path = proj_dir / "project" / "logic.pl"
            logic_path.parent.mkdir(parents=True, exist_ok=True)
            logic_path.write_text(logic_content, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _find_tools_bin_dir(proj_dir: Path) -> Path | None:
    """Return the venv bin directory for .sumd-tools, or None if not installed."""
    base = proj_dir / ".sumd-tools" / "venv"
    for subdir in ("bin", "Scripts"):
        candidate = base / subdir
        if candidate.exists():
            return candidate
    return None


def _run_tool_if_present(bin_dir: Path, name: str, args: list, proj_dir: Path) -> None:
    """Run *name* executable with *args* if it exists in *bin_dir*."""
    exe = bin_dir / name
    if not exe.exists():
        exe = bin_dir / f"{name}.exe"
    if exe.exists():
        subprocess.run([str(exe)] + args, capture_output=True, cwd=str(proj_dir))


def _refresh_analysis_files(proj_dir: Path, profile: str) -> None:
    """Run only the external tools required for the given profile.

    Called from RenderPipeline._collect() before extract_project_analysis()
    so analysis files are always fresh when embedded.  Silently skips any
    tool not installed in .sumd-tools/venv.

    profile: 'minimal' | 'light' | 'rich' | 'refactor'
    """
    tools_needed = required_tools_for_profile(profile)
    if not tools_needed:
        return

    bin_dir = _find_tools_bin_dir(proj_dir)
    if not bin_dir:
        return  # tools not installed — skip silently

    project_output = proj_dir / "project"
    project_output.mkdir(parents=True, exist_ok=True)

    try:
        if "code2llm" in tools_needed:
            _run_tool_if_present(
                bin_dir, "code2llm",
                ["./", "-f", "toon", "-o", str(project_output), "--no-chunk"],
                proj_dir,
            )
        if "redup" in tools_needed:
            _run_tool_if_present(
                bin_dir, "redup",
                ["scan", str(proj_dir), "--format", "toon", "--output", str(project_output)],
                proj_dir,
            )
        if "vallm" in tools_needed:
            _run_tool_if_present(
                bin_dir, "vallm",
                ["batch", str(proj_dir), "--recursive",
                 "--format", "toon", "--output", str(project_output)],
                proj_dir,
            )
    except Exception:  # noqa: BLE001
        pass  # non-fatal


# ---------------------------------------------------------------------------
# Source collection helpers (moved from renderer.py)
# ---------------------------------------------------------------------------


def _collect_tool_sources(
    pyproj: dict, reqs: list, tasks: list, makefile: list, scenarios: list
) -> list[str]:
    """Collect source labels for file-based tool inputs."""
    sources: list[str] = []
    if pyproj:
        sources.append("pyproject.toml")
    if reqs:
        sources.extend(r["file"] for r in reqs)
    if tasks:
        sources.append("Taskfile.yml")
    if makefile:
        sources.append("Makefile")
    if scenarios:
        sources.append(f"testql({len(scenarios)})")
    return sources


def _doql_sources(doql: dict) -> list[str]:
    """Return doql source labels if any doql content is present."""
    if doql.get("app") or doql.get("workflows") or doql.get("entities"):
        return doql.get("sources", ["app.doql.less"])
    return []


def _collect_pkg_sources(
    pyproj: dict,
    reqs: list,
    tasks: list,
    makefile: list,
    scenarios: list,
    openapi: dict,
    doql: dict,
    pyqual: dict,
    goal: dict,
    env_vars: list,
) -> list[str]:
    """Collect source labels for code/pipeline sources."""
    sources = _collect_tool_sources(pyproj, reqs, tasks, makefile, scenarios)
    if openapi.get("endpoints"):
        sources.append(f"openapi({len(openapi['endpoints'])} ep)")
    sources.extend(_doql_sources(doql))
    if pyqual.get("stages"):
        sources.append("pyqual.yaml")
    if goal.get("name"):
        sources.append("goal.yaml")
    if env_vars:
        sources.append(".env.example")
    return sources


def _collect_infra_sources(
    dockerfile: dict,
    compose: dict,
    pkg_json: dict,
    modules: list,
    project_analysis: list,
) -> list[str]:
    """Collect source labels for infra/module sources."""
    sources: list[str] = []
    if dockerfile:
        sources.append("Dockerfile")
    if compose.get("services"):
        sources.append(compose.get("file", "docker-compose.yml"))
    if pkg_json.get("name"):
        sources.append("package.json")
    if modules:
        sources.append(f"src({len(modules)} mod)")
    if project_analysis:
        sources.append(f"project/({len(project_analysis)} analysis files)")
    return sources


def _collect_sources(
    pyproj: dict,
    reqs: list,
    tasks: list,
    makefile: list,
    scenarios: list,
    openapi: dict,
    doql: dict,
    pyqual: dict,
    goal: dict,
    env_vars: list,
    dockerfile: dict,
    compose: dict,
    pkg_json: dict,
    modules: list,
    project_analysis: list,
    swop: dict,
) -> list[str]:
    """Build the list of source labels that contributed data to this SUMD."""
    sources = _collect_pkg_sources(
        pyproj, reqs, tasks, makefile, scenarios, openapi, doql, pyqual, goal, env_vars
    ) + _collect_infra_sources(dockerfile, compose, pkg_json, modules, project_analysis)
    if swop.get("sources"):
        sources.extend(swop["sources"])
    return sources


def _inject_toc(content: str) -> str:
    """Inject a ## Contents TOC block before ## Metadata."""
    import re

    h2_sections = re.findall(r"^## (.+)$", content, re.MULTILINE)
    if not h2_sections:
        return content
    toc_lines = ["## Contents", ""]
    for sec in h2_sections:
        anchor = re.sub(r"[^\w\s-]", "", sec.lower()).strip()
        anchor = re.sub(r"\s+", "-", anchor)
        toc_lines.append(f"- [{sec}](#{anchor})")
    toc_lines.append("")
    toc_block = "\n".join(toc_lines)
    return re.sub(
        r"(\n## Metadata\n)", f"\n{toc_block}\n## Metadata\n", content, count=1
    )


class RenderPipeline:
    """Collect project data → build sections → render → inject TOC.

    Usage:
        pipeline = RenderPipeline(proj_dir)
        content, sources = pipeline.run(profile='rich', return_sources=True)
    """

    def __init__(self, proj_dir: Path, raw_sources: bool = True) -> None:
        self.proj_dir = proj_dir.resolve()
        self.raw_sources = raw_sources
        self._profile: str = "rich"  # set before _collect() by run()

    # ── Phase 1: collect ────────────────────────────────────────────────

    def _collect(self) -> RenderContext:
        """Extract all project data and build RenderContext."""
        proj_dir = self.proj_dir
        pkg_name = proj_dir.name

        pyproj = extract_pyproject(proj_dir)
        tasks = extract_taskfile(proj_dir)
        scenarios = extract_testql_scenarios(proj_dir)
        openapi = extract_openapi(proj_dir)
        doql = extract_doql(proj_dir)
        pyqual = extract_pyqual(proj_dir)
        modules = extract_python_modules(proj_dir, pkg_name)
        title = extract_readme_title(proj_dir)
        reqs = extract_requirements(proj_dir)
        makefile = extract_makefile(proj_dir)
        goal = extract_goal(proj_dir)
        env_vars = extract_env(proj_dir)
        dockerfile = extract_dockerfile(proj_dir)
        compose = extract_docker_compose(proj_dir)
        pkg_json = extract_package_json(proj_dir)
        swop = extract_swop(proj_dir)

        # Auto-regenerate map.toon.yaml — pure-Python, always fast.
        _refresh_map_toon(proj_dir)

        # Run only the external tools needed by the active profile (if installed).
        _refresh_analysis_files(proj_dir, self._profile)

        project_analysis = extract_project_analysis(
            proj_dir, refactor=(self._profile == "refactor")
        )
        source_snippets = extract_source_snippets(proj_dir, pkg_name)

        name = pyproj.get("name", pkg_name)
        version = pyproj.get("version", "0.0.0")
        description = pyproj.get("description", title or name)
        sources_used = _collect_sources(
            pyproj,
            reqs,
            tasks,
            makefile,
            scenarios,
            openapi,
            doql,
            pyqual,
            goal,
            env_vars,
            dockerfile,
            compose,
            pkg_json,
            modules,
            project_analysis,
            swop,
        )

        return RenderContext(
            proj_dir=proj_dir,
            name=name,
            version=version,
            description=description,
            py_req=pyproj.get("python_requires", ""),
            license_=pyproj.get("license", ""),
            ai_model=pyproj.get("ai_model", ""),
            deps=pyproj.get("dependencies", []),
            dev_deps=pyproj.get("dev_dependencies", []),
            scripts=pyproj.get("scripts", []),
            tasks=tasks,
            scenarios=scenarios,
            openapi=openapi,
            doql=doql,
            pyqual=pyqual,
            modules=modules,
            reqs=reqs,
            makefile=makefile,
            goal=goal,
            env_vars=env_vars,
            dockerfile=dockerfile,
            compose=compose,
            pkg_json=pkg_json,
            project_analysis=project_analysis,
            source_snippets=source_snippets,
            swop=swop,
            raw_sources=self.raw_sources,
            sources_used=sources_used,
            title=title or name,
        )

    # ── Phase 2: build sections ─────────────────────────────────────────

    def _build_registered_sections(
        self, ctx: RenderContext, profile: str
    ) -> list[list[str]]:
        """Run all registered Section classes that match the profile."""
        allowed = PROFILES.get(profile, set())
        rendered: list[list[str]] = []
        for cls in SECTION_REGISTRY:
            section = cls()
            if section.name not in allowed:
                continue
            if not section.should_render(ctx):
                continue
            rendered.append(section.render(ctx))
        return rendered

    def _render_legacy_sections(self, ctx: RenderContext) -> list[list[str]]:
        """All sections have been migrated to Section classes. Returns empty list."""
        return []

    # ── Phase 3: render ─────────────────────────────────────────────────

    def _assemble(self, ctx: RenderContext, profile: str) -> str:
        """Assemble all section lines into final markdown."""
        L: list[str] = []
        a = L.append

        # Document header
        a(f"# {ctx.title}")
        a("")
        if profile == "refactor":
            a(
                "SUMD - Structured Unified Markdown Descriptor for AI-aware project refactorization"
            )
        else:
            a(ctx.description)
        a("")

        # Registered sections (new architecture)
        for section_lines in self._build_registered_sections(ctx, profile):
            L.extend(section_lines)

        # Intent section (inline — will become IntentSection later)
        a("## Intent")
        a("")
        a(ctx.description)
        a("")

        # Legacy sections (not yet migrated)
        for section_lines in self._render_legacy_sections(ctx):
            L.extend(section_lines)

        return "\n".join(L)

    # ── Public API ───────────────────────────────────────────────────────

    def run(
        self, profile: str = "rich", return_sources: bool = False
    ) -> str | tuple[str, list[str]]:
        """Run the full pipeline and return rendered SUMD content.

        Args:
            profile: 'minimal' | 'light' | 'rich' | 'refactor'
            return_sources: if True, return (content, sources_used) tuple

        Returns:
            str or (str, list[str])
        """
        self._profile = profile
        ctx = self._collect()
        raw = self._assemble(ctx, profile)
        content = _inject_toc(raw)

        if return_sources:
            return content, ctx.sources_used
        return content


__all__ = ["RenderPipeline"]
