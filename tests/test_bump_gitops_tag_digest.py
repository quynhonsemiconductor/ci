"""The 'Bump' step of actions/bump-gitops-tag/action.yml, run for real with a stand-in `yq`.

The stand-in understands only the three expressions the step uses (set tag, set digest, del digest) and edits the
YAML with PyYAML, so these tests cover the step's shell logic: which expression runs for which input, validation,
and the changed output. They do not prove real yq's rendering. The case that must never regress: a tag-only bump
deletes a stale digest (the chart pins the digest and ignores the tag, so a stale one keeps the old image).
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys

import pytest
import yaml

ACTION = pathlib.Path(__file__).resolve().parents[1] / "actions" / "bump-gitops-tag" / "action.yml"
D1 = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("git") is None, reason="jq and git are needed by the step under test"
)

YQ_STUB = """
import os, sys, yaml
expr, path = sys.argv[-2], sys.argv[-1]
doc = yaml.safe_load(open(path)) or {}
img = doc["services"][os.environ["svc"]]["image"]
if expr == ".services[strenv(svc)].image.tag = strenv(TAG)":
    img["tag"] = os.environ["TAG"]
elif expr == ".services[strenv(svc)].image.digest = strenv(digest)":
    img["digest"] = os.environ["digest"]
elif expr == "del(.services[strenv(svc)].image.digest)":
    img.pop("digest", None)
else:
    sys.exit("unexpected yq expression: " + expr)
yaml.safe_dump(doc, open(path, "w"), sort_keys=False)
"""


def step_script() -> str:
    doc = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    return next(s for s in doc["runs"]["steps"] if s.get("id") == "bump")["run"]


def run_bump(tmp_path, values: dict, *, tag="v1.2.3", digests=None, services="api worker"):
    work = tmp_path / "gitops"
    (work / "values" / "rova").mkdir(parents=True)
    file = work / "values" / "rova" / "tags.prod.yaml"
    file.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    yq = bindir / "yq"
    yq.write_text(f"#!{sys.executable}\n" + YQ_STUB, encoding="utf-8")
    yq.chmod(yq.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "output"
    out.touch()
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out), "PRODUCT": "rova", "ENV": "prod",
        "SERVICES": services, "TAG": tag, "DIGESTS": "" if digests is None else json.dumps(digests),
        "HOME": os.environ["HOME"],
    }
    result = subprocess.run(["bash", "-c", step_script()], cwd=work, capture_output=True, text=True, env=env, timeout=30)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return result, outputs, yaml.safe_load(file.read_text(encoding="utf-8"))


def values(**per_service):
    return {"services": {name: {"image": image} for name, image in per_service.items()}}


def test_tag_only_bump_deletes_a_stale_digest(tmp_path):
    result, outputs, doc = run_bump(
        tmp_path, values(api={"tag": "sha-old", "digest": D1}, worker={"tag": "sha-old", "digest": D1})
    )
    assert result.returncode == 0, result.stderr
    assert doc["services"]["api"]["image"] == {"tag": "v1.2.3"}
    assert doc["services"]["worker"]["image"] == {"tag": "v1.2.3"}
    assert outputs["changed"] == "true"


def test_tag_only_bump_without_a_digest_still_works(tmp_path):
    result, outputs, doc = run_bump(tmp_path, values(api={"tag": "sha-old"}, worker={"tag": "sha-old"}))
    assert result.returncode == 0, result.stderr
    assert doc["services"]["api"]["image"] == {"tag": "v1.2.3"}
    assert outputs["changed"] == "true"


def test_digests_write_tag_and_digest_per_service(tmp_path):
    result, outputs, doc = run_bump(
        tmp_path,
        values(api={"tag": "sha-old", "digest": D1}, worker={"tag": "sha-old"}),
        digests={"api": D2, "worker": D2},
    )
    assert result.returncode == 0, result.stderr
    assert doc["services"]["api"]["image"] == {"tag": "v1.2.3", "digest": D2}
    assert doc["services"]["worker"]["image"] == {"tag": "v1.2.3", "digest": D2}
    assert outputs["changed"] == "true"


def test_same_tag_and_digest_is_not_a_deploy(tmp_path):
    img = {"tag": "v1.2.3", "digest": D1}
    result, outputs, _ = run_bump(tmp_path, values(api=dict(img), worker=dict(img)), digests={"api": D1, "worker": D1})
    assert result.returncode == 0, result.stderr
    assert outputs["changed"] == "false"


def test_missing_digest_entry_fails(tmp_path):
    result, _, _ = run_bump(tmp_path, values(api={"tag": "x"}, worker={"tag": "x"}), digests={"api": D1})
    assert result.returncode != 0
    assert "digests has no entry for worker" in result.stdout + result.stderr


@pytest.mark.parametrize("bad", ["sha256:short", "sha256:" + "A" * 64, "latest"])
def test_malformed_digest_fails(tmp_path, bad):
    result, _, doc = run_bump(tmp_path, values(api={"tag": "x"}, worker={"tag": "x"}), digests={"api": bad, "worker": D1})
    assert result.returncode != 0
    assert "bad digest for api" in result.stdout + result.stderr
