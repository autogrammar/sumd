import pytest
from pathlib import Path
from textwrap import dedent
from sumd.prolog_engine import PythonPrologDB, PythonPrologEngine
from sumd.validator import validate_project_architecture, validate_sumd_file


def test_pure_python_prolog_basic():
    """Test the zero-dependency pure-Python Prolog SLD engine on basic facts."""
    db = PythonPrologDB()
    db.parse_and_load(dedent("""
        project_file('src/main.py', 100, 'python').
        project_file('src/utils.py', 50, 'python').
        
        has_large_file(F) :- project_file(F, L, _), L \\= 50.
    """))
    
    engine = PythonPrologEngine(db)
    
    # Query facts
    res = engine.query("project_file(F, 100, 'python')")
    assert len(res) == 1
    assert res[0]["F"] == "src/main.py"
    
    # Query rules with inequality
    res_rule = engine.query("has_large_file(File)")
    assert len(res_rule) == 1
    assert res_rule[0]["File"] == "src/main.py"


def test_architectural_validation_missing_file(tmp_path):
    """Test Layer 3 consistency: declared file is missing from filesystem."""
    proj_dir = tmp_path
    
    # 1. Create a minimal SUMD.md with a markpact block declaring missing.py
    sumd_content = dedent("""\
        # test_project - Minimal Test
        
        ## Metadata
        - **name**: test_project
        - **version**: 1.0.0
        
        ## Architecture
        ```python markpact:file path=missing.py
        print("This file does not exist")
        ```
    """)
    (proj_dir / "SUMD.md").write_text(sumd_content, encoding="utf-8")
    (proj_dir / "Makefile").write_text("", encoding="utf-8")
    
    # Run validation (missing.py does not exist in workspace, so it should report an error)
    errors = validate_project_architecture(proj_dir)
    
    assert len(errors) > 0
    assert any("declared_file_missing" in err and "missing.py" in err for err in errors)


def _declare_file(root, relative):
    (root / "Makefile").write_text("", encoding="utf-8")
    (root / "SUMD.md").write_text(
        f"# fixture\n\n```text markpact:analysis path={relative}\nfixture\n```\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("relative", [
    "project/map.toon.yaml", "project/calls.toon.yaml", "project/logic.pl",
    "testql-scenarios/generated.testql.toon.yaml", "assets/image.bin", "LICENSE",
    "reports/owner's-report.bin",
])
def test_declared_existing_files_need_not_be_in_analysis_inventory(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture\n")
    (tmp_path / ".sumdignore").write_text("project/\ntestql-scenarios/\nassets/\nreports/\nLICENSE\n")
    _declare_file(tmp_path, relative)
    assert validate_project_architecture(tmp_path) == []
    path.unlink()
    assert any("declared_file_missing" in error for error in validate_project_architecture(tmp_path))


def test_declared_missing_file_is_not_exempt_when_its_tree_is_ignored(tmp_path):
    (tmp_path / ".sumdignore").write_text("project/\n")
    _declare_file(tmp_path, "project/missing.bin")
    errors = validate_project_architecture(tmp_path)
    assert any("declared_file_missing(project/missing.bin" in error for error in errors)


def test_cached_source_facts_cannot_hide_current_missing_declarations(tmp_path):
    _declare_file(tmp_path, "new-missing.bin")
    (tmp_path / "project").mkdir()
    (tmp_path / "project/logic.pl").write_text(
        "project_file('new-missing.bin', 1, 'python').\n"
        "sumd_declared_file('old-missing.bin', 'analysis').\n"
    )
    errors = validate_project_architecture(tmp_path)
    assert any("declared_file_missing(new-missing.bin" in error for error in errors)
    assert not any("old-missing.bin" in error for error in errors)


@pytest.mark.parametrize("kind", ["directory", "dangling", "outside"])
def test_declared_non_file_or_external_target_remains_invalid(tmp_path, kind):
    path = tmp_path / "artifact.bin"
    if kind == "directory":
        path.mkdir()
    elif kind == "dangling":
        path.symlink_to("missing.bin")
    else:
        outside = tmp_path.parent / (tmp_path.name + "-outside.bin")
        outside.write_bytes(b"external")
        path.symlink_to(outside)
    _declare_file(tmp_path, "artifact.bin")
    errors = validate_project_architecture(tmp_path)
    assert any("declared_file_missing(artifact.bin" in error for error in errors)


def test_architectural_validation_aligned(tmp_path):
    """Test that an entirely consistent project reports no errors."""
    proj_dir = tmp_path
    
    # 1. Create app.doql.less declaring a workflow and matching task/makefile
    doql_content = dedent("""\
        app {
          name: test;
          version: 1.0.0;
        }
        workflow[name="build"] {
          trigger: manual;
          step-1: run cmd=echo build;
        }
    """)
    (proj_dir / "app.doql.less").write_text(doql_content, encoding="utf-8")
    
    # 2. Create matching SUMD.md
    sumd_content = dedent("""\
        # test - Minimal Aligned Test
        
        ## Metadata
        - **name**: test
        - **version**: 1.0.0
        
        ## Architecture
        ```less markpact:doql path=app.doql.less
        // content
        ```
    """)
    (proj_dir / "SUMD.md").write_text(sumd_content, encoding="utf-8")
    
    # 3. Create Makefile or Taskfile to satisfy "workflow_missing_automation"
    makefile_content = dedent("""\
        build:
        \techo building
    """)
    (proj_dir / "Makefile").write_text(makefile_content, encoding="utf-8")
    
    # Run validation - should be fully consistent!
    errors = validate_project_architecture(proj_dir)
    assert errors == []


def test_architectural_validation_missing_automation(tmp_path):
    """Test Layer 3: workflow exists but Makefile / Taskfile has no matching automation."""
    proj_dir = tmp_path
    
    # Declare a workflow "deploy" but don't provide Makefile target or Taskfile task
    doql_content = dedent("""\
        app { name: test; }
        workflow[name="deploy"] {
          trigger: manual;
          step-1: run cmd=echo deploy;
        }
    """)
    (proj_dir / "app.doql.less").write_text(doql_content, encoding="utf-8")
    
    sumd_content = dedent("""\
        # test - Missing Automation
        
        ## Metadata
        - **name**: test
        - **version**: 1.0.0
        
        ## Architecture
        ```less markpact:doql path=app.doql.less
        ```
    """)
    (proj_dir / "SUMD.md").write_text(sumd_content, encoding="utf-8")
    
    errors = validate_project_architecture(proj_dir)
    assert len(errors) > 0
    assert any("workflow_missing_automation" in err and "deploy" in err for err in errors)


def test_architectural_validation_missing_gate(tmp_path):
    """Test Layer 2: quality workflow exists but no matching pyqual gate is declared."""
    proj_dir = tmp_path
    
    doql_content = dedent("""\
        app { name: test; }
        workflow[name="quality:regix"] {
          trigger: manual;
          step-1: run cmd=echo pyqual;
        }
    """)
    (proj_dir / "app.doql.less").write_text(doql_content, encoding="utf-8")
    
    sumd_content = dedent("""\
        # test - Missing Gate
        
        ## Metadata
        - **name**: test
        - **version**: 1.0.0
        
        ## Architecture
        ```less markpact:doql path=app.doql.less
        ```
    """)
    (proj_dir / "SUMD.md").write_text(sumd_content, encoding="utf-8")
    
    # We also provide a Makefile target so we don't trigger "workflow_missing_automation"
    (proj_dir / "Makefile").write_text("quality:regix:\n\techo running\n", encoding="utf-8")
    
    # Run validation - since pyqual.yaml is missing, the regix gate is missing!
    errors = validate_project_architecture(proj_dir)
    assert len(errors) > 0
    assert any("missing_gate_for_quality_workflow" in err and "regix" in err for err in errors)
