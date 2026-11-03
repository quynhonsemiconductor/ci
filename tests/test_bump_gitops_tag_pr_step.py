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
    git_stub = 'if [ "$1 $2" = "diff --cached" ]; then exit 1; fi'
    for tool, out in (("git", git_stub), ("gh", 'case "$1 $2" in "pr create") echo https://example/pr/1;; esac')):
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
    assert any(c.startswith("git add -A -- values/rova/tags.dev.yaml") for c in calls)
    assert "git commit -m chore(rova): dev -> sha-0123456789ab" in calls
    assert "git push -u origin bump/rova-dev-sha-0123456789ab" in calls
    assert any(c.startswith("gh pr create --title chore(rova): dev -> sha-0123456789ab") for c in calls)
    assert "gh pr merge https://example/pr/1 --auto --squash" in calls
    assert not any("--force" in c or " -f" in c for c in calls if c.startswith("git push"))


def test_prod_keeps_the_promote_branch_and_never_auto_merges_by_default(tmp_path):
    result, calls = run_step(tmp_path, env_name="prod", tag="v1.2.3")
    assert result.returncode == 0, result.stderr
    assert "git checkout -b promote/rova-v1.2.3" in calls
    assert any(c.startswith("gh pr create --title chore(rova): promote prod to v1.2.3") for c in calls)
    assert not any(c.startswith("gh pr merge") for c in calls)


def test_dev_without_auto_merge_does_not_enable_it(tmp_path):
    result, calls = run_step(tmp_path, env_name="dev", tag="sha-0123456789ab")
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith("gh pr merge") for c in calls)


def step(step_id):
    doc = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    return next(x for x in doc["runs"]["steps"] if x.get("id") == step_id)


def real_repo(tmp_path):
    """A real git checkout with a bare origin, a tags file, a tracked rendered file and a scripts/render.sh."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        subprocess.run(["git", "config", k, v], cwd=work, check=True)
    (work / "values/rova").mkdir(parents=True)
    (work / "rendered/rova").mkdir(parents=True)
    (work / "scripts").mkdir()
    (work / "values/rova/tags.dev.yaml").write_text("services: {api: {image: {tag: old}}}\n")
    (work / "scripts/render.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\ncd \"$(dirname \"$0\")/..\"\n"
        "grep -o 'tag: .*[a-z0-9]' values/rova/tags.dev.yaml | head -1 > /dev/null\n"
        "echo \"rendered from $(cat values/rova/tags.dev.yaml | tr -d '\\n')\" > rendered/rova/dev.yaml\n"
        "echo new > rendered/rova/brand-new.yaml\n"
    )
    (work / "scripts/render.sh").chmod(0o755)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=work, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=work, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "main"], cwd=work, check=True)
    return work, origin


def test_render_step_runs_in_the_target_repo_and_the_pr_commit_carries_rendered(tmp_path):
    work, origin = real_repo(tmp_path)
    # what the Bump step does: edit the tags file
    (work / "values/rova/tags.dev.yaml").write_text("services: {api: {image: {tag: sha-new}}}\n")
    r = subprocess.run(["bash", "-c", step("render")["run"]], cwd=work, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "sha-new" in (work / "rendered/rova/dev.yaml").read_text()
    # the PR step with the REAL git and a stub gh
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text('#!/usr/bin/env bash\ncase "$1 $2" in "pr create") echo https://example/pr/1;; esac\n')
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "output"
    out.touch()
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out), "GH_TOKEN": "x",
           "PRODUCT": "rova", "ENV": "dev", "TAG": "sha-new", "AUTO_MERGE": "false"}
    r = subprocess.run(["bash", "-c", step("pr")["run"]], cwd=work, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    files = subprocess.run(["git", "--git-dir", str(origin), "show", "--name-only", "--format=", "bump/rova-dev-sha-new"],
                           capture_output=True, text=True, check=True).stdout.split()
    assert sorted(files) == ["rendered/rova/dev.yaml", "values/rova/tags.dev.yaml"]


def test_render_step_is_conditional_and_pins_helm():
    r = step("render")
    assert "inputs.render == 'true'" in r["if"] and "hashFiles('.gitops/scripts/render.sh')" in r["if"]
    assert "steps.bump.outputs.changed == 'true'" in r["if"]
    doc = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    helm = next(x for x in doc["runs"]["steps"] if x.get("uses", "").startswith("azure/setup-helm@"))
    assert helm["with"]["version"] == "${{ inputs.helm-version }}" and doc["inputs"]["helm-version"]["default"] == "4.3.0"
    names = [x.get("name") for x in doc["runs"]["steps"]]
    assert names.index("Render") < names.index("Commit (dev)") < names.index("Open a pull request")


def test_commit_mode_commit_carries_rendered_too(tmp_path):
    work, origin = real_repo(tmp_path)
    (work / "values/rova/tags.dev.yaml").write_text("services: {api: {image: {tag: sha-new}}}\n")
    subprocess.run(["bash", "-c", step("render")["run"]], cwd=work, check=True, capture_output=True)
    commit = next(x for x in yaml.safe_load(ACTION.read_text(encoding="utf-8"))["runs"]["steps"] if x.get("name") == "Commit (dev)")
    env = {**os.environ, "PRODUCT": "rova", "ENV": "dev", "TAG": "sha-new"}
    r = subprocess.run(["bash", "-c", commit["run"]], cwd=work, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    files = subprocess.run(["git", "--git-dir", str(origin), "show", "--name-only", "--format=", "main"],
                           capture_output=True, text=True, check=True).stdout.split()
    assert sorted(files) == ["rendered/rova/dev.yaml", "values/rova/tags.dev.yaml"]


def test_gitops_checkout_persists_no_credentials_and_both_pushes_authenticate_env_only():
    doc = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    steps = doc["runs"]["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"].get("persist-credentials") is False
    for name in ("Commit (dev)", "Open a pull request"):
        step = next(s for s in steps if s.get("name") == name)
        run = step["run"]
        assert "GIT_CONFIG_COUNT=1" in run
        assert 'GIT_CONFIG_KEY_0="http.https://github.com/.extraheader"' in run
        assert 'GIT_CONFIG_VALUE_0="AUTHORIZATION: basic' in run
        assert "git config --local" not in run
