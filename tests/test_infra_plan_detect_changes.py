"""The infra-plan detect-changes step may only emit stack dirs that EXIST at the head.

A PR that DELETES a stack (opshub#464 removed infra/live/prod) lists the dir in the
diff; planning the ghost died with "No such file or directory" then ENOENT plan.txt.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest

WF = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/infra-plan.yml"


def step_script() -> str:
    """Extract the detect-changes `run:` block from the workflow, ready to execute."""
    action = WF.read_text()
    i = action.find("  detect-changes:")
    i = action.find("      run: |", i)
    block = []
    for line in action[i:].splitlines()[1:]:
        if line.startswith("        ") or line.strip() == "":
            block.append(line[8:])
        else:
            break
    return "\n".join(block)


def git(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A repo with two live stacks on `main`, and a PR branch that deletes one."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    for stack in ("dev", "prod"):
        d = r / "infra" / "live" / stack
        d.mkdir(parents=True)
        (d / "main.tf").write_text("# stack\n")
    (r / "infra" / "modules").mkdir(parents=True)
    (r / "infra" / "modules" / "stack.tf").write_text("# module\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    # the PR: delete infra/live/prod, touch infra/live/dev
    shutil.rmtree(r / "infra" / "live" / "prod")
    (r / "infra" / "live" / "dev" / "main.tf").write_text("# changed\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "delete prod, touch dev")
    git(r, "update-ref", "refs/remotes/origin/main", "HEAD~1")
    return r


def run_detect(repo: pathlib.Path, module_prefix: str = "", prefix: str = "infra/live/"):
    out = repo / "out.txt"
    env = {
        "PREFIX": prefix,
        "MODULE_PREFIX": module_prefix,
        "BASE_REF": "main",
        "GITHUB_OUTPUT": str(out),
    }
    proc = subprocess.run(
        ["bash", "-c", step_script()],
        cwd=repo,
        env={**{k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"},
             "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo), **env},
        capture_output=True,
        text=True,
    )
    return proc, out


def test_a_deleted_stack_is_skipped_with_a_notice(repo):
    proc, out = run_detect(repo)
    assert proc.returncode == 0, proc.stderr
    assert "infra/live/dev" in out.read_text()
    assert "infra/live/prod" not in out.read_text()
    assert "was deleted in this PR" in proc.stdout


def test_a_module_change_plans_only_existing_stacks(repo):
    proc, out = run_detect(repo, module_prefix="infra/modules")
    assert proc.returncode == 0, proc.stderr
    listed = out.read_text()
    assert "infra/live/dev" in listed
    assert "prod" not in listed


def test_when_everything_is_deleted_the_list_is_empty(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    d = r / "infra" / "live" / "prod"
    d.mkdir(parents=True)
    (d / "main.tf").write_text("# stack\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    shutil.rmtree(d)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "delete the only stack")
    git(r, "update-ref", "refs/remotes/origin/main", "HEAD~1")
    proc, out = run_detect(r)
    assert proc.returncode == 0, proc.stderr
    assert out.read_text().strip() == "workspaces=[]"
