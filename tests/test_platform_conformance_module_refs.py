"""The `module-refs` contract, which asks whether a live stack's `source` resolves.

Tested because the contract's only value is that it CATCHES things, and a check
that has never been shown to fail is indistinguishable from one that cannot. Both
cases below are bugs that reached `infra`'s main branch inside one week, in the
same stack:

  1. `source = "../../../tf-modules/modules/rds"` — a path out of the repository.
     It resolves on a machine with the two repos side by side and nowhere else, so
     `tofu validate` and tflint both PASSED locally while CI reported "the module
     directory does not exist or cannot be read" for every module in the data
     stacks. The review that was meant to catch it ran in the one environment
     where it is invisible.
  2. `?ref=product-profile-v1.0.0` — a tag nothing produces, because the module
     was missing from release-please-config.json. A ref to a tag that does not
     exist fails at `tofu init`: at apply time, on the machine of whoever is
     mid-migration, not at review.

Loaded by path, like the guard's tests, because the script ships as a standalone
file.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

# NOT importorskip. A missing pyyaml must be a loud error: these tests exist to
# prove the contract catches things, and a skip would let them stop proving it
# without anyone noticing — which is the shape of every bug in this directory.
SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "platform_conformance.py"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("platform_conformance", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def estate(tmp_path: pathlib.Path):  # type: ignore[no-untyped-def]
    """A minimal estate: one live stack, and a tf-modules repo carrying one tag.

    A REAL git repository rather than a stubbed tag list — the contract reads tags
    with `git tag -l`, and a shallow clone returns none, which is the thing the
    workflow's `fetch-depth: 0` exists for. Stubbing the list would test around
    exactly the property that matters.
    """
    mod = _load()

    (tmp_path / "gitops" / "values").mkdir(parents=True)
    stack = tmp_path / "infra" / "live" / "kb" / "dev"
    stack.mkdir(parents=True)

    tfm = tmp_path / "tf-modules"
    tfm.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"],
                 ["tag", "product-profile-v0.1.0"]):
        subprocess.run(["git", "-C", str(tfm), *args], check=True, env=env)

    return mod, mod.Estate(tmp_path), stack


GIT = "git::https://github.com/quynhonsemiconductor/tf-modules.git//modules/product-profile"


def test_a_ref_that_exists_passes(estate) -> None:  # type: ignore[no-untyped-def]
    mod, e, stack = estate
    (stack / "main.tf").write_text(f'module "product" {{\n  source = "{GIT}?ref=product-profile-v0.1.0"\n}}\n')
    assert mod.check_module_refs(e) == []


def test_a_ref_to_a_tag_that_does_not_exist_fails(estate) -> None:  # type: ignore[no-untyped-def]
    mod, e, stack = estate
    (stack / "main.tf").write_text(f'module "product" {{\n  source = "{GIT}?ref=product-profile-v1.0.0"\n}}\n')
    found = mod.check_module_refs(e)
    assert len(found) == 1
    assert "no such tag" in found[0].detail
    assert "product-profile-v1.0.0" in found[0].detail


def test_a_source_path_out_of_the_repository_fails(estate) -> None:  # type: ignore[no-untyped-def]
    mod, e, stack = estate
    (stack / "main.tf").write_text(
        'module "product" {\n  source = "../../../../tf-modules/modules/product-profile"\n}\n')
    found = mod.check_module_refs(e)
    assert len(found) == 1
    assert "OUTSIDE the repository" in found[0].detail


def test_a_source_path_inside_the_repository_passes(estate) -> None:  # type: ignore[no-untyped-def]
    """`infra` is allowed its own local modules; only ESCAPING the repo is the bug."""
    mod, e, stack = estate
    (stack.parent.parent.parent / "modules" / "thing").mkdir(parents=True)
    (stack / "main.tf").write_text('module "t" {\n  source = "../../../modules/thing"\n}\n')
    assert mod.check_module_refs(e) == []


def test_a_registry_source_is_not_this_contract_s_business(estate) -> None:  # type: ignore[no-untyped-def]
    mod, e, stack = estate
    (stack / "main.tf").write_text('module "x" {\n  source = "terraform-aws-modules/vpc/aws"\n}\n')
    assert mod.check_module_refs(e) == []


def test_a_commented_out_source_is_ignored(estate) -> None:  # type: ignore[no-untyped-def]
    """Comments explain why a module is pinned where it is, and quote sources while
    doing it. Matching those reports a bug in prose."""
    mod, e, stack = estate
    (stack / "main.tf").write_text(
        f'module "product" {{\n  source = "{GIT}?ref=product-profile-v0.1.0"\n}}\n'
        '# source = "../../../../tf-modules/modules/gone"\n'
        '# was: ?ref=product-profile-v1.0.0\n')
    assert mod.check_module_refs(e) == []


def test_no_tf_modules_checkout_is_reported_not_skipped(tmp_path: pathlib.Path) -> None:
    """A contract that cannot run must SAY so. Silently passing when tf-modules is
    absent — or shallow, so `git tag -l` is empty — would make the check a
    decoration exactly when someone relies on it."""
    mod = _load()
    (tmp_path / "gitops" / "values").mkdir(parents=True)
    stack = tmp_path / "infra" / "live" / "kb" / "dev"
    stack.mkdir(parents=True)
    (stack / "main.tf").write_text(f'module "p" {{\n  source = "{GIT}?ref=product-profile-v0.1.0"\n}}\n')

    found = mod.check_module_refs(mod.Estate(tmp_path))
    assert len(found) == 1
    assert "cannot verify" in found[0].detail
