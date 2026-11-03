"""actions/release-retag/retag.sh, run for real with stand-ins for `crane` and `gh`.

The stand-ins record every invocation, so these cover the order that matters: verify every found digest
BEFORE tagging any of them (a release tag on an unverified digest must never exist), skipping a service the
product does not ship, and the digest map the action hands to the prod bump.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import pathlib

import yaml

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "actions" / "release-retag" / "retag.sh"
WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-retag.yml"
SHA = "a" * 40
D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64

CRANE_STUB = f"""#!{sys.executable}
import json, os, sys
tagged = json.loads(os.environ.get("STUB_CRANE_TAGS", "{{}}"))
errors = json.loads(os.environ.get("STUB_CRANE_ERRORS", "{{}}"))
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as f:
    f.write("crane " + " ".join(args) + "\\n")
if args[0] == "digest":
    ref = args[1]
    if ref in errors:
        print(errors[ref], file=sys.stderr)
        sys.exit(1)
    digest = tagged.get(ref)
    if not digest:
        print("MANIFEST_UNKNOWN: manifest unknown; GET https://ghcr.io/v2/x/manifests/y: 404", file=sys.stderr)
        sys.exit(1)
    print(digest)
elif args[0] == "tag":
    pass
else:
    sys.exit("unexpected crane command: " + args[0])
"""

GH_STUB = f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as f:
    f.write("gh " + " ".join(args) + "\\n")
if args[0] != "attestation":
    sys.exit("unexpected gh command: " + args[0])
bad = json.loads(os.environ.get("STUB_GH_FAIL", "[]"))
ref = next(a for a in args if a.startswith("oci://"))
# The real verify only accepts an attestation whose source ref is the caller's
# main branch; the stub enforces the flag so a dropped --source-ref fails here.
if "--source-ref" not in args or args[args.index("--source-ref") + 1] != "refs/heads/main":
    print("attestation source ref is not refs/heads/main", file=sys.stderr)
    sys.exit(1)
if any(formatted in ref for formatted in bad):
    print("no attestations found", file=sys.stderr)
    sys.exit(1)
"""


def run(tmp_path, *, tags, gh_fail=(), crane_errors=None, tag="v1.2.3", commit=SHA,
        services="api", product="rova", source="quynhonsemiconductor/rova"):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("crane", CRANE_STUB), ("gh", GH_STUB)):
        path = bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    calls = tmp_path / "calls"
    calls.touch()
    out = tmp_path / "output"
    out.touch()
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": os.environ["HOME"],
        "GITHUB_OUTPUT": str(out),
        "STUB_CALLS": str(calls),
        "STUB_CRANE_TAGS": json.dumps(tags),
        "STUB_GH_FAIL": json.dumps(list(gh_fail)),
        "STUB_CRANE_ERRORS": json.dumps(crane_errors or {}),
        "PRODUCT": product,
        "RELEASE_TAG": tag,
        "COMMIT": commit,
        "SERVICES": services,
        "SOURCE_REPOSITORY": source,
        "SIGNER_WORKFLOW": "quynhonsemiconductor/ci/.github/workflows/ghcr-publish.yml",
        "GH_TOKEN": "test-token",
    }
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return result, outputs, calls.read_text().splitlines()


def tags_map(**per_service):
    return {f"ghcr.io/quynhonsemiconductor/rova-{svc}:sha-{SHA[:12]}": digest for svc, digest in per_service.items()}


def test_tags_the_published_digests_and_returns_the_map(tmp_path):
    result, outputs, calls = run(tmp_path, tags=tags_map(api=D1, worker=D2), services="api worker")
    assert result.returncode == 0, result.stderr
    assert json.loads(outputs["digests"]) == {"api": D1, "worker": D2}
    assert outputs["services"] == "api worker"
    gh_calls = [call for call in calls if call.startswith("gh ")]
    tag_calls = [call for call in calls if call.startswith("crane tag ")]
    assert "gh attestation verify oci://ghcr.io/quynhonsemiconductor/rova-api@" + D1 in gh_calls[0]
    assert "--source-digest " + SHA in gh_calls[0]
    assert len(gh_calls) == 2
    assert tag_calls == [
        f"crane tag ghcr.io/quynhonsemiconductor/rova-api@{D1} v1.2.3",
        f"crane tag ghcr.io/quynhonsemiconductor/rova-worker@{D2} v1.2.3",
    ]


def test_a_listed_service_with_no_image_fails_before_any_tag(tmp_path):
    result, _, calls = run(tmp_path, tags=tags_map(api=D1), services="api worker")
    assert result.returncode != 0
    assert "Refusing a partial release" in result.stdout + result.stderr
    # attestation of the services before the missing one may already have run;
    # the guarantee is that NO tag was written.
    assert not any(call.startswith("crane tag") for call in calls)


def test_nothing_tagged_when_a_later_attestation_fails(tmp_path):
    result, _, calls = run(tmp_path, tags=tags_map(api=D1, worker=D2), services="api worker", gh_fail=[D2])
    assert result.returncode != 0
    assert "no valid build attestation" in result.stdout + result.stderr
    assert not any(call.startswith("crane tag") for call in calls)


def test_no_image_for_the_commit_fails_loudly(tmp_path):
    result, _, _ = run(tmp_path, tags={})
    assert result.returncode != 0
    assert "is not published for this commit" in result.stdout + result.stderr


@pytest.mark.parametrize("bad", ["latest", "sha-abc123", "1.2.3"])
def test_refuses_a_non_version_release_tag(tmp_path, bad):
    result, _, calls = run(tmp_path, tags=tags_map(api=D1), tag=bad)
    assert result.returncode != 0
    assert "expected a release tag" in result.stdout + result.stderr
    assert calls == []


def test_refuses_a_short_commit(tmp_path):
    result, _, _ = run(tmp_path, tags=tags_map(api=D1), commit=SHA[:12])
    assert result.returncode != 0
    assert "full 40-character sha" in result.stdout + result.stderr


def test_verification_targets_the_caller_repository(tmp_path):
    result, _, calls = run(tmp_path, tags=tags_map(api=D1), source="quynhonsemiconductor/other")
    assert result.returncode == 0, result.stderr
    assert any("--repo quynhonsemiconductor/other" in call for call in calls if call.startswith("gh "))


def test_workflow_inlines_the_testable_script_verbatim():
    """The reusable workflow cannot `uses:` this action at a ref that does not exist yet, so it inlines it.
    This fails the moment one copy is edited without the other."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(s for s in doc["jobs"]["retag"]["steps"] if s.get("id") == "retag")
    assert step["run"].strip() == SCRIPT.read_text(encoding="utf-8").strip()


def test_an_auth_error_does_not_look_like_a_missing_image(tmp_path):
    ref = f"ghcr.io/quynhonsemiconductor/rova-api:sha-{SHA[:12]}"
    result, _, calls = run(
        tmp_path, tags=tags_map(api=D1), crane_errors={ref: "GET https://ghcr.io/v2/: denied: denied"},
    )
    assert result.returncode != 0
    assert "not a missing manifest" in result.stdout + result.stderr
    assert not any(call.startswith("gh attestation") for call in calls)
    assert not any(call.startswith("crane tag") for call in calls)


def test_a_5xx_or_rate_limit_does_not_look_like_a_missing_image(tmp_path):
    ref = f"ghcr.io/quynhonsemiconductor/rova-api:sha-{SHA[:12]}"
    result, _, _ = run(tmp_path, tags=tags_map(api=D1), crane_errors={ref: "unexpected status code 503"})
    assert result.returncode != 0
    assert "could not read" in result.stdout + result.stderr


def test_an_existing_release_tag_at_the_same_digest_is_a_noop(tmp_path):
    tags = tags_map(api=D1)
    tags[f"ghcr.io/quynhonsemiconductor/rova-api:v1.2.3"] = D1
    result, outputs, calls = run(tmp_path, tags=tags)
    assert result.returncode == 0, result.stderr
    assert "already at" in result.stdout
    assert not any(call.startswith("crane tag") for call in calls)
    assert json.loads(outputs["digests"]) == {"api": D1}


def test_an_existing_release_tag_at_another_digest_is_refused(tmp_path):
    tags = tags_map(api=D1)
    tags["ghcr.io/quynhonsemiconductor/rova-api:v1.2.3"] = D2
    result, _, calls = run(tmp_path, tags=tags)
    assert result.returncode != 0
    assert "Refusing to move a published release tag" in result.stdout + result.stderr
    assert not any(call.startswith("crane tag") for call in calls)


def test_attestation_is_verified_against_main(tmp_path):
    result, _, calls = run(tmp_path, tags=tags_map(api=D1))
    assert result.returncode == 0, result.stderr
    gh_calls = [call for call in calls if call.startswith("gh attestation")]
    assert gh_calls and "--source-ref refs/heads/main" in gh_calls[0]


def test_an_auth_error_on_one_service_fails_the_whole_run(tmp_path):
    ref = f"ghcr.io/quynhonsemiconductor/rova-api:sha-{SHA[:12]}"
    result, _, calls = run(
        tmp_path, tags=tags_map(api=D1, worker=D2), services="api worker", crane_errors={ref: "denied: denied"},
    )
    assert result.returncode != 0
    assert "not a missing manifest" in result.stdout + result.stderr
    assert not any(call.startswith("crane tag") for call in calls)


def test_a_non_404_error_on_the_release_tag_lookup_never_tags(tmp_path):
    rel = "ghcr.io/quynhonsemiconductor/rova-api:v1.2.3"
    result, _, calls = run(
        tmp_path, tags=tags_map(api=D1), crane_errors={rel: "unexpected status code 503"},
    )
    assert result.returncode != 0
    assert "could not read" in result.stdout + result.stderr
    assert not any(call.startswith("crane tag") for call in calls)


def test_a_refusal_on_worker_after_api_is_ok_tags_nothing(tmp_path):
    tags = tags_map(api=D1, worker=D2)
    tags["ghcr.io/quynhonsemiconductor/rova-worker:v1.2.3"] = "sha256:" + "9" * 64
    result, _, calls = run(tmp_path, tags=tags, services="api worker")
    assert result.returncode != 0
    assert "Refusing to move a published release tag" in result.stdout + result.stderr
    assert not any(call.startswith("crane tag") for call in calls)
