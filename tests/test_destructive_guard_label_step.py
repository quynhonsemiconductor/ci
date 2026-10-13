"""The 'Resolve the allow label' step of actions/destructive-guard/action.yml, run for real with a stub `gh`.

It used to read the label with `gh api ... 2>/dev/null || true`: a failed lookup and an unlabelled PR looked
the same. The cases here are the ones that must stay distinguishable, and the one that must never open:
a failed lookup is never an allow.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess
import tempfile

import pytest
import yaml

ACTION = pathlib.Path(__file__).resolve().parents[1] / "actions" / "destructive-guard" / "action.yml"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is needed by the step under test")


def step_script() -> str:
    doc = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    step = next(s for s in doc["runs"]["steps"] if s.get("id") == "label")
    return step["run"]


def run_step(tmp_path, *, gh_script: str, **env):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text("#!/usr/bin/env bash\n" + gh_script, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "output"
    out.touch()
    base = {
        "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out), "REPO": "o/r", "SHA": "abc123",
        "PR": "", "DISPATCH_ALLOW": "false", "EVENT": "pull_request", "WANT": "allow-dns-destroy",
        "TMPDIR": tempfile.gettempdir(),
    }
    base.update(env)
    result = subprocess.run(["bash", "-c", step_script()], capture_output=True, text=True, env=base, timeout=30)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return result, outputs


LABELLED = 'echo \'[{"name":"bug"},{"name":"allow-dns-destroy"}]\'\n'
UNLABELLED = 'echo \'[{"name":"bug"}]\'\n'
API_ERROR = 'echo "gh: HTTP 403: Resource not accessible by integration" >&2\nexit 1\n'


def test_the_label_on_a_pr_allows_and_says_where_it_came_from(tmp_path):
    result, out = run_step(tmp_path, gh_script=LABELLED, PR="12")
    assert out["allow"] == "true"
    assert "PR #12" in out["source"]


def test_a_pr_without_the_label_does_not_allow(tmp_path):
    result, out = run_step(tmp_path, gh_script=UNLABELLED, PR="12")
    assert out["allow"] == "false"
    assert "lookup FAILED" not in result.stdout


def test_an_api_error_is_reported_with_the_api_message_and_never_allows(tmp_path):
    result, out = run_step(tmp_path, gh_script=API_ERROR, PR="12")
    assert out["allow"] == "false"
    assert "::warning title=destructive-guard::label lookup FAILED" in result.stdout
    assert "HTTP 403: Resource not accessible by integration" in result.stdout


def test_an_api_error_does_not_pass_off_as_an_empty_label_list(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    failed, _ = run_step(tmp_path / "a", gh_script=API_ERROR, PR="12")
    empty, _ = run_step(tmp_path / "b", gh_script=UNLABELLED, PR="12")
    assert "lookup FAILED" in failed.stdout
    assert "lookup FAILED" not in empty.stdout


def test_a_commit_with_no_pull_request_is_a_notice_not_an_error(tmp_path):
    result, out = run_step(tmp_path, gh_script="echo '[]'\n")
    assert out["allow"] == "false"
    assert "no pull request is associated with abc123" in result.stdout
    assert "lookup FAILED" not in result.stdout


def test_a_push_reads_the_label_from_the_commits_pull_request(tmp_path):
    result, out = run_step(tmp_path, gh_script='echo \'[{"labels":[{"name":"allow-dns-destroy"}]}]\'\n')
    assert out["allow"] == "true"
    assert "commit abc123" in out["source"]


def test_a_dispatch_input_allows(tmp_path):
    result, out = run_step(tmp_path, gh_script=API_ERROR, EVENT="workflow_dispatch", DISPATCH_ALLOW="true")
    assert out["allow"] == "true"
    assert "dispatch input" in out["source"]


def test_a_dispatch_without_the_input_does_not_allow_even_if_the_pr_is_labelled(tmp_path):
    result, out = run_step(tmp_path, gh_script=LABELLED, EVENT="workflow_dispatch", DISPATCH_ALLOW="false", PR="12")
    assert out["allow"] == "false"
