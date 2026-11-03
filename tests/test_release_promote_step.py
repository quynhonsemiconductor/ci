"""The inline 'Open the promotion pull request' step of .github/workflows/release-promote.yml, run with stubs.

release-promote is inlined (a reusable workflow cannot `uses:` an action at a ref that does not exist yet),
so the shell is tested the same way as test_release_retag.py: record the calls and assert the behaviour that
matters — branch/title/body, staging limited to the two machine-owned files, no auto-merge, and the three
failure paths (existing branch, invalid product, no changelog).
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import pathlib

import yaml

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-promote.yml"
DIGESTS = '{"api":"sha256:' + "1" * 64 + '","worker":"sha256:' + "2" * 64 + '"}'

GIT_STUB = f"""#!{sys.executable}
import os, sys
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as f:
    f.write("git " + " ".join(args) + "\\n")
if args[:1] == ["ls-remote"]:
    sys.exit(int(os.environ.get("STUB_LS_REMOTE_EXIT", "1")))
if args[:2] == ["diff", "--cached"]:
    sys.exit(int(os.environ.get("STUB_NO_CHANGES", "0")))
if args[:2] == ["ls-files", "--error-unmatch"]:
    sys.exit(int(os.environ.get("STUB_LS_FILES_EXIT", "1")))
sys.exit(0)
"""

GH_STUB = f"""#!{sys.executable}
import os, sys
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as f:
    f.write("gh " + " ".join(args) + "\\n")
if args[:2] == ["pr", "list"]:
    print(os.environ.get("STUB_PR_URL", ""))
elif args[:2] == ["pr", "create"]:
    print("https://github.com/example/gitops/pull/9")
else:
    sys.exit("unexpected gh command: " + args[0])
"""


def step_script() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(s for s in doc["jobs"]["promote"]["steps"] if s.get("id") == "pr")["run"]


def run(tmp_path, *, product="rova", tag="v1.2.3", changelog="### Fixes\\n* retag", dev_health="rova-dev: Synced / Healthy",
        pr_url="", ls_remote_exit=1, no_changes=1, ls_files_exit=1, digests=DIGESTS):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("git", GIT_STUB), ("gh", GH_STUB)):
        path = bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    calls = tmp_path / "calls"
    calls.touch()
    out = tmp_path / "output"
    out.touch()
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": os.environ["HOME"],
        "GITHUB_OUTPUT": str(out),
        "STUB_CALLS": str(calls),
        "STUB_PR_URL": pr_url,
        "STUB_LS_REMOTE_EXIT": str(ls_remote_exit),
        "STUB_NO_CHANGES": str(no_changes),
        "STUB_LS_FILES_EXIT": str(ls_files_exit),
        "GH_TOKEN": "app-token",
        "PRODUCT": product,
        "TAG": tag,
        "CHANGELOG": changelog,
        "DEV_HEALTH": dev_health,
        "DIGESTS": digests,
    }
    result = subprocess.run(["bash", "-c", step_script()], cwd=tmp_path, capture_output=True, text=True, env=env, timeout=30)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return result, outputs, calls.read_text().splitlines()


def test_opens_a_promotion_pr_staged_to_the_machine_owned_files(tmp_path):
    (tmp_path / "rendered" / "rova").mkdir(parents=True)
    (tmp_path / "rendered" / "rova" / "prod.yaml").write_text("x", encoding="utf-8")
    result, outputs, calls = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert outputs["url"] == "https://github.com/example/gitops/pull/9"
    assert "git checkout -b promote/rova-v1.2.3" in calls
    assert any(c.startswith("git add -A -- values/rova/tags.prod.yaml rendered/rova/prod.yaml") for c in calls)
    assert "git commit -m chore(rova): promote prod to v1.2.3" in calls
    joined = "\n".join(calls)
    assert "gh pr create --title chore(rova): promote prod to v1.2.3" in joined
    assert "rova-dev: Synced / Healthy" in joined
    assert "retag" in joined
    assert not any("--auto" in c for c in calls)


def test_an_existing_branch_without_a_pr_fails_clearly(tmp_path):
    result, _, calls = run(tmp_path, ls_remote_exit=0)
    assert result.returncode != 0
    assert "exists on gitops but no PR was found" in result.stdout + result.stderr
    assert not any(c.startswith("git push") for c in calls)


def test_an_existing_pr_is_reported_instead_of_opening_a_second(tmp_path):
    result, outputs, calls = run(tmp_path, pr_url="https://github.com/example/gitops/pull/7")
    assert result.returncode == 0, result.stderr
    assert outputs["url"] == "https://github.com/example/gitops/pull/7"
    assert not any(c.startswith("git checkout") for c in calls)


def test_an_invalid_product_fails_before_building_a_branch(tmp_path):
    result, _, calls = run(tmp_path, product="rova/../evil")
    assert result.returncode != 0
    assert "invalid gitops-product" in result.stdout + result.stderr
    assert not any(c.startswith("git checkout") for c in calls)


def test_no_changelog_fails_instead_of_printing_not_supplied(tmp_path):
    result, _, _ = run(tmp_path, changelog="")
    assert result.returncode != 0
    assert "no changelog supplied or found" in result.stdout + result.stderr


def test_a_noop_promote_fails(tmp_path):
    result, _, _ = run(tmp_path, no_changes=0)
    assert result.returncode != 0
    assert "nothing to promote" in result.stdout + result.stderr


def _promote_steps():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"]["promote"]["steps"]


def test_the_changelog_is_read_with_the_job_token_in_its_own_step():
    notes = next(s for s in _promote_steps() if s.get("id") == "notes")
    assert notes["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert notes["if"] == "${{ inputs.changelog == '' }}"
    assert "|| true" not in notes["run"]
    assert "::error" in notes["run"]


def test_the_gitops_checkout_persists_no_credentials_and_the_push_authenticates_itself():
    checkout = next(s for s in _promote_steps() if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"].get("persist-credentials") is False
    pr = next(s for s in _promote_steps() if s.get("id") == "pr")
    assert "GIT_CONFIG_COUNT=1" in pr["run"]
    assert 'GIT_CONFIG_KEY_0="http.https://github.com/.extraheader"' in pr["run"]
    assert "GIT_CONFIG_VALUE_0=\"AUTHORIZATION: basic" in pr["run"]
    assert "git config --local" not in pr["run"]


def test_inputs_are_validated_before_paths_and_branches_are_built():
    validate = next(s for s in _promote_steps() if s.get("name") == "Validate the promote inputs")
    assert "^[a-z0-9-]+$" in validate["run"]
    assert "v[0-9]+" in validate["run"]


def test_without_a_render_stages_only_the_tags_file(tmp_path):
    result, _, calls = run(tmp_path)
    assert result.returncode == 0, result.stderr
    adds = [c for c in calls if c.startswith("git add ")]
    assert adds == ["git add -A -- values/rova/tags.prod.yaml"]


def test_nothing_staged_fails_before_the_commit(tmp_path):
    result, _, calls = run(tmp_path, no_changes=0)
    assert result.returncode != 0
    assert "nothing to promote" in result.stdout + result.stderr
    assert not any(c.startswith("git commit") for c in calls)
