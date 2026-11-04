"""Every `run:` block that builds JSON for `jq --argjson` must survive a SET value.

The bug this pins: `${VAR:-{}}` closes the parameter expansion at the FIRST `}`, so a
set value is followed by a literal `}` and jq rejects it ("invalid JSON text passed to
--argjson"). It shipped in the ghcr-publish dev-bump job of rova and opshub and failed
every main publish while the images themselves pushed fine.

Two layers:
  1. every block in THIS repository's workflows that passes `--argjson` is executed with
     realistic env — all inputs set, and each one unset in turn;
  2. the canonical product snippet is kept as a fixture and both forms are executed, so
     the guard cannot become vacuous if ci's own blocks ever stop using jq, and the
     mutation check proves the bad form still fails.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
MAP_A = '{"api":"%s"}' % D1
MAP_B = '{"web":"%s"}' % D2

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is needed")


def _blocks() -> list[tuple[str, str]]:
    """(workflow name, run block) for every run that passes --argjson."""
    found = []
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                run = step.get("run")
                if run and "--argjson" in run:
                    found.append((wf.name, run))
    return found


def _env_vars(run: str) -> list[str]:
    """Uppercase variables the block reads — the digest maps and their siblings."""
    names = set(re.findall(r"\$\{?([A-Z][A-Z0-9_]+)", run))
    # The merge reads the maps through locals too; those are lowercase and set by the
    # block itself. Anything uppercase is an env input CI provides.
    return sorted(names)


def _run(script: str, env: dict[str, str], tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    out = tmp_path / "gh_output"
    out.write_text("")
    full = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
            "GITHUB_OUTPUT": str(out), **env}
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=full, timeout=30)
    result.output_file = out  # type: ignore[attr-defined]
    return result


def test_every_argjson_block_survives_set_and_unset_env(tmp_path):
    for name, run in _blocks():
        variables = _env_vars(run)
        assert variables, f"{name}: --argjson block reads no uppercase env variable; teach this test its shape"
        all_set = {var: (MAP_A if var.endswith("SERVICES_DIGESTS") else MAP_B) for var in variables}
        cases = [all_set] + [{k: v for k, v in all_set.items() if k != unset} for unset in variables]
        for case in cases:
            env = {var: case.get(var, "") for var in variables}
            result = _run(run, env, tmp_path)
            assert result.returncode == 0, f"{name} failed with env {sorted(env)} set: {result.stderr}"
            if "--argjson" in run and "echo \"digests=" in run:
                assert "digests={" in result.output_file.read_text(), f"{name}: no digest map written"


# The canonical product form. It lives in rova/opshub ghcr-publish.yml; this copy is the
# guard for the class, because those files are not in this repository.
GOOD = """set -euo pipefail
a=${SERVICES_DIGESTS-}; [ -n "$a" ] || a='{}'
b=${WEB_DIGESTS-}; [ -n "$b" ] || b='{}'
merged=$(jq -c -n --argjson a "$a" --argjson b "$b" '$a * $b')
echo "digests=$merged" >> "$GITHUB_OUTPUT"
"""
BAD = """set -euo pipefail
merged=$(jq -c -n --argjson a "${SERVICES_DIGESTS:-{}}" --argjson b "${WEB_DIGESTS:-{}}" '$a * $b')
echo "digests=$merged" >> "$GITHUB_OUTPUT"
"""


@pytest.mark.parametrize("a,b", [(MAP_A, MAP_B), (MAP_A, ""), ("", MAP_B)])
def test_the_product_merge_snippet_handles_set_and_unset(tmp_path, a, b):
    result = _run(GOOD, {"SERVICES_DIGESTS": a, "WEB_DIGESTS": b}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "digests={" in result.output_file.read_text()


def test_the_bad_form_fails_with_a_set_value(tmp_path):
    """Mutation check: the guard above would pass a broken snippet if this did."""
    result = _run(BAD, {"SERVICES_DIGESTS": MAP_A, "WEB_DIGESTS": MAP_B}, tmp_path)
    assert result.returncode != 0
    assert "invalid JSON" in result.stderr
