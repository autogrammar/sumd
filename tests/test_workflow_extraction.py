"""Workflow source facts must preserve the automation that is actually present."""
from textwrap import dedent

import pytest

from sumd.extractor import _extract_doql_workflows, _facts_taskfile
from sumd.validator import validate_project_architecture


def test_taskfile_facts_retain_namespaced_task_names(tmp_path):
    (tmp_path / "Taskfile.yml").write_text(
        'version: "3"\ntasks:\n  "workspace:run:*":\n    desc: Run a checkout\n    cmds: ["echo done"]\n'
    )
    assert "taskfile_task('workspace:run:*', 'Run a checkout')." in _facts_taskfile(tmp_path)


@pytest.mark.parametrize("command", [
    "doql workspace list --root {{.PWD}}",
    'printf "%s" "a } brace"; echo "${PROJECT}"',
    "for item in one two; do\n  echo \"${item}\"\ndone",
    'echo "step-2: run cmd=not-a-step;"',
    r'printf "%s" C:\folder',
])
def test_workflow_preserves_complete_command(command):
    content = f'workflow[name="build"] {{\n  trigger: manual;\n  step-1: run cmd={command};\n}}'
    facts = _extract_doql_workflows(content)
    expected = command.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    assert f"sumd_workflow_step('build', 1, '{expected}')." in facts
    assert sum(fact.startswith("sumd_workflow_step(") for fact in facts) == 1


def test_multiple_inline_workflow_steps_remain_separate():
    facts = _extract_doql_workflows(
        'workflow[name="build"] { trigger: manual; step-1: run cmd=echo {{.PWD}}; step-2: run cmd=echo done; }'
    )
    assert "sumd_workflow_step('build', 1, 'echo {{.PWD}}')." in facts
    assert "sumd_workflow_step('build', 2, 'echo done')." in facts


def setup_architecture(root, workflow, *, task=True):
    (root / "app.doql.less").write_text('app { name: example; }\n' + workflow)
    (root / "SUMD.md").write_text("# Example\n")
    if task:
        (root / "Taskfile.yml").write_text('version: "3"\ntasks:\n  build:\n    cmds: ["echo {{.PWD}}"]\n')


def test_real_task_with_template_multiline_steps_validates(tmp_path):
    setup_architecture(tmp_path, dedent('''\
        workflow[name="build"] {
          trigger: manual;
          step-1: run cmd=for item in one two; do
          echo "${item}" {{.PWD}}
        done;
        }
    '''))
    assert validate_project_architecture(tmp_path) == []


def test_absent_automation_is_still_invalid(tmp_path):
    setup_architecture(tmp_path, 'workflow[name="build"] { trigger: manual; step-1: run cmd=echo {{.PWD}}; }', task=False)
    errors = validate_project_architecture(tmp_path)
    assert any("workflow_missing_automation(build)" in error for error in errors)


def test_quoted_command_punctuation_survives_native_architecture_loading(tmp_path):
    setup_architecture(tmp_path, '''workflow[name="build"] {
      trigger: manual;
      step-1: run cmd=doql adopt . --output app.doql.css;
      step-2: run cmd=printf '%s' done;
    }''')
    assert validate_project_architecture(tmp_path) == []


def test_absent_step_is_still_invalid_even_with_matching_task(tmp_path):
    setup_architecture(tmp_path, 'workflow[name="build"] { trigger: manual; }')
    errors = validate_project_architecture(tmp_path)
    assert any("workflow_missing_steps(build)" in error for error in errors)
