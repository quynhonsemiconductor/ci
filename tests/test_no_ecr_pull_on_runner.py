"""No step may download a pushed image from ECR to a runner.

A GitHub-hosted runner is outside AWS, so every byte it pulls from ECR is internet egress ($0.12/GB). qnsc-kb's Trivy scan by ECR
reference did exactly that: 3-4 GB per image, three images per push, 206 GB and $24.78 in 17 days (against $2.11 of storage).
These tests keep it from coming back: the images are scanned from the local build before they are pushed, the build cache is not
read from ECR by default, and the only things the workflows do to a pushed image are manifest-level (inspect, create, retag).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTION = ROOT / "actions/build-push-ecr"
FILES = sorted(list((ROOT / ".github" / "workflows").glob("*.yml")) + list((ROOT / "actions").glob("*/action.yml")))

ECR_REF = re.compile(r"ecr-registry|\.dkr\.ecr\.|ECR_REGISTRY|\$\{?REGISTRY\}?|inputs\.registry|image-uri|IMAGE_URI")
# Commands that move image LAYERS to the machine they run on.
LAYER_PULL = re.compile(r"\b(docker\s+(pull|run|create|save|load)|crane\s+(pull|export)|skopeo\s+(copy|sync)|regctl\s+image\s+(copy|export)|grype|trivy\s+image)\b")
# Actions that scan an image by reference. Any of them given an ECR reference downloads the image.
SCANNERS = ("aquasecurity/trivy-action", "/scan-image")


def is_scanner(uses: str) -> bool:
    return any(uses.startswith(s) or s in uses for s in SCANNERS)
CONTINUED = re.compile(r"\\\r?\n\s*")
VARIABLE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def steps_of(doc: dict):
    if "runs" in doc:  # composite action
        yield "action", {}, doc["runs"].get("steps", [])
    for name, job in (doc.get("jobs") or {}).items():
        yield f"job {name}", job.get("env") or {}, job.get("steps", [])


def all_steps():
    for path in FILES:
        doc = yaml.safe_load(path.read_text())
        for where, job_env, steps in steps_of(doc):
            for step in steps:
                # A step sees its job's env too; its own env wins.
                yield path.name, where, {**step, "env": {**job_env, **(step.get("env") or {})}}


def commands(step: dict):
    """The step's shell lines: backslash continuations joined, comments dropped, and `$NAME` replaced by the step's env value.

    The substitution is what lets `docker pull "$IMAGE_URI"` be judged by where IMAGE_URI points, not by the word in the script.
    """
    env = {k: str(v) for k, v in step["env"].items()}
    for line in CONTINUED.sub(" ", str(step.get("run") or "")).splitlines():
        if line.strip().startswith("#"):
            continue
        yield VARIABLE.sub(lambda m: env.get(m.group(1), m.group(0)), line)


def run_snippet(snippet: str, **env: str) -> subprocess.CompletedProcess:
    """Run a step's `run:` block the way the runner does (bash -e -o pipefail) with the given env."""
    return subprocess.run(
        ["bash", "-eo", "pipefail", "-c", snippet],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )


def test_there_is_something_to_check():
    assert len(FILES) > 20 and sum(1 for _ in all_steps()) > 100


def test_no_scanner_takes_an_ecr_reference():
    for file, where, step in all_steps():
        if is_scanner(str(step.get("uses", ""))):
            image = str((step.get("with") or {}).get("image-ref", ""))
            assert not ECR_REF.search(image), f"{file} {where}: scans {image!r} by registry reference, which downloads the image from ECR"


def test_no_run_step_pulls_layers_from_ecr():
    for file, where, step in all_steps():
        for line in commands(step):
            if LAYER_PULL.search(line) and ECR_REF.search(line):
                pytest.fail(f"{file} {where}: pulls image layers from ECR: {line.strip()}")


def test_the_guard_sees_through_env_and_continuations():
    """Self-check: the rules above must catch the shapes that slipped past the first version of this test."""
    cases = [
        ({"env": {"IMAGE_URI": "${{ steps.tags.outputs.image-uri }}"}, "run": 'docker pull "$IMAGE_URI"'}, True),
        ({"env": {"IMG": "${{ steps.x.outputs.image-uri }}"}, "run": 'trivy image "$IMG"'}, True),
        ({"env": {"IMG": "${{ steps.x.outputs.image-uri }}"}, "run": "trivy image \\\n  --severity CRITICAL \\\n  \"$IMG\""}, True),
        ({"env": {}, "run": "docker pull 123456.dkr.ecr.ap-southeast-1.amazonaws.com/x:sha"}, True),
        ({"env": {"IMG": "ecr-prepush-scan/x:scan"}, "run": 'trivy image "$IMG"'}, False),
    ]
    for step, caught in cases:
        found = any(LAYER_PULL.search(line) and ECR_REF.search(line) for line in commands(step))
        assert found is caught, step


def test_the_scanner_rule_catches_scan_image_as_well_as_trivy_action():
    assert is_scanner("aquasecurity/trivy-action@v0.36.0")
    assert is_scanner("quynhonsemiconductor/ci/actions/scan-image@v1")
    assert not is_scanner("quynhonsemiconductor/ci/actions/build-push-ecr@v1")
    assert ECR_REF.search("${{ steps.tags.outputs.image-uri }}")


def test_imagetools_only_does_manifest_level_work():
    for file, where, step in all_steps():
        for line in commands(step):
            match = re.search(r"imagetools\s+(\w+)", line)
            if match and not line.strip().startswith("#"):
                assert match.group(1) in ("inspect", "create"), f"{file} {where}: imagetools {match.group(1)} may copy layers"


def test_registry_build_cache_is_never_the_default():
    action = yaml.safe_load((ROOT / "actions/build-push-ecr/action.yml").read_text())
    assert action["inputs"]["cache-backend"]["default"] != "registry"


def test_no_workflow_or_action_asks_for_registry_cache_by_default():
    for file, where, step in all_steps():
        cache = str((step.get("with") or {}).get("cache-from", ""))
        if "type=registry" in cache and not file.endswith("action.yml"):
            pytest.fail(f"{file} {where}: reads the build cache from a registry")


# ── build-push-ecr: the pre-push scan ──────────────────────────────────────────────────────────────────────────────────────────

def build_push_steps():
    action = yaml.safe_load((ACTION / "action.yml").read_text())
    return {s.get("name"): (i, s) for i, s in enumerate(action["runs"]["steps"])}, action


def test_the_scan_builds_locally_scans_and_only_then_pushes():
    steps, _ = build_push_steps()
    local_i, local = steps["Build for scan (local, nothing pushed)"]
    scan_i, scan = steps["Scan before push (CRITICAL blocks; nothing has been pushed yet)"]
    push_i, push = steps["Push the scanned image"]
    assert local_i < scan_i < push_i
    w = local["with"]
    assert w["load"] is True and w["push"] is False
    assert w["provenance"] is False and w["sbom"] is False  # the Docker exporter cannot carry an index
    # This is now the only build on the scan path, so it also writes the cache and carries the labels the pushed image needs.
    assert w["cache-to"] == "${{ steps.cache.outputs.to }}"
    assert w["labels"] == "${{ inputs.labels }}"
    for key in ("context", "file", "target", "platforms", "cache-from", "secrets"):
        assert w[key] == steps["Build & push"][1]["with"][key], f"the scanned build must use the same {key} as the pushed one"
    assert ECR_REF.search(str(scan["with"]["image-ref"])) is None
    assert scan["with"]["exit-code"] == "1"
    for name in ("Build for scan (local, nothing pushed)", "Scan before push (CRITICAL blocks; nothing has been pushed yet)"):
        assert steps[name][1]["if"] == "${{ inputs.scan == 'true' }}"


def test_the_scan_path_pushes_the_scanned_image_and_never_rebuilds_it():
    """The bug this replaces: a second buildx build for the push, compared by diff_id. A cache miss rebuilt a layer and the
    gate failed on a good image (qnsc-kb worker, 2026-11-03). The push must be `docker push` of the loaded, scanned image."""
    steps, _ = build_push_steps()
    tag_i, tag = steps["Tag the scanned image"]
    push_i, push = steps["Push the scanned image"]
    verify_i, _ = steps["Verify the pushed image has the scanned layers"]
    build_i, _ = steps["Build & push"]
    assert build_i > push_i, "the buildx build must not run on the scan path"
    assert steps["Build & push"][1]["if"] == "${{ inputs.scan != 'true' }}"
    assert tag_i < push_i < verify_i
    assert tag["if"] == push["if"] == "${{ inputs.scan == 'true' }}"
    assert "docker tag" in tag["run"] and tag["env"]["TAGS"] == "${{ steps.tags.outputs.tags }}"
    assert 'docker push "$tag"' in push["run"]
    assert "sha256:" in push["run"] and "digest=" in push["run"]
    # No buildx, no rebuild: a second build-push-action on this path is exactly the regression.
    for name in ("Tag the scanned image", "Push the scanned image"):
        assert not (steps[name][1].get("uses") or "").startswith("docker/build-push-action")


def test_the_pushed_build_keeps_its_attestations_and_cache_write_rule():
    steps, _ = build_push_steps()
    push = steps["Build & push"][1]["with"]
    assert push["provenance"] == "mode=max" and push["sbom"] is True
    assert push["cache-to"] == "${{ steps.cache.outputs.to }}"  # main-only writes are decided in the cache step


def test_the_scan_input_must_be_exactly_true_or_false():
    steps, _ = build_push_steps()
    run = steps["Check the scan input"][1]["run"]
    for ok in ("true", "false"):
        assert run_snippet(run, SCAN=ok).returncode == 0
    for bad in ("yes", "TRUE", "1", ""):
        result = run_snippet(run, SCAN=bad)
        assert result.returncode != 0, f"scan={bad!r} must fail the step, not skip the scan"
        assert "scan must be exactly 'true' or 'false'" in result.stdout


def test_the_scan_input_check_runs_before_anything_reads_it():
    _, action = build_push_steps()
    assert action["runs"]["steps"][0]["name"] == "Check the scan input"


def test_a_multi_platform_scan_is_refused_up_front():
    steps, _ = build_push_steps()
    run = steps["Check the scan can run"][1]["run"]
    assert run_snippet(run, PLATFORMS="linux/arm64", PUSH_BY_DIGEST="false").returncode == 0
    assert run_snippet(run, PLATFORMS="", PUSH_BY_DIGEST="false").returncode == 0  # empty = the runner's own platform
    for many in ("linux/amd64,linux/arm64", "linux/amd64 linux/arm64", "linux/amd64, linux/arm64"):
        result = run_snippet(run, PLATFORMS=many, PUSH_BY_DIGEST="false")
        assert result.returncode != 0, f"platforms={many!r} must be refused"
        assert "needs a single platform" in result.stdout


def test_a_by_digest_push_cannot_be_combined_with_the_scan():
    """The scanned image is pushed with `docker push`, which needs a tag; push-by-digest publishes an untagged image."""
    steps, _ = build_push_steps()
    run = steps["Check the scan can run"][1]["run"]
    result = run_snippet(run, PLATFORMS="linux/amd64", PUSH_BY_DIGEST="true")
    assert result.returncode != 0
    assert "cannot be combined with push-by-digest" in result.stdout


def test_free_disk_runs_only_under_scan_and_reports_df_to_the_summary():
    steps, _ = build_push_steps()
    step = steps["Free runner disk for the scan"][1]
    assert step["if"] == "${{ inputs.scan == 'true' }}"
    assert "sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc" in step["run"]
    assert "GITHUB_STEP_SUMMARY" in step["run"] and "df -h" in step["run"]


def test_the_scanned_layers_are_recorded_before_the_push_and_the_image_is_dropped_after_it():
    steps, _ = build_push_steps()
    record_i, record = steps["Record the scanned layers"]
    push_i, _ = steps["Push the scanned image"]
    scan_i, _ = steps["Scan before push (CRITICAL blocks; nothing has been pushed yet)"]
    drop_i, drop = steps["Drop the pushed image from the runner"]
    assert scan_i < record_i < push_i < drop_i
    assert record["if"] == drop["if"] == "${{ inputs.scan == 'true' }}"
    assert "{{json .RootFS.Layers}}" in record["run"]
    # The image must NOT be removed before the push any more: it IS the image being pushed.
    assert "docker image rm" not in record["run"]
    assert "docker image rm" in drop["run"]


def test_the_pushed_image_must_have_the_scanned_layers_before_anything_downstream():
    steps, action = build_push_steps()
    verify_i, verify = steps["Verify the pushed image has the scanned layers"]
    push_i, _ = steps["Push the scanned image"]
    expose_i, _ = steps["Expose image URI and digest"]
    assert push_i < verify_i < expose_i
    assert verify["if"] == "${{ inputs.scan == 'true' }}"
    assert "imagetools inspect" in verify["run"] and "$SAME_LAYERS" in verify["run"]
    assert verify["env"]["SAME_LAYERS"].endswith("/same_layers.sh")
    assert "$RUNNER_TEMP/scanned-layers.json" in verify["run"] and "$RUNNER_TEMP/pushed-layers.json" in verify["run"]


def test_trivy_keeps_its_cache_out_of_the_build_context():
    """trivy-action defaults cache-dir to ${{ github.workspace }}/.cache/trivy, inside the build context: KB's push shipped it."""
    steps, _ = build_push_steps()
    scan = steps["Scan before push (CRITICAL blocks; nothing has been pushed yet)"][1]
    assert "runner.temp" in str(scan["with"]["cache-dir"])
    assert "github.workspace" not in str(scan["with"]["cache-dir"])


def test_the_scan_path_attests_the_pushed_digest():
    """The scan path pushes the local image, so the buildx attestations are gone. They must come back as GitHub attestations
    on the PUSHED DIGEST: provenance, and an SBOM of that same image, both not a rebuild or a pull."""
    steps, _ = build_push_steps()
    push_i, _ = steps["Push the scanned image"]
    verify_i, _ = steps["Verify the pushed image has the scanned layers"]
    prov_i, prov = steps["Attest the pushed image's build provenance"]
    sbom_i, sbom = steps["Generate an SBOM for the pushed image"]
    attest_i, attest = steps["Attest the pushed image's SBOM"]
    drop_i, _ = steps["Drop the pushed image from the runner"]
    assert push_i < verify_i < prov_i < sbom_i < attest_i < drop_i
    assert prov["uses"].startswith("actions/attest-build-provenance@")
    assert attest["uses"].startswith("actions/attest-sbom@")
    assert sbom["uses"].startswith("anchore/sbom-action@")
    for step in (prov, attest):
        assert step["with"]["subject-digest"] == "${{ steps.build.outputs.digest }}"
        assert step["with"]["subject-name"] == "${{ inputs.ecr-registry }}/${{ inputs.image-name }}"
        assert step["if"] == "${{ inputs.scan == 'true' }}"
    assert attest["with"]["sbom-path"] == "${{ runner.temp }}/sbom.spdx.json"
    assert sbom["with"]["output-file"] == "${{ runner.temp }}/sbom.spdx.json"
    # syft reads the local copy; the image must not be dropped before it runs, and nothing must pull it back from the registry.
    assert sbom["with"]["image"] == "ecr-prepush-scan/${{ inputs.image-name }}:scan"
    assert sbom["with"]["upload-artifact"] is False and sbom["with"]["upload-release-assets"] is False


def test_registry_cache_is_refused_with_the_scan():
    """A registry cache is written DURING the build, before the gates: a rejected image would still leave layers in GHCR."""
    steps, _ = build_push_steps()
    run = steps["Resolve cache backend"][1]["run"]
    env = {"BACKEND": "registry", "SCAN": "true", "SCOPE": "s", "REGISTRY": "ghcr.io/o", "IMAGE": "i",
           "REF": "refs/heads/main", "DEFAULT_BRANCH": "main"}
    result = run_snippet(run, GITHUB_OUTPUT=os.devnull, GITHUB_STEP_SUMMARY=os.devnull, **env)
    assert result.returncode != 0
    assert "registry cannot be used with scan: true" in result.stdout
    # gha (the default) and none stay allowed, and registry stays allowed without the scan.
    for ok in ({"BACKEND": "gha", "SCAN": "true"}, {"BACKEND": "none", "SCAN": "true"}, {"BACKEND": "registry", "SCAN": "false"}):
        result = run_snippet(run, GITHUB_OUTPUT=os.devnull, GITHUB_STEP_SUMMARY=os.devnull, **{**env, **ok})
        assert result.returncode == 0, (ok, result.stdout)


def test_the_build_context_is_checked_between_the_scan_and_the_push():
    steps, _ = build_push_steps()
    record_i, record = steps["Record the build context"]
    scan_i, _ = steps["Scan before push (CRITICAL blocks; nothing has been pushed yet)"]
    check_i, check = steps["Check nothing wrote into the build context (the push would ship it)"]
    push_i, _ = steps["Push the scanned image"]
    assert record_i < scan_i < check_i < push_i
    assert record["if"] == check["if"] == "${{ inputs.scan == 'true' }}"


def test_the_build_context_check_catches_a_write_and_passes_without_one(tmp_path):
    steps, _ = build_push_steps()
    record = steps["Record the build context"][1]["run"]
    check = steps["Check nothing wrote into the build context (the push would ship it)"][1]["run"]
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    subprocess.run(["git", "init", "-q", str(ctx)], check=True)
    (ctx / "Dockerfile").write_text("FROM scratch\n")
    (ctx / ".gitignore").write_text("ignored.txt\n")
    (ctx / "ignored.txt").write_text("x")
    env = {"CTX": str(ctx), "RUNNER_TEMP": str(tmp_path), "SNAPSHOT": str(tmp_path / "context-before.txt")}
    assert run_snippet(record, **env).returncode == 0
    assert run_snippet(check, **env).returncode == 0  # nothing written: passes
    (ctx / ".cache" / "trivy").mkdir(parents=True)
    (ctx / ".cache" / "trivy" / "trivy.db").write_text("db")  # what the scanner did before the fix
    result = run_snippet(check, **env)
    assert result.returncode != 0
    assert "wrote into the build context" in result.stdout + result.stderr
    assert "trivy.db" in result.stdout + result.stderr


def test_the_build_context_must_be_a_git_checkout(tmp_path):
    steps, _ = build_push_steps()
    record = steps["Record the build context"][1]["run"]
    env = {"CTX": str(tmp_path), "RUNNER_TEMP": str(tmp_path), "SNAPSHOT": str(tmp_path / "s.txt")}
    assert run_snippet(record, **env).returncode != 0


def test_scan_is_opt_in_so_other_callers_are_unchanged():
    _, action = build_push_steps()
    assert action["inputs"]["scan"]["default"] == "false"


# ── same_layers.sh: the diff_id comparison, run for real ─────────────────────────────────────────────────────────────────────

A, B, C = (f"sha256:{c * 64}" for c in "abc")


def same_layers(tmp_path, scanned, pushed) -> subprocess.CompletedProcess:
    scanned_file, pushed_file = tmp_path / "scanned.json", tmp_path / "pushed.json"
    scanned_file.write_text(json.dumps(scanned))
    pushed_file.write_text(json.dumps(pushed))
    return subprocess.run([str(ACTION / "same_layers.sh"), str(scanned_file), str(pushed_file)], capture_output=True, text=True)


def test_same_layers_passes_when_the_pushed_layers_are_the_scanned_ones(tmp_path):
    pushed = {"architecture": "arm64", "rootfs": {"type": "layers", "diff_ids": [A, B]}}
    assert same_layers(tmp_path, [A, B], pushed).returncode == 0


def test_same_layers_fails_on_any_difference(tmp_path):
    pushed = {"rootfs": {"diff_ids": [A, C]}}
    result = same_layers(tmp_path, [A, B], pushed)
    assert result.returncode == 1 and "not the scanned one" in result.stdout


def test_same_layers_fails_when_the_pushed_image_has_extra_layers(tmp_path):
    assert same_layers(tmp_path, [A], {"rootfs": {"diff_ids": [A, B]}}).returncode == 1


def test_same_layers_refuses_an_empty_scan_record(tmp_path):
    assert same_layers(tmp_path, [], {"rootfs": {"diff_ids": []}}).returncode == 1


def test_same_layers_refuses_an_index_with_two_platform_configs(tmp_path):
    config = {"rootfs": {"diff_ids": [A]}}
    result = same_layers(tmp_path, [A], {"linux/amd64": config, "linux/arm64": config})
    assert result.returncode == 1 and "got 2" in result.stdout


def test_same_layers_refuses_a_pushed_image_with_no_config(tmp_path):
    assert same_layers(tmp_path, [A], None).returncode == 1
