"""The 'Open a pull request' step of actions/bump-gitops-tag/action.yml, run with stub `git` and `gh`.

Dev bumps open `bump/<product>-dev-<tag>` with a chore title; prod keeps `promote/...`. Auto-merge is
enabled only when asked, and the push is never forced.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess

import pytest
import yaml

ACTION = pathlib.Path(__file__).resolve().parents[1] / "actions" / "bump-gitops-tag" / "action.yml"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash needed")


def step_script() -> str:
    doc = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    return next(s for s in doc["runs"]["steps"] if s.get("id") == "pr")["run"]


def run_step(tmp_path, *, env_name, tag, auto_merge="false"):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    for tool, out in (("git", ""), ("gh", 'case "$1 $2" in "pr create") echo https://example/pr/1;; esac')):
        p = bindir / tool
        p.write_text(f'#!/usr/bin/env bash\necho "{tool} $*" >> "{log}"\n{out}\n', encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "output"
    out.touch()
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out), "GH_TOKEN": "x", "PRODUCT": "rova",
        "ENV": env_name, "TAG": tag, "AUTO_MERGE": auto_merge,
    }
    result = subprocess.run(["bash", "-c", step_script()], cwd=tmp_path, capture_output=True, text=True, env=env, timeout=30)
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_dev_opens_a_bump_branch_with_a_chore_title_and_auto_merges(tmp_path):
    result, calls = run_step(tmp_path, env_name="dev", tag="sha-0123456789ab", auto_merge="true")
    assert result.returncode == 0, result.stderr
    assert "git checkout -b bump/rova-dev-sha-0123456789ab" in calls
    assert "git commit -am chore(rova): dev -> sha-0123456789ab" in calls
    assert "git push -u origin bump/rova-dev-sha-0123456789ab" in calls
    assert any(c.startswith("gh pr create --title chore(rova): dev -> sha-0123456789ab") for c in calls)
    assert "gh pr merge https://example/pr/1 --auto --squash" in calls
    assert not any("--force" in c or " -f" in c for c in calls if c.startswith("git push"))


def test_prod_keeps_the_promote_branch_and_never_auto_merges_by_default(tmp_path):
    result, calls = run_step(tmp_path, env_name="prod", tag="v1.2.3")
    assert result.returncode == 0, result.stderr
    assert "git checkout -b promote/rova-v1.2.3" in calls
    assert any(c.startswith("gh pr create --title promote(rova): prod -> v1.2.3") for c in calls)
    assert not any(c.startswith("gh pr merge") for c in calls)


def test_dev_without_auto_merge_does_not_enable_it(tmp_path):
    result, calls = run_step(tmp_path, env_name="dev", tag="sha-0123456789ab")
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith("gh pr merge") for c in calls)
