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
    listing = tmp_path / "files.jsonl"
    listing.write_text("\n".join(rows))
    env = dict(os.environ, FILES_PATH=str(listing), IGNORE=ignore, SKIP_HEADS=skip, HEAD_REF=head, AUTHOR=author,
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


BIG_PATCH = "@@ -1,2 +1,2 @@\n" + "-old line of a lockfile entry\n+new line of a lockfile entry\n" * 60  # ~3.5 KB


def test_the_3000_file_ceiling_runs_everything(tmp_path):
    files = [(f"docs/{i}.md", BIG_PATCH) for i in range(3000)]  # ~10 MB of diff, far past ARG_MAX and the 128 KB env-string cap
    assert run(files, ignore=WEB_ONLY_IGNORES, tmp_path=tmp_path) == "run=true"


def test_a_huge_but_ignorable_listing_is_read_from_the_file(tmp_path):
    """The real regression: the list must travel by FILE. 2,999 ignorable files with ~3.5 KB diffs each (~10 MB) would crash with
    E2BIG if the action passed them through the environment or argv, and here must be decided normally."""
    files = [(f"docs/{i}.md", BIG_PATCH) for i in range(2999)]
    assert run(files, ignore=WEB_ONLY_IGNORES, tmp_path=tmp_path) == "run=false"


def test_an_unreadable_listing_runs_everything(tmp_path):
    out = tmp_path / "out"
    env = dict(os.environ, FILES_PATH=str(tmp_path / "missing.jsonl"), IGNORE=WEB_ONLY_IGNORES, SKIP_HEADS="", HEAD_REF="x",
               AUTHOR="x", GITHUB_OUTPUT=str(out))
    subprocess.run([sys.executable, str(SCRIPT)], env=env, check=True, capture_output=True)
    assert out.read_text().strip() == "run=true"


def test_a_malformed_listing_runs_everything(tmp_path):
    out = tmp_path / "out"
    (tmp_path / "bad.jsonl").write_text("{not json")
    env = dict(os.environ, FILES_PATH=str(tmp_path / "bad.jsonl"), IGNORE=WEB_ONLY_IGNORES, SKIP_HEADS="", HEAD_REF="x",
               AUTHOR="x", GITHUB_OUTPUT=str(out))
    subprocess.run([sys.executable, str(SCRIPT)], env=env, check=True, capture_output=True)
    assert out.read_text().strip() == "run=true"


def test_a_rename_needs_both_paths_ignorable(tmp_path):
    out = tmp_path / "out"
    row = json.dumps({"filename": "docs/new.md", "previous_filename": "apps/api/old.ts", "patch": None})
    (tmp_path / "files.jsonl").write_text(row)
    env = dict(os.environ, FILES_PATH=str(tmp_path / "files.jsonl"), IGNORE=WEB_ONLY_IGNORES, SKIP_HEADS="", HEAD_REF="x", AUTHOR="x", GITHUB_OUTPUT=str(out))
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
    (tmp_path / "out").unlink()  # run() appends to one output file
    dep = '@@ -9,3 +9,3 @@\n-dependencies = ["a"]\n+dependencies = ["a", "evil"]\n'
    assert run([("pyproject.toml", TOML_PATCH + dep)], skip=rule, head="release-please--x", author=BOT, tmp_path=tmp_path) == "run=true"


def run_step(tmp_path, event, monkeypatch_env, fake_gh=None, count_files=0, pr="836"):
    """EXECUTE the action's bash step (not a text check): fake `gh` on PATH, real python."""
    import json as _json
    import stat

    action = (pathlib.Path(__file__).resolve().parents[1] / "actions/changed-paths/action.yml").read_text()
    i = action.find("      run: |")
    block = []
    for line in action[i:].splitlines()[1:]:
        if line.startswith("        ") or line.strip() == "":
            block.append(line[8:])
        else:
            break
    script = "\n".join(block)
    script = script.replace('$GITHUB_ACTION_PATH/changed_paths.py', str(pathlib.Path(__file__).resolve().parents[1] / "actions/changed-paths/changed_paths.py"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    payload = "".join(
        _json.dumps({"filename": f"docs/file{n}.md", "patch": "+x"}) + "\n" for n in range(count_files)
    )
    seen = {}
    gh.write_text(
        "#!/bin/sh\n"
        'echo "$@" >> "' + str(tmp_path / "gh-calls.log") + '"\n'
        "cat <<'JSON'\n" + payload + "JSON\n"
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    out = tmp_path / "out.txt"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "EVENT": event,
        "REPO": "quynhonsemiconductor/probe",
        "PR": pr,
        "HEAD_REF": "",
        "AUTHOR": "",
        "IGNORE": os.environ.get("CP_IGNORE", "**/*.md"),
        "SKIP_HEADS": "",
        "MERGE_BASE_SHA": monkeypatch_env.get("BASE", "1111111"),
        "MERGE_HEAD_SHA": monkeypatch_env.get("HEAD", "2222222"),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(out),
        "GITHUB_ACTION_PATH": str(pathlib.Path(__file__).resolve().parents[1] / "actions/changed-paths"),
        "HOME": os.environ.get("HOME", ""),
    }
    proc = subprocess.run(["bash", "-c", script], env={**os.environ, **env}, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    value = dict(line.split("=", 1) for line in out.read_text().splitlines())["run"]
    calls = (tmp_path / "gh-calls.log").read_text() if (tmp_path / "gh-calls.log").exists() else ""
    return value, calls


@pytest.mark.parametrize(
    "count,expected",
    [(3, "false"), (299, "false"), (300, "true")],  # 3 md files ignorable; 299 still under the cap; 300 hits it
)
def test_merge_group_executes_and_respects_the_compare_cap(tmp_path, count, expected):
    run, _ = run_step(tmp_path, "merge_group", {}, count_files=count)
    assert run == expected


def test_merge_group_compares_base_sha_to_head_sha(tmp_path):
    _, calls = run_step(tmp_path, "merge_group", {"BASE": "aaa111", "HEAD": "bbb222"}, count_files=3)
    assert "compare/aaa111...bbb222" in calls


def test_merge_group_without_shas_runs_everything(tmp_path):
    run, calls = run_step(tmp_path, "merge_group", {"BASE": "", "HEAD": ""})
    assert run == "true"
    assert calls == ""


def test_merge_group_when_gh_fails_runs_everything(tmp_path):
    # an ignore list that would match anything at all — only the missing listing must save it
    import os as _os
    _os.environ["CP_IGNORE"] = "**"
    run, _ = run_step(tmp_path, "merge_group", {}, count_files=0)
    assert run == "true"


def test_pull_request_branch_still_uses_the_pr_files_endpoint(tmp_path):
    # the PR path is untouched by the merge_group work: same endpoint, same filtering
    run, calls = run_step(tmp_path, "pull_request", {}, count_files=3)
    assert run == "false"
    assert "/pulls/836/files" in calls
    assert "compare/" not in calls

