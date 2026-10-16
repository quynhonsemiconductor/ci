"""Tests for changed-paths: it may only turn CI OFF when every change is provably ignorable."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "actions" / "changed-paths" / "changed_paths.py"
WEB_ONLY_IGNORES = "**/*.md\ndocs/**\n.claude/**\napps/web/**"  # a backend CI's view of "cannot affect me"


def run(files, ignore="", skip="", head="feat/x", tmp_path=None):
    out = tmp_path / "out"
    env = dict(os.environ, FILES="\n".join(files), IGNORE=ignore, SKIP_HEADS=skip, HEAD_REF=head, GITHUB_OUTPUT=str(out))
    subprocess.run([sys.executable, str(SCRIPT)], env=env, check=True, capture_output=True)
    return out.read_text().strip()


@pytest.mark.parametrize("files,expected", [
    (["apps/web/src/a.ts"], "false"),
    (["README.md", "docs/x/y.png"], "false"),
    (["apps/api/README.md"], "false"),              # ** crosses directories
    (["apps/web/src/a.ts", "apps/api/src/b.ts"], "true"),  # one backend file is enough
    (["package.json"], "true"),                     # shared files are never ignorable
    (["apps/webx/a.ts"], "true"),                   # a prefix match is not a directory match
    ([], "true"),                                   # nothing listed: do not guess
])
def test_ignore_list_only_skips_when_every_file_matches(files, expected, tmp_path):
    assert run(files, ignore=WEB_ONLY_IGNORES, tmp_path=tmp_path) == f"run={expected}"


def test_no_ignore_list_never_skips(tmp_path):
    assert run(["docs/a.md"], ignore="", tmp_path=tmp_path) == "run=true"


def test_the_3000_file_ceiling_runs_everything(tmp_path):
    files = [f"docs/{i}.md" for i in range(3000)]
    assert run(files, ignore=WEB_ONLY_IGNORES, tmp_path=tmp_path) == "run=true"


@pytest.mark.parametrize("head,files,expected", [
    ("release-please--branches--main", ["CHANGELOG.md", "package.json"], "false"),
    ("renovate/github-actions", [".github/workflows/a.yml", ".github/workflows/b.yml"], "false"),
    ("renovate/github-actions", [".github/workflows/a.yml", "package.json"], "true"),   # not Actions-only
    ("feat/x", [".github/workflows/a.yml"], "true"),                                   # not a renovate branch
])
def test_head_branch_rules(head, files, expected, tmp_path):
    rules = "release-please--=**\nrenovate/=.github/workflows/**"
    assert run(files, skip=rules, head=head, tmp_path=tmp_path) == f"run={expected}"
