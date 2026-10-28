"""Tests for leak-guard — the deterministic public-repo name check.

The cases that matter: every pattern fires on a real leak, the exemptions are the
ONES THE COMMENTS PROMISE (tests for everything but the runtime org identifiers,
lockfiles and licence files entirely, loopback is not an address pattern at all),
the allowlist suppresses by text and by path, the runtime identifiers are fed in
— never baked into this file, which is public — and their findings are REDACTED
in the report. Exit 1 only for unsuppressed findings.

Loaded by path: the script ships inside its action and runs as a standalone file.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "actions" / "leak-guard" / "leak_guard.py"
spec = importlib.util.spec_from_file_location("leak_guard", SCRIPT)
leak_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leak_guard)

# Fabricated stand-ins for the org identifiers: the real ones are exactly what
# this check exists to keep out of public repos, so they appear nowhere here —
# not even in its tests. Same shapes (GUID, 12-digit account) as the real ones.
FABRICATED_TENANT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
FABRICATED_SUBSCRIPTION = "77777777-8888-4999-aaaa-bbbbbbbbbbbb"
FABRICATED_AWS = "999999999999"


def all_patterns():
    return leak_guard.STATIC_PATTERNS + leak_guard.runtime_patterns(
        FABRICATED_TENANT, FABRICATED_SUBSCRIPTION, FABRICATED_AWS)


@pytest.mark.parametrize("text,pattern_id", [
    ("host = admin.qnsc.vn", "qnsc-hostname"),
    ("url https://doors.qnsc.vn/api", "qnsc-hostname"),
    ("contact ops@qnsc.vn", "qnsc-email"),
    ("from: noreply-rova-dev@qnsc.vn", "qnsc-email"),
    (f"tenant {FABRICATED_TENANT}", "entra-tenant"),
    (f"subscription: {FABRICATED_SUBSCRIPTION}", "azure-subscription"),
    ("id 3f2504e0-4f89-11d3-9a0c-0305e82c3301", "guid"),
    (f"account {FABRICATED_AWS}", "aws-account"),
    ("node 10.1.2.3", "private-ipv4"),
    ("cidr 192.168.0.0/16", "private-ipv4"),
    ("peer 172.20.4.11", "private-ipv4"),
    ("meta 169.254.169.254", "private-ipv4"),
    ("cgnat 100.64.0.1", "private-ipv4"),
    ("addr fd00:db8::1", "private-ipv6"),
    ("link fe80::1%eth0", "private-ipv6"),
])
def test_every_pattern_fires(tmp_path, text, pattern_id):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "conf.txt").write_text(text + "\n")
    findings, _ = leak_guard.scan(tmp_path, all_patterns(), [])
    assert any(f"[{pattern_id}]" in f for f in findings), findings


@pytest.mark.parametrize("text", [
    "see https://qnsc.vn",              # registrable domain alone, no internal host
    "maintainer someone@example.org",   # generic addresses are not a pattern (dropped: noise)
    "placeholder user@company.com in a form",
    "uses: org/ci/.github/workflows/security.yml@v1.23.1",
    "loopback 127.0.0.1 and ::1",       # local-dev convention, never a pattern
    "public 8.8.8.8 and 203.0.113.9",   # non-private addresses
    "version 1.2.3.4",                  # dotted quad that is not an address pattern match
])
def test_not_a_leak(tmp_path, text):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "conf.txt").write_text(text + "\n")
    assert leak_guard.scan(tmp_path, all_patterns(), []) == ([], 0)


def test_azure_subscription_disarmed_when_not_fed(tmp_path):
    t = tmp_path / "src"
    t.mkdir()
    (t / "conf.txt").write_text(f"subscription = '{FABRICATED_SUBSCRIPTION}'\n")
    patterns = leak_guard.STATIC_PATTERNS + leak_guard.runtime_patterns("", "", "")
    # Unarmed runtime patterns still leave the generic GUID pattern (outside
    # tests): the line IS reported, but as a guid — never unredacted as the
    # subscription itself.
    findings, _ = leak_guard.scan(tmp_path, patterns, [], [])
    assert findings == ["src/conf.txt:1: [guid] " + FABRICATED_SUBSCRIPTION]


def test_azure_subscription_is_tier_1_redacted_everywhere(tmp_path):
    # Even in a test-ish path, where the generic GUID pattern is exempt: the
    # subscription id is tier 1 and fires everywhere, redacted.
    t = tmp_path / "tests"
    t.mkdir()
    (t / "fixtures.py").write_text(f"SUB = '{FABRICATED_SUBSCRIPTION}'\n")
    findings, _ = leak_guard.scan(tmp_path, all_patterns(), [], [])
    assert findings == ["tests/fixtures.py:1: [azure-subscription] (redacted)"]


def load_allowlist_from_lines(lines):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(lines) + "\n")
        name = fh.name
    try:
        return leak_guard.load_allowlist(pathlib.Path(name))
    finally:
        import os
        os.unlink(name)


def test_key_entry_scopes_identifier_to_its_line(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.yaml").write_text(
        f"tenantId: {FABRICATED_TENANT}\n"
        f"appClientId: {FABRICATED_SUBSCRIPTION}\n"
        "someOtherGuid: 3f2504e0-4f89-11d3-9a0c-0305e82c3301\n"
        f"host: admin.qnsc.vn tenantId: {FABRICATED_TENANT}\n")
    regexes, keys = load_allowlist_from_lines(
        ["key:tenantId", "key:[A-Z_]*ClientId"])
    findings, suppressed = leak_guard.scan(tmp_path, all_patterns(), regexes, keys)
    # Line 1 and 2: the key is on the line -> suppressed. Line 3: no key ->
    # reported. Line 4: a hostname is NOT identifier-shaped -> still reported,
    # even though a key sits on the same line.
    assert findings == [
        "src/conf.yaml:3: [guid] 3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        "src/conf.yaml:4: [qnsc-hostname] admin.qnsc.vn",
    ]


def test_runtime_ids_disarmed_when_not_fed(tmp_path):
    # A test-ish path, so the generic GUID pattern (which still runs) is exempt
    # there too — this isolates exactly the two runtime patterns.
    t = tmp_path / "tests"
    t.mkdir()
    (t / "conf.py").write_text(f"tenant {FABRICATED_TENANT} account {FABRICATED_AWS}\n")
    # No runtime inputs -> only static patterns -> these two lines are not findings.
    assert leak_guard.scan(tmp_path, leak_guard.STATIC_PATTERNS, []) == ([], 0)


def test_tests_exempt_everything_but_runtime_identifiers(tmp_path):
    t = tmp_path / "tests"
    t.mkdir()
    (t / "fixtures.py").write_text(
        f"TENANT = '{FABRICATED_TENANT}'\n"
        f"ACCOUNT = '{FABRICATED_AWS}'\n"
        "USER = '3f2504e0-4f89-11d3-9a0c-0305e82c3301'\n"
        "EMAIL = 'user@qnsc.vn'\n"
        "HOST = 'admin.qnsc.vn'\n"
        "ADDR = '10.0.0.1'\n")
    findings, _ = leak_guard.scan(tmp_path, all_patterns(), [])
    ids = {f.split("[")[1].split("]")[0] for f in findings}
    # The org's own identifiers fire even in a fixture; fabricated props do not.
    assert ids == {"entra-tenant", "aws-account"}


@pytest.mark.parametrize("name", ["pnpm-lock.yaml", "go.sum", "LICENSE", "vendor.min.js"])
def test_machine_written_files_skipped(tmp_path, name):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / name).write_text(
        f"admin.qnsc.vn 10.0.0.1 {FABRICATED_TENANT} {FABRICATED_AWS}\n")
    assert leak_guard.scan(tmp_path, all_patterns(), []) == ([], 0)


def test_binary_files_skipped(tmp_path):
    (tmp_path / "img.bin").write_bytes(b"admin.qnsc.vn\x00\x01\x02")
    assert leak_guard.scan(tmp_path, all_patterns(), []) == ([], 0)


def test_allowlist_suppresses_by_text_and_single_file_path(tmp_path):
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "vpc.tf").write_text("cidr = \"10.0.0.0/16\"\nendpoint = \"admin.qnsc.vn\"\n")
    compiled, keys = load_allowlist_from_lines(
        [r"10\.0\.0\.0/16",          # this CIDR is intentionally public
         r"^live/vpc\.tf$"])           # ONE file, not a directory
    findings, suppressed = leak_guard.scan(tmp_path, all_patterns(), compiled, keys)
    assert findings == [] and suppressed == 2  # the cidr by text, the hostname by file path


def test_directory_entries_are_refused(tmp_path):
    for bad in ["^rendered/", "values/", "key:foo/"]:
        allow = tmp_path / "allow.txt"
        allow.write_text(bad + "\n")
        with pytest.raises(SystemExit) as exc:
            leak_guard.load_allowlist(allow)
        assert exc.value.code == 2


def test_cli_exit_codes_and_redaction(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text(
        f"host admin.qnsc.vn tenant {FABRICATED_TENANT} "
        f"subscription {FABRICATED_SUBSCRIPTION} account {FABRICATED_AWS}\n")
    (tmp_path / ".github").mkdir()

    def run(*extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(tmp_path),
             "--entra-tenant-id", FABRICATED_TENANT,
             "--azure-subscription-id", FABRICATED_SUBSCRIPTION,
             "--aws-account-id", FABRICATED_AWS,
             *extra],
            capture_output=True, text=True)

    r = run()
    assert r.returncode == 1 and "[qnsc-hostname]" in r.stdout
    # The runtime identifiers are the point of the check: they must not be
    # echoed back, not even in the report that says they were found.
    for lit in (FABRICATED_TENANT, FABRICATED_SUBSCRIPTION, FABRICATED_AWS):
        assert lit not in r.stdout
    assert "[entra-tenant] (redacted)" in r.stdout
    assert "[azure-subscription] (redacted)" in r.stdout
    r = run("--report-only")
    assert r.returncode == 0 and "patterns armed:" in r.stdout
    allow = tmp_path / "allow.txt"
    # The allowlist matches the FINDING'S TEXT even when the report redacts it —
    # exempting a runtime identifier is done by its value, not by "(redacted)".
    allow.write_text(
        f"admin\\.qnsc\\.vn\n{FABRICATED_TENANT}\n{FABRICATED_SUBSCRIPTION}\n{FABRICATED_AWS}\n")
    r = run("--allowlist", str(allow))
    # (The allowlist file itself sits inside the scanned root, so its own lines
    # add suppressed hits — assert the outcome, not the count.)
    assert r.returncode == 0 and "0 finding(s)" in r.stdout
    r = run("--allowlist", str(tmp_path / "nope.txt"))
    assert r.returncode == 2 and "not found" in r.stdout


def test_allowlist_regex_error_is_not_silent(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("([\n")
    with pytest.raises(SystemExit) as exc:
        leak_guard.load_allowlist(bad)
    assert exc.value.code == 2


def test_standard_library_only():
    source = SCRIPT.read_text()
    imports = {m.split()[1].split(".")[0] for m in source.splitlines()
               if m.startswith(("import ", "from ")) and "__future__" not in m}
    assert imports <= {"argparse", "os", "re", "sys", "pathlib"}


def test_action_metadata_parses():
    """actionlint checks workflows, not action.yml — an unquoted `key: value` in a description
    broke this file once (on pr-size) and nothing else would have noticed before a caller ran it."""
    import yaml
    action = yaml.safe_load((SCRIPT.parent / "action.yml").read_text())
    assert set(action["inputs"]) == {"entra-tenant-id", "azure-subscription-id",
                                     "aws-account-id", "allowlist", "report-only"}
    # The org identifiers must not be defaulted into the public action metadata.
    assert action["inputs"]["entra-tenant-id"]["default"] == ""
    assert action["inputs"]["azure-subscription-id"]["default"] == ""
    assert action["inputs"]["aws-account-id"]["default"] == ""
    assert action["inputs"]["allowlist"]["default"] == ".github/leak-guard-allowlist.txt"
    assert action["runs"]["using"] == "composite"
