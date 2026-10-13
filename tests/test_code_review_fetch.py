"""The rules download in code-review.yml must say WHY a fetch failed.

It used to be `curl -fsSL ... || echo "rule profile 'x' not found"`: a 429, a 5xx and a dropped
connection all printed "not found" and sent people to check the profile name. Only a 404 means that.
The `download` shell function is read out of the workflow (not copied) and run against a local server.
"""

from __future__ import annotations

import pathlib
import subprocess
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "code-review.yml"


def _download_function() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("          download() {")
    end = text.index("          fetch() {")
    return textwrap.dedent(text[start:end])


@pytest.fixture(scope="module")
def server():
    hits: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            hits[self.path] = hits.get(self.path, 0) + 1
            if self.path == "/ok":
                code = 200
            elif self.path == "/missing":
                code = 404
            elif self.path == "/flaky":
                code = 500 if hits[self.path] < 3 else 200
            else:
                code = 503
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", hits
    httpd.shutdown()


def run(url: str, tmp_path):
    script = f"""
        RULES_REF=v1
        FETCH_RETRY_DELAY=0
        {_download_function()}
        download "{url}" "{tmp_path}/out.json" "rule profile 'x'"
    """
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)


def test_a_file_that_exists_downloads(server, tmp_path):
    base, hits = server
    result = run(f"{base}/ok", tmp_path)
    assert result.returncode == 0
    assert hits["/ok"] == 1


def test_a_404_is_reported_as_not_found_and_not_retried(server, tmp_path):
    base, hits = server
    result = run(f"{base}/missing", tmp_path)
    assert result.returncode == 1
    assert "not found at v1 (HTTP 404" in result.stdout
    assert hits["/missing"] == 1, "a 404 is an answer, not a transient failure"


def test_a_server_error_is_retried_and_then_succeeds(server, tmp_path):
    base, hits = server
    result = run(f"{base}/flaky", tmp_path)
    assert result.returncode == 0
    assert hits["/flaky"] == 3


def test_persistent_failure_is_not_blamed_on_the_profile_name(server, tmp_path):
    base, hits = server
    result = run(f"{base}/down", tmp_path)
    assert result.returncode == 1
    assert "HTTP 503 after 3 attempts" in result.stdout
    assert "not found" not in result.stdout
    assert hits["/down"] == 3


def test_a_refused_connection_reports_http_000(tmp_path):
    result = run("http://127.0.0.1:1/x", tmp_path)
    assert result.returncode == 1
    assert "HTTP 000 after 3 attempts" in result.stdout
    assert "not found" not in result.stdout


def test_the_workflow_no_longer_uses_curl_f_for_the_rules():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "curl -fsSL \"$base/$RULES_REF" not in text
