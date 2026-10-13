"""actions/update-task-definition: every container on the service image moves, and the result is checked.

The incident: qnsc-kb's worker task runs Celery beat from the SAME image as the worker, in a second container.
The deploy rewrote only the container named 'worker'; beat kept `...-worker:latest`, which does not exist in an
immutable ECR repository, so the task failed to start (CannotPullContainerError) and the worker was down.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "actions" / "update-task-definition" / "update_task_definition.py"
spec = importlib.util.spec_from_file_location("update_task_definition", SCRIPT)
utd = importlib.util.module_from_spec(spec)
sys.modules["update_task_definition"] = utd
spec.loader.exec_module(utd)

REG = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com"


def kb_worker_task():
    """The shape of qnsc-kb's worker task definition."""
    return {
        "family": "qnsc-kb-develop-worker", "revision": 138, "status": "ACTIVE", "taskDefinitionArn": "arn:x",
        "registeredAt": "t", "compatibilities": ["FARGATE"], "requiresAttributes": [],
        "containerDefinitions": [
            {"name": "worker", "image": f"{REG}/qnsc-kb-worker:oldsha"},
            {"name": "beat", "image": f"{REG}/qnsc-kb-worker:latest"},
            {"name": "clamav", "image": "clamav/clamav:1.4"},
        ],
    }


def images(task):
    return {c["name"]: c["image"] for c in task["containerDefinitions"]}


def present(*_args, **_kw):
    return subprocess.CompletedProcess([], 0, "sha1\n", "")


def missing(*_args, **_kw):
    return subprocess.CompletedProcess([], 0, "None\n", "")


def test_the_container_sharing_the_image_moves_with_it_and_unrelated_ones_do_not():
    new, log, errors = utd.rewrite(kb_worker_task(), "worker", "sha1")
    assert errors == []
    assert images(new) == {
        "worker": f"{REG}/qnsc-kb-worker:sha1",
        "beat": f"{REG}/qnsc-kb-worker:sha1",
        "clamav": "clamav/clamav:1.4",
    }
    assert any("beat" in line and ":latest" in line and ":sha1" in line for line in log), "each rewrite is logged"
    assert any("clamav" in line and "left alone" in line for line in log)


def test_revision_metadata_is_stripped_so_the_definition_can_be_registered():
    new, _, _ = utd.rewrite(kb_worker_task(), "worker", "sha1")
    for field in ("taskDefinitionArn", "revision", "status", "compatibilities", "requiresAttributes", "registeredAt"):
        assert field not in new


def test_a_missing_primary_container_is_an_error_not_a_silent_no_op():
    _, _, errors = utd.rewrite(kb_worker_task(), "api", "sha1")
    assert errors and "no container named 'api'" in errors[0]


@pytest.mark.parametrize("image,expected", [
    (f"{REG}/r:abc", (f"{REG}/r", "abc")),
    (f"{REG}/r", (f"{REG}/r", "")),
    ("localhost:5000/r", ("localhost:5000/r", "")),
    ("localhost:5000/r:v1", ("localhost:5000/r", "v1")),
    (f"{REG}/r@sha256:aa", (f"{REG}/r", "@sha256:aa")),
    (f"{REG}/r:v1@sha256:aa", (f"{REG}/r", "@sha256:aa")),
])
def test_split_image(image, expected):
    assert utd.split_image(image) == expected


# ── the checks ───────────────────────────────────────────────────────────────────────────────
def test_a_container_left_on_latest_fails_the_check():
    task = kb_worker_task()  # NOT rewritten: beat is still on :latest
    errors, _ = utd.check(task, f"{REG}/qnsc-kb-worker", "ap-southeast-1", runner=present)
    assert any("'beat'" in e and "latest" in e for e in errors)


def test_a_container_with_no_tag_counts_as_latest():
    task = {"containerDefinitions": [{"name": "x", "image": f"{REG}/r"}]}
    errors, _ = utd.check(task, f"{REG}/r", "r", runner=present)
    assert errors


def test_a_tag_missing_from_ecr_fails_the_check():
    new, _, _ = utd.rewrite(kb_worker_task(), "worker", "sha1")
    errors, _ = utd.check(new, f"{REG}/qnsc-kb-worker", "ap-southeast-1", runner=missing)
    assert len(errors) == 2 and all("not in ECR" in e for e in errors)


def test_a_rewritten_task_with_existing_tags_passes():
    new, _, _ = utd.rewrite(kb_worker_task(), "worker", "sha1")
    errors, warnings = utd.check(new, f"{REG}/qnsc-kb-worker", "ap-southeast-1", runner=present)
    assert errors == [] and warnings == []


def test_the_lookup_uses_batch_get_image_which_the_deploy_role_has_not_describe_images():
    calls = []

    def runner(cmd, **_kw):
        calls.append(cmd)
        return present()

    new, _, _ = utd.rewrite(kb_worker_task(), "worker", "sha1")
    utd.check(new, f"{REG}/qnsc-kb-worker", "ap-southeast-1", runner=runner)
    assert calls and all(c[:3] == ["aws", "ecr", "batch-get-image"] for c in calls)
    assert not any("describe-images" in c for c in calls)


def test_a_failed_lookup_of_the_rewritten_image_fails_but_an_unrelated_repo_only_warns():
    task = {"containerDefinitions": [
        {"name": "worker", "image": f"{REG}/qnsc-kb-worker:sha1"},
        {"name": "other", "image": f"{REG}/someone-elses:v1"},
    ]}

    def denied(*_a, **_k):
        return subprocess.CompletedProcess([], 254, "", "AccessDeniedException")

    errors, warnings = utd.check(task, f"{REG}/qnsc-kb-worker", "ap-southeast-1", runner=denied)
    assert len(errors) == 1 and "'worker'" in errors[0]
    assert len(warnings) == 1 and "'other'" in warnings[0]


def test_digest_pinned_and_third_party_images_are_not_looked_up():
    task = {"containerDefinitions": [
        {"name": "a", "image": f"{REG}/r@sha256:aa"},
        {"name": "b", "image": "cloudflare/cloudflared:2026.6.1"},
    ]}

    def boom(*_a, **_k):
        raise AssertionError("must not call ECR")

    assert utd.check(task, f"{REG}/r", "x", runner=boom) == ([], [])


# ── the CLI, end to end, with a fake aws ─────────────────────────────────────────────────────
def run_cli(tmp_path, task, tag, *, ecr_has_tag=True, container="worker"):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    aws = bindir / "aws"
    aws.write_text("#!/usr/bin/env bash\necho %s\n" % ("sha1" if ecr_has_tag else "None"), encoding="utf-8")
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "new.json"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run([sys.executable, str(SCRIPT), "--container", container, "--tag", tag, "--region", "ap-southeast-1",
                        "--out", str(out)], input=json.dumps(task), capture_output=True, text=True, env=env)
    return r, out


def test_cli_writes_the_rewritten_definition_and_logs_each_container(tmp_path):
    r, out = run_cli(tmp_path, kb_worker_task(), "sha1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert images(json.loads(out.read_text()))["beat"] == f"{REG}/qnsc-kb-worker:sha1"
    assert "beat" in r.stdout and "worker" in r.stdout


def test_cli_refuses_and_writes_nothing_when_the_tag_is_not_in_ecr(tmp_path):
    r, out = run_cli(tmp_path, kb_worker_task(), "sha1", ecr_has_tag=False)
    assert r.returncode == 1
    assert "not in ECR" in r.stdout
    assert not out.exists(), "nothing may be registered from a definition that failed the check"


def test_cli_refuses_a_latest_tag_for_the_deploy_itself(tmp_path):
    r, out = run_cli(tmp_path, kb_worker_task(), "latest")
    assert r.returncode == 1 and not out.exists()


# ── the workflow uses it, for all three services, and checks the worker ──────────────────────
def test_backend_deploy_uses_the_action_for_api_worker_and_migrator_and_verifies_the_worker():
    text = (ROOT / ".github" / "workflows" / "backend-deploy.yml").read_text(encoding="utf-8")
    assert text.count("actions/update-task-definition@v1") == 3
    for name in ("container: api", "container: worker", "container: migrator"):
        assert name in text
    assert "- name: Verify Worker deployment" in text
    assert "aws ecs wait services-stable" in text.split("- name: Verify Worker deployment", 1)[1].split("- name:", 1)[0]
    assert "c['image'].rsplit(':', 1)[0]" not in text, "the single-container inline rewrite must not come back"
