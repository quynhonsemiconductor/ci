"""Tests for leak-guard — the deterministic public-repo name check.

The cases that matter: every pattern fires on a real leak; the exemptions are
the ONES THE COMMENTS PROMISE (tests for everything but the runtime org
identifiers, lockfiles and licence files entirely, loopback is not an address
pattern); the allowlist's three scopes (text value, literal single file,
key-anchored identifier) suppress exactly what they claim and nothing wider;
the Azure subscription id (tier 1) cannot be suppressed by anything; every
identifier-shaped finding is printed with its value redacted; malformed
runtime inputs exit 2 instead of arming a pattern that can never fire.

Loaded by path: the script ships inside its action and runs standalone.
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
    findings, _ = leak_guard.scan(tmp_path, all_patterns(), ([], []), [])
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
    assert leak_guard.scan(tmp_path, all_patterns()) == ([], 0)


def test_runtime_ids_disarmed_when_not_fed(tmp_path):
    # A test-ish path, so the generic GUID pattern (which still runs) is exempt
    # there too — this isolates exactly the runtime patterns.
    t = tmp_path / "tests"
    t.mkdir()
    (t / "conf.py").write_text(
        f"tenant {FABRICATED_TENANT} subscription {FABRICATED_SUBSCRIPTION}\n")
    patterns = leak_guard.STATIC_PATTERNS + leak_guard.runtime_patterns("", "", "")
    assert leak_guard.scan(tmp_path, patterns) == ([], 0)


def test_runtime_ids_fire_in_tests_and_are_redacted(tmp_path):
    t = tmp_path / "tests"
    t.mkdir()
    (t / "fixtures.py").write_text(
        f"TENANT = '{FABRICATED_TENANT}'\n"
        f"SUB = '{FABRICATED_SUBSCRIPTION}'\n"
        "USER = '3f2504e0-4f89-11d3-9a0c-0305e82c3301'\n"     # fabricated guid: exempt in tests
        "EMAIL = 'user@qnsc.vn'\n"
        "HOST = 'admin.qnsc.vn'\n"
        "ADDR = '10.0.0.1'\n")
    findings, _ = leak_guard.scan(tmp_path, all_patterns())
    # The org's own identifiers fire even in a fixture; fabricated props do not.
    # Every identifier finding is printed WITHOUT its value.
    assert findings == [
        "tests/fixtures.py:1: [entra-tenant] (redacted)",
        "tests/fixtures.py:2: [azure-subscription] (redacted)",
    ]


def test_identifier_findings_are_redacted_even_disarmed(tmp_path):
    # With NO runtime inputs, the static guid pattern still reports a GUID-like
    # value — and must not echo it: a disarmed tier-1 input must not leak via
    # the generic pattern's report.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "conf.txt").write_text(f"id = {FABRICATED_SUBSCRIPTION}\n")
    findings, _ = leak_guard.scan(tmp_path, leak_guard.STATIC_PATTERNS)
    assert findings == ["src/conf.txt:1: [guid] (redacted)"]


@pytest.mark.parametrize("name", ["pnpm-lock.yaml", "go.sum", "LICENSE", "vendor.min.js"])
def test_machine_written_files_skipped(tmp_path, name):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / name).write_text(
        f"admin.qnsc.vn 10.0.0.1 {FABRICATED_TENANT} {FABRICATED_SUBSCRIPTION}\n")
    assert leak_guard.scan(tmp_path, all_patterns()) == ([], 0)


def test_binary_files_skipped(tmp_path):
    (tmp_path / "img.bin").write_bytes(b"admin.qnsc.vn\x00\x01\x02")
    assert leak_guard.scan(tmp_path, all_patterns()) == ([], 0)


def test_text_and_literal_file_entries(tmp_path):
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "vpc.tf").write_text('cidr = "10.0.0.0/16"\nendpoint = "admin.qnsc.vn"\n')  # noqa: E501
    (tmp_path / "live" / "other.tf").write_text('endpoint = "admin.qnsc.vn"\n')
    values, paths, keys = load_allowlist_from_lines([
        r"10\.0\.0\.0",        # this address is intentionally public — by TEXT
        "live/vpc.tf",         # ONE literal file
    ])
    findings, suppressed = leak_guard.scan(tmp_path, all_patterns(), (values, paths), keys)
    # vpc.tf: both findings suppressed (text + file). other.tf: the hostname in
    # a file that is NOT named is still a finding — literal means literal.
    assert findings == ["live/other.tf:1: [qnsc-hostname] admin.qnsc.vn"]
    assert suppressed == 2


def test_key_entry_scopes_identifier_to_the_keys_value(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.yaml").write_text(
        f"tenantId: {FABRICATED_TENANT}\n"                        # suppressed: value of tenantId
        'ENTRA_CLIENT_ID="3f2504e0-4f89-11d3-9a0c-0305e82c3301"\n'  # suppressed: = form, quoted
        f"see tenantId docs {FABRICATED_TENANT} for details\n"    # NOT suppressed: prose, not a value
        "someOtherGuid: 3f2504e0-4f89-11d3-9a0c-0305e82c3301\n"   # NOT suppressed: no key entry
        f"host: admin.qnsc.vn tenantId: {FABRICATED_TENANT}\n")   # hostname never key-scoped
    # [A-Z_]*CLIENT_ID, not bare CLIENT_ID: the left anchor means an entry
    # names the WHOLE key, and ENTRA_CLIENT_ID is a different key from
    # CLIENT_ID (the suffix test below proves the anchor).
    values, paths, keys = load_allowlist_from_lines(
        ["key:tenantId", "key:[A-Z_]*CLIENT_ID"])
    findings, suppressed = leak_guard.scan(tmp_path, all_patterns(), (values, paths), keys)
    assert findings == [
        "src/conf.yaml:3: [entra-tenant] (redacted)",
        "src/conf.yaml:4: [guid] (redacted)",
        "src/conf.yaml:5: [qnsc-hostname] admin.qnsc.vn",
    ]
    # Per pattern-match: guid AND tenant on line 1, guid on line 2, tenant AND
    # guid on line 5 — five suppressions, three findings.
    assert suppressed == 5


@pytest.mark.parametrize("bad", [
    "^rendered/", "values/", "live/*.tf", "charts/.*\\.yaml", "a|b/c.txt",
])
def test_directory_or_pattern_path_entries_are_refused(tmp_path, bad):
    allow = tmp_path / "allow.txt"
    allow.write_text(bad + "\n")
    with pytest.raises(SystemExit) as exc:
        leak_guard.load_allowlist(allow)
    assert exc.value.code == 2


@pytest.mark.parametrize("bad", ["key:", "key:.", "key:.*"])
def test_empty_or_wildcard_key_entries_are_refused(tmp_path, bad):
    allow = tmp_path / "allow.txt"
    allow.write_text(bad + "\n")
    with pytest.raises(SystemExit) as exc:
        leak_guard.load_allowlist(allow)
    assert exc.value.code == 2


def test_literal_path_entries_allow_dots_in_names(tmp_path):
    values, paths, keys = load_allowlist_from_lines(["live/.gitleaks.toml"])
    assert paths == ["live/.gitleaks.toml"] and values == [] and keys == []


def test_azure_subscription_is_unsuppressible(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.yaml").write_text(f"subscriptionId: {FABRICATED_SUBSCRIPTION}\n")
    # A key entry that WOULD match and the file itself by path — tier 1 ignores
    # both. (A text entry with the literal is refused at load: it matches a GUID.)
    values, paths, keys = load_allowlist_from_lines([
        "key:subscriptionId",
        "src/conf.yaml",
    ])
    findings, suppressed = leak_guard.scan(tmp_path, all_patterns(), (values, paths), keys)
    assert findings == ["src/conf.yaml:1: [azure-subscription] (redacted)"]
    # The tier-1 finding is reported once, unsuppressed; the generic guid
    # pattern's duplicate of the SAME value is key-suppressed — one report,
    # not two, and the tier-1 report itself stands.
    assert suppressed == 1


@pytest.mark.parametrize("broad", [".*", "[0-9a-f-]+", "^3f2504e0-[0-9a-f-]+$"])
def test_guid_matching_text_entries_are_refused(tmp_path, broad):
    # Identifier findings are key-scoped only; a text regex broad enough to
    # match a GUID is a key scope wearing a disguise, and is refused at load.
    allow = tmp_path / "allow.txt"
    allow.write_text(broad + "\n")
    with pytest.raises(SystemExit) as exc:
        leak_guard.load_allowlist(allow)
    assert exc.value.code == 2


def test_identifier_findings_are_key_scoped_only(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.yaml").write_text(f"tenantId: {FABRICATED_TENANT}\n")
    # The file itself by path — a perfectly valid entry — still does not
    # suppress the identifier: only a key entry may.
    values, paths, keys = load_allowlist_from_lines(["src/conf.yaml"])
    findings, _ = leak_guard.scan(tmp_path, all_patterns(), (values, paths), keys)
    assert findings == ["src/conf.yaml:1: [entra-tenant] (redacted)"]


def test_key_alternation_binds_as_the_key(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.yaml").write_text(
        f"tenantId: {FABRICATED_TENANT}\n"
        "clientId=3f2504e0-4f89-11d3-9a0c-0305e82c3301\n")
    values, paths, keys = load_allowlist_from_lines(["key:tenantId|clientId"])
    findings, suppressed = leak_guard.scan(tmp_path, all_patterns(), (values, paths), keys)
    # Without the (?:...) wrap the alternation would bind as `tenantId` OR
    # `clientId\s*[:=]...` and the `=` form would not match. (3 suppressions:
    # tenant + guid on line 1, guid on line 2.)
    assert findings == [] and suppressed == 3


def test_key_entries_do_not_match_a_keys_suffix(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.yaml").write_text(
        f"clientId: {FABRICATED_TENANT}\n"                          # tail of clientId: no match
        "Id: 3f2504e0-4f89-11d3-9a0c-0305e82c3301\n")               # standalone Id: match
    values, paths, keys = load_allowlist_from_lines(["key:Id"])
    findings, suppressed = leak_guard.scan(tmp_path, all_patterns(), (values, paths), keys)
    assert findings == ["src/conf.yaml:1: [entra-tenant] (redacted)"]


def test_cli_exit_codes_redaction_and_validation(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text(
        f"host admin.qnsc.vn tenant {FABRICATED_TENANT} "
        f"subscription {FABRICATED_SUBSCRIPTION}\n")
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
    # Identifier values are the point of the check: never echoed back, not even
    # in the report that says they were found — including the generic guid.
    for lit in (FABRICATED_TENANT, FABRICATED_SUBSCRIPTION, FABRICATED_AWS):
        assert lit not in r.stdout
    assert "[entra-tenant] (redacted)" in r.stdout
    assert "[azure-subscription] (redacted)" in r.stdout
    r = run("--report-only")
    assert r.returncode == 0 and "patterns armed:" in r.stdout
    # The hostname is suppressible by text; identifier findings are
    # key-scoped only (and a GUID-matching text entry would be refused at
    # load), so tenant AND subscription still fail the run.
    allow = tmp_path / "allow.txt"
    allow.write_text("admin\\.qnsc\\.vn\n")
    r = run("--allowlist", str(allow))
    assert r.returncode == 1
    assert "[entra-tenant] (redacted)" in r.stdout
    assert "[azure-subscription] (redacted)" in r.stdout
    r = run("--allowlist", str(tmp_path / "nope.txt"))
    assert r.returncode == 2 and "not found" in r.stdout


def test_malformed_runtime_inputs_exit_2(tmp_path):
    for flag, value, expected in [
        ("--entra-tenant-id", "not-a-guid", 2),
        ("--azure-subscription-id", "still not", 2),
        ("--entra-tenant-id", f"  {FABRICATED_TENANT} ", 0),  # stripped, valid
        ("--aws-account-id", "12x456789012", 2),
    ]:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(tmp_path), flag, value],
            capture_output=True, text=True)
        assert r.returncode == expected, (flag, value, r.stdout, r.stderr)


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
