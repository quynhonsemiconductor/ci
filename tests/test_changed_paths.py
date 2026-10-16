"""Tests for changed-paths: it may only turn CI OFF when every change is provably ignorable."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "actions" / "changed-paths" / "changed_paths.py"
WEB_ONLY_IGNORES = "**/*.md\ndocs/**\n.claude/**\napps/web/**"  # a backend CI's view of "cannot affect me"
BOT = "qnsc-automation[bot]"
RELEASE_RULE = f"release-please--@{BOT}=CHANGELOG.md,.release-please-manifest.json,version-only:**/package.json"
VERSION_PATCH = '@@ -1,6 +1,6 @@\n {\n   "name": "rova",\n-  "version": "0.7.18",\n+  "version": "0.8.0",\n   "private": true,\n'
DEP_PATCH = '@@ -9,3 +9,3 @@\n-    "fastify": "5.12.5",\n+    "fastify": "5.12.6",\n'


def run(files, ignore="", skip="", head="feat/x", author="someone", tmp_path=None):
    """files: list of names, or (name, patch) tuples."""
    out = tmp_path / "out"
    rows = []
    for f in files:
        name, patch = (f, None) if isinstance(f, str) else f
        rows.append(json.dumps({"filename": name, "previous_filename": None, "patch": patch}))
    env = dict(os.environ, FILES_JSON="\n".join(rows), IGNORE=ignore, SKIP_HEADS=skip, HEAD_REF=head, AUTHOR=author,
               GITHUB_OUTPUT=str(out))
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


def test_a_rename_needs_both_paths_ignorable(tmp_path):
    out = tmp_path / "out"
    row = json.dumps({"filename": "docs/new.md", "previous_filename": "apps/api/old.ts", "patch": None})
    env = dict(os.environ, FILES_JSON=row, IGNORE=WEB_ONLY_IGNORES, SKIP_HEADS="", HEAD_REF="x", AUTHOR="x", GITHUB_OUTPUT=str(out))
    subprocess.run([sys.executable, str(SCRIPT)], env=env, check=True, capture_output=True)
    assert out.read_text().strip() == "run=true"


RELEASE_FILES = [("CHANGELOG.md", "+x"), (".release-please-manifest.json", None), ("package.json", VERSION_PATCH)]


def test_the_real_release_pr_skips(tmp_path):
    assert run(RELEASE_FILES, skip=RELEASE_RULE, head="release-please--branches--main--components--rova-api", author=BOT,
               tmp_path=tmp_path) == "run=false"


@pytest.mark.parametrize("head,author,files", [
    # a forged branch name from anyone else
    ("release-please--branches--main", "attacker", RELEASE_FILES),
    # the right author on some other branch
    ("feat/x", BOT, RELEASE_FILES),
    # the right branch and author, but a source file rides along
    ("release-please--branches--main", BOT, RELEASE_FILES + [("apps/api/src/a.ts", "+x")]),
    # package.json changed more than the version (a dependency bump)
    ("release-please--branches--main", BOT, [("package.json", VERSION_PATCH + DEP_PATCH)]),
    # package.json diff unavailable (GitHub omits big patches): not provably version-only
    ("release-please--branches--main", BOT, [("package.json", None)]),
    # a script smuggled into package.json under the version line's cover
    ("release-please--branches--main", BOT, [("package.json", '@@ -1,2 +1,2 @@\n-  "version": "1",\n+  "version": "2",\n+  "postinstall": "x"\n')]),
])
def test_release_rule_fails_open(head, author, files, tmp_path):
    assert run(files, skip=RELEASE_RULE, head=head, author=author, tmp_path=tmp_path) == "run=true"


def test_a_rule_without_an_author_is_never_trusted(tmp_path):
    assert run(RELEASE_FILES, skip="release-please--=**", head="release-please--x", author="attacker", tmp_path=tmp_path) == "run=true"


def test_author_match_ignores_case(tmp_path):
    assert run(RELEASE_FILES, skip=RELEASE_RULE, head="release-please--x", author=BOT.upper(), tmp_path=tmp_path) == "run=false"


TOML_PATCH = '@@ -1,4 +1,4 @@\n [project]\n name = "qnsc-kb-backend"\n-version = "0.4.0"\n+version = "0.5.0"\n'


def test_a_python_release_pr_is_version_only_in_pyproject(tmp_path):
    rule = f"release-please--@{BOT}=CHANGELOG.md,.release-please-manifest.json,version-only:pyproject.toml"
    files = [("CHANGELOG.md", "+x"), ("pyproject.toml", TOML_PATCH)]
    assert run(files, skip=rule, head="release-please--x", author=BOT, tmp_path=tmp_path) == "run=false"
    dep = '@@ -9,3 +9,3 @@\n-dependencies = ["a"]\n+dependencies = ["a", "evil"]\n'
    assert run([("pyproject.toml", TOML_PATCH + dep)], skip=rule, head="release-please--x", author=BOT, tmp_path=tmp_path) == "run=true"
