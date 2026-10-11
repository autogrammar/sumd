"""extractor — read project source files and extract structured metadata."""

from __future__ import annotations

import ast
import fnmatch
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_toml(path: Path) -> dict:
    try:
        import tomllib

        return tomllib.loads(path.read_text(encoding="utf-8"))
    except ImportError:
        import toml

        return toml.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def extract_pyproject(proj_dir: Path) -> dict[str, Any]:
    toml_path = proj_dir / "pyproject.toml"
    if not toml_path.exists():
        return {}
    try:
        data = _read_toml(toml_path)
        project = data.get("project", {})
        optional = project.get("optional-dependencies", {})
        dev_deps = optional.get("dev", [])
        pfix = data.get("tool", {}).get("pfix", {})
        return {
            "name": project.get("name", proj_dir.name),
            "version": project.get("version", "0.0.0"),
            "description": project.get("description", ""),
            "python_requires": project.get("requires-python", ""),
            "license": project.get("license", ""),
            "dependencies": project.get("dependencies", []),
            "dev_dependencies": dev_deps,
            "scripts": list(project.get("scripts", {}).keys()),
            "ai_model": pfix.get("model", ""),
        }
    except Exception:
        return {}


def _first_task_cmd(cmds: list) -> str:
    """Extract the first command string from a task's cmds list."""
    if not cmds:
        return ""
    if isinstance(cmds[0], str):
        return cmds[0]
    if isinstance(cmds[0], dict):
        return cmds[0].get("task", cmds[0].get("cmd", ""))
    return ""


def extract_taskfile(proj_dir: Path) -> list[dict[str, str]]:
    taskfile_path = proj_dir / "Taskfile.yml"
    if not taskfile_path.exists():
        return []
    try:
        data = yaml.safe_load(taskfile_path.read_text(encoding="utf-8"))
        tasks = data.get("tasks", {}) or {}
        result = []
        for task_name, body in tasks.items():
            if not isinstance(body, dict):
                continue
            desc = body.get("desc", "")
            cmd = _first_task_cmd(body.get("cmds", []))
            result.append({"name": task_name, "desc": desc, "cmd": cmd})
        return result
    except Exception:
        return []


def _process_openapi_method(
    method: str, spec: Any, path: str, seen: set[tuple], endpoints: list[dict]
) -> None:
    _HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
    if method not in _HTTP_METHODS or not isinstance(spec, dict):
        return
    key = (method.upper(), path)
    if key in seen:
        return
    seen.add(key)
    endpoints.append(
        {
            "method": method.upper(),
            "path": path,
            "operationId": spec.get("operationId", ""),
            "summary": spec.get("summary", ""),
            "tags": spec.get("tags", []),
        }
    )


def _parse_openapi_endpoints(paths: dict) -> list[dict]:
    """Extract endpoint dicts from the paths section of an OpenAPI spec."""
    endpoints: list[dict] = []
    seen: set[tuple] = set()
    for path, methods in paths.items():
        if not isinstance(methods, dict) or "://" in path:
            continue
        for method, spec in methods.items():
            _process_openapi_method(method, spec, path, seen, endpoints)
    return endpoints


def extract_openapi(proj_dir: Path) -> dict[str, Any]:
    openapi_path = proj_dir / "openapi.yaml"
    if not openapi_path.exists():
        return {}
    try:
        data = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
        info = data.get("info", {})
        paths = data.get("paths", {}) or {}
        schemas = list((data.get("components", {}) or {}).get("schemas", {}).keys())
        return {
            "title": info.get("title", ""),
            "version": info.get("version", ""),
            "description": info.get("description", ""),
            "endpoints": _parse_openapi_endpoints(paths),
            "schemas": schemas,
        }
    except Exception:
        return {}


def _parse_doql_entities(content: str) -> list[dict[str, Any]]:
    """Parse entity blocks from DOQL content."""
    entities: list[dict[str, Any]] = []
    for m in re.finditer(
        r'entity\[name="([^"]+)"\](?:\s*page\[name="([^"]+)"\])?\s*\{([^}]*)\}',
        content,
        re.DOTALL,
    ):
        attrs = dict(re.findall(r"(\w[\w-]*):\s*([^;]+);", m.group(3)))
        entry: dict[str, Any] = {"name": m.group(1)}
        if m.group(2):
            entry["page"] = m.group(2)
        if attrs:
            entry["attrs"] = attrs
        entities.append(entry)
    return entities


def _parse_doql_interfaces(content: str) -> list[dict[str, Any]]:
    """Parse interface and integration blocks from DOQL content."""
    interfaces: list[dict[str, Any]] = []
    for m in re.finditer(
        r'interface\[([^\]]+)\](?:\s*page\[name="([^"]+)"\])?\s*\{([^}]*)\}',
        content,
        re.DOTALL,
    ):
        attrs = dict(re.findall(r"(\w[\w-]*):\s*([^;]+);", m.group(3)))
        entry: dict[str, Any] = {"selector": m.group(1).strip()}
        if m.group(2):
            entry["page"] = m.group(2)
        entry.update(attrs)
        interfaces.append(entry)
    return interfaces


def _parse_doql_workflows(content: str) -> list[dict[str, Any]]:
    """Parse workflow blocks from DOQL content, deduplicated by name."""
    # _BLOCK matches content allowing {{template}} and {single} brace expressions
    _BLOCK = r"(?:[^{}]|\{\{[^}]*\}\}|\{[^}]*\})*"
    workflows_map: dict[str, dict[str, Any]] = {}
    for m in re.finditer(
        r"workflow\[([^\]]+)\]\s*\{(" + _BLOCK + r")\}", content, re.DOTALL
    ):
        name_m = re.search(r'name="([^"]+)"', m.group(1))
        wf_name = name_m.group(1) if name_m else m.group(1).strip()
        body = m.group(2)
        raw_steps = re.findall(
            r"step-\d+:\s*run cmd=(" + _BLOCK + r");", body, re.DOTALL
        )
        steps = []
        for s in raw_steps:
            first_line = next(
                (line.strip() for line in s.splitlines() if line.strip()), s.strip()
            )
            steps.append(first_line)
        trigger_m = re.search(r'trigger:\s*"?([^"\s;]+)"?;', body)
        workflows_map[wf_name] = {
            "name": wf_name,
            "trigger": trigger_m.group(1) if trigger_m else "manual",
            "steps": steps,
        }
    return list(workflows_map.values())


def _parse_doql_content(content: str) -> dict[str, Any]:
    """Parse DOQL content from .less or .css file into structured data."""
    app_block = re.search(r"app\s*\{([^}]+)\}", content, re.DOTALL)
    app_meta: dict[str, str] = {}
    if app_block:
        for line in app_block.group(1).splitlines():
            m = re.match(r"\s*(\w+):\s*(.+?);", line)
            if m:
                app_meta[m.group(1)] = m.group(2).strip()

    integrations: list[dict[str, Any]] = []
    for m in re.finditer(r"integration\[([^\]]+)\]\s*\{([^}]+)\}", content, re.DOTALL):
        attrs = dict(re.findall(r"(\w[\w-]*):\s*([^;]+);", m.group(2)))
        integrations.append({"selector": m.group(1).strip(), **attrs})

    interfaces = _parse_doql_interfaces(content)
    # deduplicate by selector
    iface_map: dict[str, dict[str, Any]] = {i["selector"]: i for i in interfaces}

    return {
        "app": app_meta,
        "entities": _parse_doql_entities(content),
        "interfaces": list(iface_map.values()),
        "integrations": integrations,
        "workflows": _parse_doql_workflows(content),
    }


def extract_doql(proj_dir: Path) -> dict[str, Any]:
    """Read app.doql.less (preferred) or app.doql.css as fallback."""
    for fname in ("app.doql.less", "app.doql.css"):
        p = proj_dir / fname
        if p.exists():
            result = _parse_doql_content(p.read_text(encoding="utf-8"))
            result["sources"] = [fname]
            return result
    return {}


def extract_pyqual(proj_dir: Path) -> dict[str, Any]:
    pyqual_path = proj_dir / "pyqual.yaml"
    if not pyqual_path.exists():
        return {}
    try:
        data = yaml.safe_load(pyqual_path.read_text(encoding="utf-8"))
        pipeline = data.get("pipeline", data)
        metrics = pipeline.get("metrics", {})
        stages = [
            {
                "name": s["name"],
                "tool": s.get("tool", s.get("run", "")),
                "optional": s.get("optional", False),
            }
            for s in pipeline.get("stages", [])
            if isinstance(s, dict)
        ]
        return {
            "name": pipeline.get("name", ""),
            "metrics": metrics,
            "stages": stages,
            "loop": pipeline.get("loop", {}),
        }
    except Exception:
        return {}


def extract_python_modules(proj_dir: Path, pkg_name: str) -> list[str]:
    pkg_dir = proj_dir / pkg_name
    if not pkg_dir.exists():
        return []
    return [p.stem for p in sorted(pkg_dir.glob("*.py")) if not p.stem.startswith("__")]


def extract_readme_title(proj_dir: Path) -> str:
    readme = proj_dir / "README.md"
    if not readme.exists():
        return ""
    for line in readme.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def extract_requirements(proj_dir: Path) -> list[dict[str, str]]:
    """Parse requirements*.txt files — return list of {file, deps[]}."""
    results = []
    for f in sorted(proj_dir.glob("requirements*.txt")):
        deps = []
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                deps.append(line)
        if deps:
            results.append({"file": f.name, "deps": deps})
    return results


def extract_makefile(proj_dir: Path) -> list[dict[str, str]]:
    """Parse Makefile — return list of {target, comment}."""
    makefile = proj_dir / "Makefile"
    if not makefile.exists():
        return []
    targets = []
    pending_comment = ""
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if line.startswith("##") or line.startswith("# "):
            pending_comment = line.lstrip("#").strip()
        elif re.match(r"^[a-zA-Z0-9_-]+\s*:", line) and not line.startswith("\t"):
            target = re.match(r"^([a-zA-Z0-9_-]+)\s*:", line).group(1)
            targets.append({"target": target, "desc": pending_comment})
            pending_comment = ""
        else:
            pending_comment = ""
    return targets


def extract_goal(proj_dir: Path) -> dict[str, Any]:
    """Parse goal.yaml — versioning strategy, git conventions, build strategies."""
    goal_path = proj_dir / "goal.yaml"
    if not goal_path.exists():
        return {}
    try:
        data = yaml.safe_load(goal_path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        versioning = data.get("versioning", {})
        git = data.get("git", {})
        strategies = data.get("strategies", {})
        quality = data.get("quality", {})
        return {
            "name": project.get("name", ""),
            "type": project.get("type", []),
            "description": project.get("description", ""),
            "versioning_strategy": versioning.get("strategy", ""),
            "version_files": versioning.get("files", []),
            "commit_strategy": git.get("commit", {}).get("strategy", ""),
            "commit_scope": git.get("commit", {}).get("scope", ""),
            "changelog_template": git.get("changelog", {}).get("template", ""),
            "strategies": list(strategies.keys()),
            "quality_gates": list(quality.get("gates", {}).items()),
        }
    except Exception:
        return {}


def _parse_env_line(line_stripped: str, pending_comment: str, vars_: list[dict[str, str]]) -> str:
    """Parse a single line from an env file and return the new pending_comment."""
    if line_stripped.startswith("#"):
        return line_stripped.lstrip("#").strip()
    if "=" in line_stripped:
        key, _, rest = line_stripped.partition("=")
        if "  #" in rest:
            val_part, inline_comment = rest.split("  #", 1)
            comment = inline_comment.strip() or pending_comment
        else:
            val_part = rest
            comment = pending_comment
        val = val_part.strip()
        vars_.append(
            {
                "key": key.strip(),
                "default": val if val else "*(not set)*",
                "comment": comment,
            }
        )
        return ""
    return ""


def extract_env(proj_dir: Path) -> list[dict[str, str]]:
    """Parse .env.example — return list of {key, default, comment}."""
    for fname in (".env.example", ".env.sample", ".env.template"):
        env_path = proj_dir / fname
        if env_path.exists():
            break
    else:
        return []
    vars_: list[dict[str, str]] = []
    pending_comment = ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        pending_comment = _parse_env_line(line.strip(), pending_comment, vars_)
    return vars_


def _parse_dockerfile_labels(line: str, parsed: dict) -> None:
    """Parse labels from Dockerfile line."""
    for kv in re.findall(r'(\w[\w.-]*)=("(?:[^"\\]|\\.)*"|\S+)', line):
        parsed["labels"][kv[0]] = kv[1].strip('"')


def _parse_dockerfile_line(line: str, parsed: dict) -> None:
    """Update *parsed* dict in-place with one Dockerfile instruction."""
    upper = line.upper()
    if upper.startswith("FROM "):
        if not parsed["from"]:
            parsed["from"] = line[5:].strip()
    elif upper.startswith("EXPOSE "):
        parsed["ports"].extend(line[7:].strip().split())
    elif upper.startswith("ENTRYPOINT "):
        parsed["entrypoint"] = line[11:].strip()
    elif upper.startswith("CMD "):
        parsed["cmd"] = line[4:].strip()
    elif upper.startswith("LABEL "):
        _parse_dockerfile_labels(line[6:], parsed)


def extract_dockerfile(proj_dir: Path) -> dict[str, Any]:
    """Parse Dockerfile — base image, exposed ports, entrypoint, labels."""
    for candidate in (proj_dir / "Dockerfile", proj_dir / "docker" / "Dockerfile"):
        if candidate.exists():
            dockerfile_path = candidate
            break
    else:
        return {}
    content = dockerfile_path.read_text(encoding="utf-8")
    parsed: dict = {"from": "", "ports": [], "entrypoint": "", "cmd": "", "labels": {}}
    for line in content.splitlines():
        _parse_dockerfile_line(line.strip(), parsed)
    return {
        "from": parsed["from"],
        "ports": parsed["ports"],
        "entrypoint": parsed["entrypoint"] or parsed["cmd"],
        "labels": parsed["labels"],
    }


def _parse_docker_compose_service(svc_name: str, svc: Any, services: list) -> None:
    """Parse a single service block from docker-compose."""
    if not isinstance(svc, dict):
        return
    ports = [str(p).strip() for p in svc.get("ports", [])]
    env_vars = (
        list(svc.get("environment", {}).keys())
        if isinstance(svc.get("environment"), dict)
        else []
    )
    services.append(
        {
            "name": svc_name,
            "image": svc.get("image", svc.get("build", "")),
            "ports": ports,
            "env_vars": env_vars,
        }
    )


def extract_docker_compose(proj_dir: Path) -> dict[str, Any]:
    """Parse docker-compose*.yml — services with images, ports, environment."""
    candidates = sorted(
        list(proj_dir.glob("docker-compose*.yml"))
        + list((proj_dir / "docker").glob("docker-compose*.yml"))
    )
    if not candidates:
        return {}
    # prefer docker-compose.yml or docker-compose.dev.yml
    path = candidates[0]
    for c in candidates:
        if c.name in ("docker-compose.yml", "docker-compose.yaml"):
            path = c
            break
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        services_raw = data.get("services", {}) or {}
        services = []
        for svc_name, svc in services_raw.items():
            _parse_docker_compose_service(svc_name, svc, services)
        return {"file": path.name, "services": services}
    except Exception:
        return {}


def extract_package_json(proj_dir: Path) -> dict[str, Any]:
    """Parse package.json — name, version, scripts, dependencies."""
    pkg = proj_dir / "package.json"
    if not pkg.exists():
        return {}
    try:
        import json

        data = json.loads(pkg.read_text(encoding="utf-8"))
        return {
            "name": data.get("name", ""),
            "version": data.get("version", ""),
            "description": data.get("description", ""),
            "main": data.get("main", ""),
            "scripts": data.get("scripts", {}),
            "dependencies": list(data.get("dependencies", {}).keys()),
            "dev_dependencies": list(data.get("devDependencies", {}).keys()),
            "engines": data.get("engines", {}),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Code / module analysis
# ---------------------------------------------------------------------------

_LANG_EXT: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sh": "shell",
    ".bash": "shell",
    ".css": "css",
    ".less": "less",
    ".php": "php",
    ".html": "html",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".rs": "rust",
    ".go": "go",
}

_IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "site-packages",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    ".tox",
    "dist",
    "build",
    "target",
    "state",
    ".subactor",
    ".codex",
    ".worktrees",
    "artifacts",
    ".cargo",
    ".planfile",
    "twinerd-bench-results",
    "benchmarks",
    "bench-results",
    "panel-data",
    "runtimes",
    "validation",
    "*.egg-info",
    ".sumd-tools",
    "project",
    "testql-scenarios",
}

# Files to include in M[] (source code only, not docs/config/data)
_SOURCE_LANGS = {
    "python",
    "javascript",
    "typescript",
    "shell",
    "css",
    "less",
    "php",
    "rust",
    "go",
}

_CC_THRESHOLD = 10  # critical CC minimum


def _lang_of(path: Path) -> str:
    return _LANG_EXT.get(path.suffix.lower(), "other")


def _fan_out(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count unique called names inside a function body."""
    calls: set[str] = set()
    for n in ast.walk(func_node):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                calls.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                calls.add(n.func.attr)
    return len(calls)


def _cc_estimate(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Rough cyclomatic-complexity estimate: 1 + decision points."""
    decision = {
        ast.If,
        ast.For,
        ast.While,
        ast.ExceptHandler,
        ast.With,
        ast.AsyncFor,
        ast.AsyncWith,
        ast.Match,
    }
    cc = 1
    for n in ast.walk(func_node):
        if type(n) in decision:
            cc += 1
        elif isinstance(n, ast.BoolOp):
            cc += len(n.values) - 1
    return cc


def _try_radon_cc(src: str) -> dict[str, int]:
    """Return {func_name: cc} using radon if available, else empty."""
    try:
        from radon.complexity import cc_visit  # type: ignore

        return {r.name: r.complexity for r in cc_visit(src)}
    except Exception:
        return {}


def _analyse_py_top_funcs(
    tree: ast.AST, radon_cc: dict[str, int]
) -> tuple[list[str], list[dict]]:
    """Extract top-level function info. Returns (exports, funcs)."""
    exports: list[str] = []
    funcs: list[dict] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            exports.append(name)
            args = [a.arg for a in node.args.args]
            cc = radon_cc.get(name) or _cc_estimate(node)
            fo = _fan_out(node)
            funcs.append({"name": name, "args": args, "cc": cc, "fan": fo})
    return exports, funcs


def _analyse_class_methods(node: ast.ClassDef, radon_cc: dict) -> list[dict]:
    """Extract method signatures and metrics from a class node."""
    methods: list[dict] = []
    for item in ast.iter_child_nodes(node):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            margs = [a.arg for a in item.args.args if a.arg != "self"]
            cc = radon_cc.get(item.name) or _cc_estimate(item)
            fo = _fan_out(item)
            methods.append({"name": item.name, "args": margs, "cc": cc, "fan": fo})
    return methods


def _analyse_py_top_classes(
    tree: ast.AST, radon_cc: dict[str, int]
) -> tuple[list[str], list[dict]]:
    """Extract top-level class info. Returns (exports, classes)."""
    exports: list[str] = []
    classes: list[dict] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        exports.append(node.name)
        methods = _analyse_class_methods(node, radon_cc)
        doc = (ast.get_docstring(node) or "").strip()
        docline = ("  # " + doc.splitlines()[0][:60]) if doc else ""
        classes.append({"name": node.name, "methods": methods, "doc": docline})
    return exports, classes


def _analyse_py_module(path: Path) -> dict[str, Any]:
    """Extract exports, function signatures, class info from a Python file."""
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return {"exports": [], "funcs": [], "classes": [], "cc_map": {}}
    radon_cc = _try_radon_cc(src)
    func_exports, funcs = _analyse_py_top_funcs(tree, radon_cc)
    class_exports, classes = _analyse_py_top_classes(tree, radon_cc)
    return {
        "exports": func_exports + class_exports,
        "funcs": funcs,
        "classes": classes,
        "cc_map": radon_cc,
    }


def _parse_ignore_file(ignore_path: Path) -> list[str]:
    """Parse .gitignore or .sumdignore file and return list of patterns."""
    if not ignore_path.exists():
        return []
    
    patterns = []
    try:
        content = ignore_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            # Remove trailing spaces
            patterns.append(line.rstrip())
    except Exception:
        # If we can't read the file, return empty patterns
        pass
    
    return patterns


def _match_dir_pattern(path: Path, path_str: str, dir_pattern: str) -> bool:
    """Check if path matches a directory pattern (ends with /)."""
    globs = (dir_pattern, dir_pattern + "/*", "*/" + dir_pattern, "*/" + dir_pattern + "/*")
    if any(fnmatch.fnmatch(path_str, g) for g in globs):
        return True
    return any(fnmatch.fnmatch(part, dir_pattern) for part in path.parts)


def _match_absolute_pattern(path_str: str, pattern: str) -> bool:
    """Check if path matches an absolute pattern (starts with /)."""
    pattern = pattern[1:]
    return fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path_str, pattern + "/*")


def _match_recursive_pattern(path_str: str, pattern: str) -> bool:
    """Check if path matches a recursive pattern (starts with **/)."""
    pattern = pattern[3:]
    return (
        fnmatch.fnmatch(path_str, pattern)
        or fnmatch.fnmatch(path_str, "*/" + pattern)
        or fnmatch.fnmatch(path_str, "**/" + pattern)
    )


def _match_regular_pattern(path: Path, path_str: str, pattern: str) -> bool:
    """Check if path matches a regular pattern."""
    if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path_str, "*/" + pattern):
        return True
    for part in path.parts:
        if fnmatch.fnmatch(part, pattern):
            return True
    return False


def _path_matches_pattern(path: Path, pattern: str) -> bool:
    """Check if a path matches a gitignore-style pattern."""
    path_str = str(path)

    # Handle negation patterns (starting with !)
    if pattern.startswith("!"):
        # This is a negation - we handle it at the caller level
        return False

    # Handle directory patterns (ending with /)
    if pattern.endswith("/"):
        return _match_dir_pattern(path, path_str, pattern[:-1])

    # Handle absolute patterns (starting with /)
    if pattern.startswith("/"):
        return _match_absolute_pattern(path_str, pattern)

    # Handle recursive patterns (starting with **/)
    if pattern.startswith("**/"):
        return _match_recursive_pattern(path_str, pattern)

    # Regular pattern
    return _match_regular_pattern(path, path_str, pattern)


def _is_path_ignored(path: Path, proj_dir: Path, ignore_patterns: list[str]) -> bool:
    """Check if a path should be ignored based on gitignore-style patterns."""
    if not ignore_patterns:
        return False
    
    # Convert to relative path for matching
    try:
        rel_path = path.relative_to(proj_dir)
    except ValueError:
        # If path is not relative to proj_dir, treat it as not ignored
        return False
    
    # First check for negation patterns, then for regular patterns
    is_ignored = False
    
    for pattern in ignore_patterns:
        if pattern.startswith("!"):
            # Negation pattern - unignore if it matches
            if _path_matches_pattern(rel_path, pattern[1:]):
                is_ignored = False
        else:
            # Regular ignore pattern
            if _path_matches_pattern(rel_path, pattern):
                is_ignored = True
    
    return is_ignored


def _is_map_ignored_path(p: Path) -> bool:
    """Return True if *p* (relative) contains an ignored directory segment."""
    for part in p.parts:
        if part in _IGNORE_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _should_include_map_file(f: Path, proj_dir: Path, all_ignore_patterns: list[str]) -> str | None:
    """Return language string if file should be included, else None."""
    try:
        rel_path = f.relative_to(proj_dir)
    except ValueError:
        return None
    if _is_map_ignored_path(rel_path):
        return None
    if _is_path_ignored(f, proj_dir, all_ignore_patterns):
        return None
    lang = _lang_of(f)
    if lang == "other" or lang not in _SOURCE_LANGS:
        return None
    return lang


def _collect_map_files(
    proj_dir: Path,
) -> tuple[dict[str, int], list[tuple[Path, int, str]]]:
    """Collect source files for map generation. Returns (lang_counts, modules)."""
    lang_counts: dict[str, int] = {}
    modules: list[tuple[Path, int, str]] = []  # (path, lines, lang)

    # Load ignore patterns from .gitignore and .sumdignore
    gitignore_patterns = _parse_ignore_file(proj_dir / ".gitignore")
    sumdignore_patterns = _parse_ignore_file(proj_dir / ".sumdignore")
    all_ignore_patterns = gitignore_patterns + sumdignore_patterns

    # Prune ignored directories before descending instead of walking the
    # full tree (including venv/node_modules) and filtering afterward.
    all_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(proj_dir, topdown=True):
        current_dir = Path(dirpath)
        kept = []
        for d in dirnames:
            dir_path = current_dir / d
            rel_dir = dir_path.relative_to(proj_dir)
            if _is_map_ignored_path(rel_dir) or _is_path_ignored(dir_path, proj_dir, all_ignore_patterns):
                continue
            kept.append(d)
        dirnames[:] = kept
        for filename in filenames:
            all_files.append(current_dir / filename)

    for f in sorted(all_files):
        lang = _should_include_map_file(f, proj_dir, all_ignore_patterns)
        if not lang:
            continue

        try:
            lines = f.read_text(encoding="utf-8", errors="replace").count("\n") + 1
        except Exception:
            continue
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        modules.append((f.relative_to(proj_dir), lines, lang))

    return lang_counts, modules


def _render_map_detail(
    proj_dir: Path, modules: list[tuple[Path, int, str]]
) -> tuple[list[tuple[Path, dict]], list[dict], list[dict], int]:
    """Analyse Python modules for map detail section. Returns (py_modules, all_funcs, all_classes, total_cls)."""
    py_modules: list[tuple[Path, dict]] = []
    all_funcs: list[dict] = []
    all_classes: list[dict] = []
    total_cls = 0

    for rel, lines, lang in modules:
        if lang != "python":
            continue
        info = _analyse_py_module(proj_dir / rel)
        py_modules.append((rel, info))
        for f in info["funcs"]:
            all_funcs.append({**f, "mod": str(rel)})
        for c in info["classes"]:
            all_classes.append({**c, "mod": str(rel)})
            total_cls += 1

    return py_modules, all_funcs, all_classes, total_cls


def _map_cc_stats(
    all_funcs: list[dict],
) -> tuple[float, int, str, str]:
    """Compute CC stats for map header. Returns (avg_cc, critical, alerts_str, hotspots_str)."""
    cc_vals = [f["cc"] for f in all_funcs] or [1]
    avg_cc = round(sum(cc_vals) / len(cc_vals), 1)
    critical = sum(1 for c in cc_vals if c >= _CC_THRESHOLD)
    by_cc = sorted(all_funcs, key=lambda x: -x["cc"])[:5]
    by_fan = sorted(all_funcs, key=lambda x: -x["fan"])[:5]
    cc_items = [f"CC {f['name']}={f['cc']}" for f in by_cc]
    fan_items = [f"fan-out {f['name']}={f['fan']}" for f in by_fan]
    alert_items = list(dict.fromkeys(cc_items + fan_items))[:5]
    hotspot_items = [f"{f['name']} fan={f['fan']}" for f in by_fan[:5]]
    alerts = "; ".join(alert_items) if alert_items else "none"
    hotspots = "; ".join(hotspot_items) if hotspot_items else "none"
    return avg_cc, critical, alerts, hotspots


def _render_py_module_detail(rel: Path, info: dict, a) -> None:
    """Append detail lines for one Python module in map.toon format."""
    a(f"  {rel}:")
    if info["exports"]:
        a(f"    e: {','.join(info['exports'])}")
    for cls in info["classes"]:
        method_summary = ",".join(
            f"{m['name']}({len(m['args'])})" for m in cls["methods"]
        )
        doc = cls["doc"]
        if method_summary:
            a(f"    {cls['name']}: {method_summary}{doc}")
        else:
            a(f"    {cls['name']}:{doc}")
    for f in info["funcs"]:
        sig = ";".join(f["args"]) if f["args"] else ""
        a(f"    {f['name']}({sig})")


def generate_map_toon(proj_dir: Path) -> str:
    """Generate project/map.toon.yaml content for proj_dir."""
    proj_dir = proj_dir.resolve()
    proj_name = proj_dir.name
    today = date.today().isoformat()

    lang_counts, modules = _collect_map_files(proj_dir)
    total_files = len(modules)
    total_lines = sum(lines for _, lines, _ in modules)

    py_modules, all_funcs, all_classes, total_cls = _render_map_detail(
        proj_dir, modules
    )

    total_func = len(all_funcs)
    total_mod = len(modules)

    avg_cc, critical, alerts, hotspots = _map_cc_stats(all_funcs)

    # ── Render ─────────────────────────────────────────────────────────────
    L: list[str] = []
    a = L.append

    lang_str = ",".join(
        f"{lang}:{cnt}"
        for lang, cnt in sorted(lang_counts.items(), key=lambda x: -x[1])
    )

    a(f"# {proj_name} | {total_files}f {total_lines}L | {lang_str} | {today}")
    a(
        f"# stats: {total_func} func | {total_cls} cls | {total_mod} mod"
        f" | CC̄={avg_cc} | critical:{critical} | cycles:0"
    )
    a(f"# alerts[5]: {alerts}")
    a(f"# hotspots[5]: {hotspots}")
    a("# evolution: baseline")
    a(
        "# Keys: M=modules, D=details, i=imports, e=exports, c=classes, f=functions, m=methods"
    )

    a(f"M[{total_mod}]:")
    for rel, lines, _lang in modules:
        a(f"  {rel},{lines}")

    a("D:")
    for rel, info in py_modules:
        _render_py_module_detail(rel, info, a)

    return "\n".join(L) + "\n"


def _facts_project_metadata(proj_dir: Path) -> list[str]:
    """Generate project metadata facts."""
    proj_name = proj_dir.name
    version = "0.0.0"
    project_type = "python"
    try:
        pyproj = extract_pyproject(proj_dir)
        version = pyproj.get("version", "0.0.0")
        if not pyproj:
            pkg_json = extract_package_json(proj_dir)
            if pkg_json:
                version = pkg_json.get("version", "0.0.0")
                project_type = "javascript"
    except Exception:
        pass
    return [
        "% ── Project Metadata ─────────────────────────────────────",
        f"project_metadata('{proj_name}', '{version}', '{project_type}').\n",
    ]


def _facts_project_files(proj_dir: Path) -> list[str]:
    """Generate project file facts."""
    facts = ["% ── Project Files ────────────────────────────────────────"]
    _lang_counts, modules = _collect_map_files(proj_dir)
    for rel_path, lines, lang in modules:
        rel_clean = str(rel_path).replace("'", "\\'")
        facts.append(f"project_file('{rel_clean}', {lines}, '{lang}').")
    facts.append("")
    return facts


def _facts_python_analysis(proj_dir: Path) -> list[str]:
    """Generate Python function and class facts."""
    _lang_counts, modules = _collect_map_files(proj_dir)
    _py_modules, all_funcs, all_classes, _total_cls = _render_map_detail(proj_dir, modules)
    facts = ["% ── Python Functions ─────────────────────────────────────"]
    for f in all_funcs:
        mod_clean = f["mod"].replace("'", "\\'")
        func_clean = f["name"].replace("'", "\\'")
        arity = len(f["args"])
        cc = f["cc"]
        fan = f["fan"]
        facts.append(f"python_function('{mod_clean}', '{func_clean}', {arity}, {cc}, {fan}).")
    facts.append("")

    facts.append("% ── Python Classes ───────────────────────────────────────")
    for cls in all_classes:
        mod_clean = cls["mod"].replace("'", "\\'")
        cls_clean = cls["name"].replace("'", "\\'")
        facts.append(f"python_class('{mod_clean}', '{cls_clean}').")
        for m in cls["methods"]:
            m_clean = m["name"].replace("'", "\\'")
            arity = len(m["args"])
            cc = m["cc"]
            fan = m["fan"]
            facts.append(f"python_method('{cls_clean}', '{m_clean}', {arity}, {cc}, {fan}).")
    facts.append("")
    return facts


def _facts_dependencies(proj_dir: Path) -> list[str]:
    """Generate dependency facts."""
    facts = ["% ── Dependencies ─────────────────────────────────────────"]
    try:
        reqs = extract_requirements(proj_dir)
        for req in reqs:
            src_file = req["file"].replace("'", "\\'")
            for dep in req["deps"]:
                dep_clean = dep.replace("'", "\\'")
                facts.append(f"project_dependency('{dep_clean}', '{src_file}').")
    except Exception:
        pass
    facts.append("")
    return facts


def _facts_makefile(proj_dir: Path) -> list[str]:
    """Generate Makefile target facts."""
    facts = ["% ── Makefile Targets ─────────────────────────────────────"]
    try:
        makefile = extract_makefile(proj_dir)
        for target in makefile:
            tgt_clean = target["target"].replace("'", "\\'")
            desc_clean = target["desc"].replace("'", "\\'").replace("\n", " ")
            facts.append(f"makefile_target('{tgt_clean}', '{desc_clean}').")
    except Exception:
        pass
    facts.append("")
    return facts


def _facts_taskfile(proj_dir: Path) -> list[str]:
    """Generate Taskfile task facts."""
    facts = ["% ── Taskfile Tasks ───────────────────────────────────────"]
    try:
        tasks = extract_taskfile(proj_dir)
        for task in tasks:
            name_clean = task.get("task", "").replace("'", "\\'")
            desc_clean = task.get("desc", "").replace("'", "\\'").replace("\n", " ")
            facts.append(f"taskfile_task('{name_clean}', '{desc_clean}').")
    except Exception:
        pass
    facts.append("")
    return facts


def _facts_env_variables(proj_dir: Path) -> list[str]:
    """Generate environment variable facts."""
    facts = ["% ── Environment Variables ────────────────────────────────"]
    try:
        env_vars = extract_env(proj_dir)
        for ev in env_vars:
            k_clean = ev["key"].replace("'", "\\'")
            d_clean = ev["default"].replace("'", "\\'")
            c_clean = ev["comment"].replace("'", "\\'").replace("\n", " ")
            facts.append(f"env_variable('{k_clean}', '{d_clean}', '{c_clean}').")
    except Exception:
        pass
    facts.append("")
    return facts


def _facts_testql_scenarios(proj_dir: Path) -> list[str]:
    """Generate TestQL scenario facts."""
    facts = ["% ── TestQL Scenarios ─────────────────────────────────────"]
    try:
        from sumd.toon_parser import extract_testql_scenarios
        scenarios = extract_testql_scenarios(proj_dir)
        for sc in scenarios:
            file_clean = sc.get("file", "").replace("'", "\\'")
            type_clean = sc.get("type", "generic").replace("'", "\\'")
            facts.append(f"testql_scenario('{file_clean}', '{type_clean}').")
    except Exception:
        pass
    facts.append("")
    return facts


def generate_project_logic(proj_dir: Path) -> str:
    """Generate project/logic.pl containing Prolog facts representing the project structure."""
    proj_dir = proj_dir.resolve()
    facts: list[str] = []
    facts.extend(_facts_project_metadata(proj_dir))
    facts.extend(_facts_project_files(proj_dir))
    facts.extend(_facts_python_analysis(proj_dir))
    facts.extend(_facts_dependencies(proj_dir))
    facts.extend(_facts_makefile(proj_dir))
    facts.extend(_facts_taskfile(proj_dir))
    facts.extend(_facts_env_variables(proj_dir))
    facts.extend(_facts_testql_scenarios(proj_dir))

    facts.append("% ── Semantic Facts from SUMD.md ──────────────────────────")
    try:
        facts.extend(_extract_sumd_semantic_facts(proj_dir))
    except Exception:
        pass
    facts.append("")

    return "\n".join(facts) + "\n"


def _extract_markpact_files(content: str) -> list[str]:
    """Extract declared files from markpact codeblocks in SUMD.md."""
    facts = []
    pattern = r"^```(?P<lang>\w+)[ \t]+markpact:(?P<kind>\w+)(?:[ \t]+(?P<attrs>[^\n]*))?$"
    for m in re.finditer(pattern, content, re.MULTILINE):
        kind = m.group("kind")
        attrs = m.group("attrs") or ""
        pm = re.search(r"path=([^\s]+)", attrs)
        if pm:
            path_val = pm.group(1).strip("'\"")
            facts.append(f"sumd_declared_file('{path_val}', '{kind}').")
    return facts


def _extract_doql_interfaces(doql_content: str) -> list[str]:
    """Extract interface facts from app.doql.less content."""
    facts = []
    for m in re.finditer(
        r'interface\[type="(?P<type>[^"]+)"\](?:\s*\{\s*framework:\s*(?P<fw>[^;]+);)?',
        doql_content,
    ):
        itype = m.group("type").replace("'", "\\'")
        if m.group("fw"):
            ifw = m.group("fw").strip().replace("'", "\\'")
            facts.append(f"sumd_interface('{itype}', '{ifw}').")
        else:
            facts.append(f"sumd_interface('{itype}', '').")
    return facts


def _extract_doql_workflows(doql_content: str) -> list[str]:
    """Extract workflow facts from app.doql.less content."""
    facts = []
    workflow_blocks = re.finditer(
        r'workflow\[name="(?P<name>[^"]+)"\]\s*\{(?P<body>[\s\S]*?)\}',
        doql_content,
    )
    for wb in workflow_blocks:
        w_name = wb.group("name").replace("'", "\\'")
        body = wb.group("body")
        trig_m = re.search(r"trigger:\s*([^;]+);", body)
        w_trig = trig_m.group(1).strip().replace("'", "\\'") if trig_m else ""
        facts.append(f"sumd_workflow('{w_name}', '{w_trig}').")

        if w_name.startswith("quality:"):
            gate_name = w_name.split(":", 1)[1]
            facts.append(f"sumd_quality_workflow('{w_name}', '{gate_name}').")

        steps = re.finditer(r"step-(?P<idx>\d+):\s*run\s+cmd=(?P<cmd>[^;\n]+);", body)
        for st in steps:
            s_idx = st.group("idx")
            s_cmd = st.group("cmd").strip().replace("'", "\\'")
            facts.append(f"sumd_workflow_step('{w_name}', {s_idx}, '{s_cmd}').")
    return facts


def _extract_doql_facts(proj_dir: Path) -> list[str]:
    """Extract facts from app.doql.less if it exists."""
    facts = []
    doql_path = proj_dir / "app.doql.less"
    if not doql_path.exists():
        return facts
    doql_content = doql_path.read_text(encoding="utf-8")
    facts.extend(_extract_doql_interfaces(doql_content))
    facts.extend(_extract_doql_workflows(doql_content))
    return facts


def _extract_deploy_facts(proj_dir: Path) -> list[str]:
    """Extract deployment target facts."""
    facts = []
    compose_path = proj_dir / "docker-compose.yml"
    if compose_path.exists():
        facts.append("sumd_deploy_target('docker_compose').")
        facts.append("sumd_deploy_compose_file('docker-compose.yml').")
    return facts


def _extract_pyqual_gates(proj_dir: Path) -> list[str]:
    """Extract pyqual gate facts."""
    facts = []
    pyqual_path = proj_dir / "pyqual.yaml"
    if not pyqual_path.exists():
        return facts
    pyqual_content = pyqual_path.read_text(encoding="utf-8")
    for m in re.finditer(r"gate:\s*([^\s\n]+)", pyqual_content):
        g_name = m.group(1).strip().replace("'", "\\'")
        facts.append(f"sumd_gate('{g_name}').")
    return facts


def _extract_sumd_semantic_facts(proj_dir: Path) -> list[str]:
    facts = []
    sumd_path = proj_dir / "SUMD.md"
    if not sumd_path.exists():
        return facts

    content = sumd_path.read_text(encoding="utf-8")
    facts.extend(_extract_markpact_files(content))
    facts.extend(_extract_doql_facts(proj_dir))
    facts.extend(_extract_deploy_facts(proj_dir))
    facts.extend(_extract_pyqual_gates(proj_dir))
    return facts


# ---------------------------------------------------------------------------
# Project analysis files
# ---------------------------------------------------------------------------

_PROJECT_ANALYSIS_FILES = [
    ("map.toon.yaml", "toon"),
    ("calls.toon.yaml", "toon"),
    ("logic.pl", "prolog"),
]

# Files loaded only for the 'refactor' profile (pre-refactoring analysis).
# map.toon.yaml is included here too — structural overview is still relevant.
_REFACTOR_ANALYSIS_FILES = [
    ("map.toon.yaml", "toon"),
    ("calls.toon.yaml", "toon"),
    ("analysis.toon.yaml", "toon"),
    ("duplication.toon.yaml", "toon"),
    ("evolution.toon.yaml", "toon"),
    ("validation.toon.yaml", "toon"),
]

# Maps each analysis file to the external tool that generates it.
# map.toon.yaml is excluded — handled by _refresh_map_toon() (pure-Python).
_TOOL_FOR_FILE: dict[str, str] = {
    "calls.toon.yaml":        "code2llm",
    "analysis.toon.yaml":     "code2llm",
    "evolution.toon.yaml":    "code2llm",
    "duplication.toon.yaml":  "redup",
    "validation.toon.yaml":   "vallm",
}


def required_tools_for_profile(profile: str) -> set[str]:
    """Return the set of external tools needed to refresh analysis files for *profile*.

    Used by RenderPipeline._refresh_analysis_files() to run only the tools
    that are actually embedded by the active profile.

    Examples:
        required_tools_for_profile('rich')     → {'code2llm'}
        required_tools_for_profile('refactor') → {'code2llm', 'redup', 'vallm'}
        required_tools_for_profile('minimal')  → set()
    """
    file_list = _REFACTOR_ANALYSIS_FILES if profile == "refactor" else _PROJECT_ANALYSIS_FILES
    return {_TOOL_FOR_FILE[f] for f, _ in file_list if f in _TOOL_FOR_FILE}


def extract_source_snippets(proj_dir: Path, pkg_name: str) -> list[dict]:
    """Return per-module AST summary for source_snippets section.

    Each entry: {module, path, funcs: [{name, args, cc, fan}], classes: [{name, methods, doc}]}
    Sorted by total function+method count descending (highest-density modules first).
    """
    pkg_dir = proj_dir / pkg_name
    if not pkg_dir.is_dir():
        return []
    results: list[dict] = []
    for py_file in sorted(pkg_dir.glob("*.py")):
        if py_file.stem.startswith("__"):
            continue
        analysis = _analyse_py_module(py_file)
        if not analysis["funcs"] and not analysis["classes"]:
            continue
        rel = py_file.relative_to(proj_dir)
        results.append(
            {
                "module": f"{pkg_name}.{py_file.stem}",
                "path": str(rel),
                "funcs": analysis["funcs"],
                "classes": analysis["classes"],
            }
        )

    # Sort by density: total public symbols (functions + all class methods)
    def _density(entry: dict) -> int:
        method_count = sum(len(c["methods"]) for c in entry["classes"])
        return len(entry["funcs"]) + method_count

    results.sort(key=_density, reverse=True)
    return results


def _process_swop_manifest(
    context_dir: Path, context_name: str, manifest_type: str, context_data: dict, sources: list
) -> None:
    """Parse a single SWOP manifest file and add to context_data."""
    manifest_path = context_dir / manifest_type
    if manifest_path.exists():
        rel_path = f".swop/manifests/{context_name}/{manifest_type}"
        try:
            content = manifest_path.read_text(encoding="utf-8").rstrip()
            context_data[manifest_type.replace(".yml", "")] = {
                "file": rel_path,
                "content": content,
            }
            sources.append(rel_path)
        except Exception:
            pass


def extract_swop(proj_dir: Path) -> dict[str, Any]:
    """Extract SWOP manifest files from .swop/manifests/<context>/ directory.

    Returns dict with structure:
    {
        "contexts": {
            "<context_name>": {
                "commands": {file, content},
                "queries": {file, content},
                "events": {file, content}
            }
        },
        "sources": [list of file paths]
    }
    """
    swop_dir = proj_dir / ".swop" / "manifests"
    if not swop_dir.is_dir():
        return {}

    contexts: dict[str, dict[str, Any]] = {}
    sources: list[str] = []

    for context_dir in sorted(swop_dir.iterdir()):
        if not context_dir.is_dir():
            continue

        context_name = context_dir.name
        context_data: dict[str, dict[str, str]] = {}

        for manifest_type in ("commands.yml", "queries.yml", "events.yml"):
            _process_swop_manifest(context_dir, context_name, manifest_type, context_data, sources)

        if context_data:
            contexts[context_name] = context_data

    if not contexts:
        return {}

    return {"contexts": contexts, "sources": sources}


def extract_project_analysis(
    proj_dir: Path, refactor: bool = False
) -> list[dict[str, str]]:
    """Return list of {file, lang, content} for files present in project/ subdir.

    Args:
        refactor: if True, load refactor-profile files (analysis, duplication,
                  evolution, validation) in addition to the standard set.
    """
    project_dir = proj_dir / "project"
    if not project_dir.is_dir():
        return []
    file_list = _REFACTOR_ANALYSIS_FILES if refactor else _PROJECT_ANALYSIS_FILES
    results = []
    seen: set[str] = set()
    for filename, lang in file_list:
        if filename in seen:
            continue
        seen.add(filename)
        fpath = project_dir / filename
        if fpath.exists():
            results.append(
                {
                    "file": f"project/{filename}",
                    "lang": lang,
                    "content": fpath.read_text(encoding="utf-8").rstrip(),
                }
            )
    return results
