"""No step may download a pushed image from ECR to a runner.

A GitHub-hosted runner is outside AWS, so every byte it pulls from ECR is internet egress ($0.12/GB). qnsc-kb's Trivy scan by ECR
reference did exactly that: 3-4 GB per image, three images per push, 206 GB and $24.78 in 17 days (against $2.11 of storage).
These tests keep it from coming back: the images are scanned from the local build before they are pushed, the build cache is not
read from ECR by default, and the only things the workflows do to a pushed image are manifest-level (inspect, create, retag).
"""

from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = sorted(list((ROOT / ".github" / "workflows").glob("*.yml")) + list((ROOT / "actions").glob("*/action.yml")))

ECR_REF = re.compile(r"ecr-registry|\.dkr\.ecr\.|ECR_REGISTRY|\$\{?REGISTRY\}?|inputs\.registry")
# Commands that move image LAYERS to the machine they run on.
LAYER_PULL = re.compile(r"\b(docker\s+(pull|run|create|save|load)|crane\s+(pull|export)|skopeo\s+(copy|sync)|regctl\s+image\s+(copy|export)|grype|trivy\s+image)\b")


def steps_of(doc: dict):
    if "runs" in doc:  # composite action
        yield "action", doc["runs"].get("steps", [])
    for name, job in (doc.get("jobs") or {}).items():
        yield f"job {name}", job.get("steps", [])


def all_steps():
    for path in FILES:
        doc = yaml.safe_load(path.read_text())
        for where, steps in steps_of(doc):
            for step in steps:
                yield path.name, where, step


def test_there_is_something_to_check():
    assert len(FILES) > 20 and sum(1 for _ in all_steps()) > 100


def test_no_trivy_action_takes_an_ecr_reference():
    for file, where, step in all_steps():
        if str(step.get("uses", "")).startswith("aquasecurity/trivy-action"):
            image = str((step.get("with") or {}).get("image-ref", ""))
            assert not ECR_REF.search(image), f"{file} {where}: Trivy scans {image!r} by registry reference, which downloads the image from ECR"


def test_no_run_step_pulls_layers_from_ecr():
    for file, where, step in all_steps():
        run = step.get("run")
        if not run:
            continue
        for line in run.splitlines():
            if line.strip().startswith("#"):
                continue
            if LAYER_PULL.search(line) and ECR_REF.search(line):
                pytest.fail(f"{file} {where}: pulls image layers from ECR: {line.strip()}")


def test_imagetools_only_does_manifest_level_work():
    for file, where, step in all_steps():
        for line in (step.get("run") or "").splitlines():
            match = re.search(r"imagetools\s+(\w+)", line)
            if match and not line.strip().startswith("#"):
                assert match.group(1) in ("inspect", "create"), f"{file} {where}: imagetools {match.group(1)} may copy layers"


def test_registry_build_cache_is_never_the_default():
    action = yaml.safe_load((ROOT / "actions/build-push-ecr/action.yml").read_text())
    assert action["inputs"]["cache-backend"]["default"] != "registry"
    reusable = yaml.safe_load((ROOT / ".github/workflows/backend-deploy.yml").read_text())
    assert reusable[True]["workflow_call"]["inputs"]["cache_backend"]["default"] != "registry"


def test_no_workflow_or_action_asks_for_registry_cache_by_default():
    for file, where, step in all_steps():
        cache = str((step.get("with") or {}).get("cache-from", ""))
        if "type=registry" in cache and not file.endswith("action.yml"):
            pytest.fail(f"{file} {where}: reads the build cache from a registry")


# ── build-push-ecr: the pre-push scan ──────────────────────────────────────────────────────────────────────────────────────────

def build_push_steps():
    action = yaml.safe_load((ROOT / "actions/build-push-ecr/action.yml").read_text())
    return {s.get("name"): (i, s) for i, s in enumerate(action["runs"]["steps"])}, action


def test_the_scan_builds_locally_scans_and_only_then_pushes():
    steps, _ = build_push_steps()
    local_i, local = steps["Build for scan (local, nothing pushed)"]
    scan_i, scan = steps["Scan before push (CRITICAL blocks; nothing has been pushed yet)"]
    push_i, push = steps["Build & push"]
    assert local_i < scan_i < push_i
    w = local["with"]
    assert w["load"] is True and w["push"] is False
    assert w["provenance"] is False and w["sbom"] is False  # the Docker exporter cannot carry an index
    assert "cache-to" not in w  # the local build must not write the cache
    for key in ("context", "file", "target", "platforms", "cache-from"):
        assert w[key] == push["with"][key], f"the scanned build must use the same {key} as the pushed one"
    assert w["secrets"] == push["with"]["secrets"]
    assert ECR_REF.search(str(scan["with"]["image-ref"])) is None
    assert scan["with"]["exit-code"] == "1"
    for step in (local, scan):
        assert step["if"] == "${{ inputs.scan == 'true' }}"


def test_the_pushed_build_keeps_its_attestations_and_cache_write_rule():
    steps, _ = build_push_steps()
    push = steps["Build & push"][1]["with"]
    assert push["provenance"] == "mode=max" and push["sbom"] is True
    assert push["cache-to"] == "${{ steps.cache.outputs.to }}"  # main-only writes are decided in the cache step


def test_a_multi_platform_scan_is_refused_up_front():
    steps, _ = build_push_steps()
    run = steps["Check the scan can run"][1]["run"]
    assert "*,*" in run and "exit 1" in run


def test_scan_is_opt_in_so_other_callers_are_unchanged():
    _, action = build_push_steps()
    assert action["inputs"]["scan"]["default"] == "false"


# ── backend-deploy: where the scan lives now ──────────────────────────────────────────────────────────────────────────────────

def backend_jobs():
    return yaml.safe_load((ROOT / ".github/workflows/backend-deploy.yml").read_text())["jobs"]


def test_the_build_job_scans_through_build_push_ecr():
    build = backend_jobs()["build"]
    step = next(s for s in build["steps"] if str(s.get("uses", "")).startswith("quynhonsemiconductor/ci/actions/build-push-ecr"))
    assert step["with"]["scan"] == "true"
    assert not any(str(s.get("uses", "")).startswith("aquasecurity/trivy-action") for s in build["steps"])


def test_the_merge_job_pulls_nothing_to_scan():
    merge = backend_jobs()["merge"]
    assert not any(str(s.get("uses", "")).startswith("aquasecurity/trivy-action") for s in merge["steps"])
    assert any("imagetools create" in (s.get("run") or "") for s in merge["steps"])  # still builds the index from digests
    # both-arch-or-nothing is unchanged
    run = next(s["run"] for s in merge["steps"] if s.get("id") == "merge")
    assert "refusing to tag a partial image" in run and "has no $p manifest" in run


def test_every_leg_must_succeed_before_the_merge_so_a_failed_scan_blocks_the_tag():
    merge = backend_jobs()["merge"]
    assert "build" in merge["needs"]  # `needs` means every matrix leg succeeded
