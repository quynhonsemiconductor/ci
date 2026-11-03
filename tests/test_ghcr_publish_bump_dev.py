"""The shared dev bump in .github/workflows/ghcr-publish.yml.

The job is the ONLY dev-bump path for a product: callers turn it on with an input and delete their own
copied job. Pinned to the release whose action is safe at rest (no credential persistence, narrow staging);
a product's rename of `product` vs the gitops key is the `gitops-product` input.
"""

from __future__ import annotations

import pathlib

import yaml

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ghcr-publish.yml"
V1320 = "6c53291be3b072939236c87b3316c0f9ea187c59"


def doc():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_bump_dev_is_opt_in_and_dev_only():
    # PyYAML reads the bare `on:` key as boolean True.
    inputs = doc()[True]["workflow_call"]["inputs"]
    assert inputs["bump-dev"]["default"] == "false"
    job = doc()["jobs"]["bump-dev"]
    assert job["if"] == "${{ inputs.bump-dev == 'true' && github.ref == 'refs/heads/main' }}"
    step = next(s for s in job["steps"] if "bump-gitops-tag" in s.get("uses", ""))
    assert step["with"]["env"] == "dev"
    assert step["with"]["auto-merge"] == "true"


def test_bump_dev_calls_the_fixed_release():
    job = doc()["jobs"]["bump-dev"]
    uses = next(s["uses"] for s in job["steps"] if "bump-gitops-tag" in s.get("uses", ""))
    assert uses == f"quynhonsemiconductor/ci/actions/bump-gitops-tag@{V1320}"
    assert f"bump-gitops-tag@{V1320}  # v1.32.0" in WORKFLOW.read_text(encoding="utf-8")
    # The old, credential-persisting pin must never come back.
    assert "db42e37" not in WORKFLOW.read_text(encoding="utf-8")


def test_bump_dev_uses_the_published_digests_and_gitops_product():
    job = doc()["jobs"]["bump-dev"]
    assert job["needs"] == ["build", "digests"]
    step = next(s for s in job["steps"] if "bump-gitops-tag" in s.get("uses", ""))
    assert step["with"]["digests"] == "${{ needs.digests.outputs.digests }}"
    assert step["with"]["tag"] == "${{ needs.build.outputs.tag }}"
    assert step["with"]["product"] == "${{ inputs.gitops-product || inputs.product }}"
    assert "join(fromJSON(inputs.services-json)" in step["with"]["services"]
