"""Every setup-opentofu step must install the REAL tofu binary (tofu_wrapper: false).

The action's wrapper (the default) captures stdout/stderr/exit-code as step
outputs and makes `tofu` itself exit 0. That silently breaks three things this
estate gates on: `tofu plan -detailed-exitcode` (infra's apply-onprem saw
"Plan: 8 to add" and then skipped apply because the wrapper reported 0),
plain `$?`, and `${PIPESTATUS[0]}` — and every lint gate that judges tofu by
its exit code (`fmt -check`, `validate`). The failure mode is the worst kind:
the step passes green on a real problem.

Written after iac-lint shipped without the setting and the wrapper ate both
its own exit codes and its callers'.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = sorted(
    list((ROOT / ".github" / "workflows").glob("*.yml"))
    + list((ROOT / "actions").glob("*/action.yml"))
)

SETUP_TOFU = "opentofu/setup-opentofu@"


def all_steps():
    for path in FILES:
        doc = yaml.safe_load(path.read_text())
        steps = list(doc.get("runs", {}).get("steps", []) or [])
        for job in (doc.get("jobs") or {}).values():
            steps.extend(job.get("steps") or [])
        for step in steps:
            if isinstance(step.get("uses"), str) and SETUP_TOFU in step["uses"]:
                yield path.relative_to(ROOT), step


def test_every_setup_opentofu_disables_the_wrapper():
    found = 0
    for where, step in all_steps():
        found += 1
        with_ = step.get("with") or {}
        assert with_.get("tofu_wrapper") is False, (
            f"{where}: step '{step.get('name') or step['uses']}' installs "
            f"opentofu without `tofu_wrapper: false`. The default wrapper "
            f"always exits 0 and swallows `-detailed-exitcode`, `$?` and "
            f"`${{PIPESTATUS[0]}}` — see the module docstring."
        )
    assert found >= 1, (
        "no setup-opentofu step found — the assert above must never pass on a "
        "renamed installer it no longer sees"
    )
