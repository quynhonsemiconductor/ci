#!/usr/bin/env python3
"""Deterministic public-repo leak guard.

These repositories are public on purpose; only product-docs holds internal detail.
That boundary is enforced by pattern, not by memory: a hostname, a tenant GUID, a
private address or an internal email that lands in a public tree fails this check
the moment it is pushed, before review rather than after someone notices.

Deterministic means NO model, NO network, NO judgement: plain regular expressions
over the tracked tree, one allowlist file per repository for names that are
intentionally public. Every pattern below is a proposal the SA reviews — the list
lives in this file and in the PR that adds it, not in a config far from the code.

The two identifiers that would themselves be leaks if written here — the Entra
tenant GUID and the AWS account number — are NOT in this file and NOT in the
action's defaults. Callers feed them at runtime from org variables
(`vars.ENTRA_TENANT_ID`, `vars.AWS_ACCOUNT_ID`); an empty input disarms that one
pattern (the summary names which patterns ran), and a finding prints the file and
line with the VALUE REDACTED, because a public repo's Actions log is public too.

What it deliberately does NOT do: scan git history (gitleaks already does, for
secrets — this check is about the CURRENT tree), and guess at "suspicious" text
(anything not matched is fine, which is why the pattern list is short and exact).

Exit codes: 0 clean (or every finding allowlisted), 1 findings, 2 bad invocation.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Files whose CONTENT is written by tools or upstream, not by us: a lockfile's
# hashes and resolved URLs, a minified bundle, an upstream licence's contact
# line. Nothing anyone chose to write belongs in a leak report.
SKIPPED_BASENAMES = {
    'pnpm-lock.yaml', 'package-lock.json', 'yarn.lock', 'npm-shrinkwrap.json',
    'poetry.lock', 'Pipfile.lock', 'uv.lock', 'composer.lock', 'Gemfile.lock',
    'Cargo.lock', 'flake.lock', 'bun.lock', 'go.sum',
    'LICENSE', 'LICENSE.md', 'LICENSE.txt', 'COPYING', 'NOTICE',
}
SKIPPED_SUFFIXES = ('.lock', '.min.js', '.min.css', '.map')

# Fixture identifiers are fabricated by design: jane@qnsc.vn and 10.0.0.1 in a
# spec file are props, not leaks, and a pattern that fired on them would be
# trained out within a week. Test paths are skipped for every pattern EXCEPT the
# two fed in at runtime — the org's own identifiers are never legitimately
# public, test or not.
TESTISH_PATH = re.compile(
    r'(^|/)(tests?|__tests__|__snapshots__|fixtures?|mocks?|testdata)/'
    r'|[._-](test|spec)\.[a-zA-Z0-9]+$'
)

# The STATIC patterns: id, regex, whether test-ish paths are exempt, whether the
# matched text is redacted in the report.
#   qnsc-hostname — any host under the organisation's domain (admin., doors., …).
#     The registrable domain alone in prose ("qnsc.vn") is not matched, and
#     www.qnsc.vn — the public site — is a per-repo allowlist entry, not an
#     exemption baked in here.
#   qnsc-email — internal mail. The generic any-address pattern was dropped:
#     on a first dry run it fired hundreds of times on placeholder addresses in
#     form markup (user@company.com), which trains people to ignore the check.
#   guid — arbitrary UUIDs outside tests, where real subscription/object ids
#     tend to be pasted as "harmless examples". The org's own tenant GUID is a
#     RUNTIME pattern (see above), not this one.
#   private-ipv4 / private-ipv6 — RFC1918, link-local and CGNAT space, and ULA /
#     link-local v6. 127.0.0.1 and ::1 are NOT leaks (the local-dev port-binding
#     convention binds loopback on purpose) and are simply not in the patterns.
STATIC_PATTERNS: list[tuple[str, re.Pattern[str], bool, bool]] = [
    ('qnsc-hostname', re.compile(r'\b(?:[a-z0-9-]+\.)+qnsc\.vn\b', re.IGNORECASE), True, False),
    ('qnsc-email', re.compile(r'\b[\w.+-]+@qnsc\.vn\b', re.IGNORECASE), True, False),
    ('guid', re.compile(
        r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
        re.IGNORECASE), True, False),
    ('private-ipv4', re.compile(
        r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
        r'|192\.168\.\d{1,3}\.\d{1,3}'
        r'|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}'
        r'|169\.254\.\d{1,3}\.\d{1,3}'
        r'|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})\b'), True, False),
    ('private-ipv6', re.compile(r'\b(?:f[cd][0-9a-f]{2}:|fe80:)', re.IGNORECASE), True, False),
]


def runtime_patterns(entra_tenant_id: str, aws_account_id: str):
    """The org's own identifiers, escaped into exact-match patterns.

    Redacted in every line of output: the report runs in a public repo's Actions
    log, and echoing the value to say "this value should not be here" would be
    the leak it is complaining about.
    """
    out: list[tuple[str, re.Pattern[str], bool, bool]] = []
    if entra_tenant_id:
        out.append(('entra-tenant', re.compile(rf'\b{re.escape(entra_tenant_id)}\b',
                                               re.IGNORECASE), False, True))
    if aws_account_id:
        out.append(('aws-account', re.compile(rf'\b{re.escape(aws_account_id)}\b'), False, True))
    return out


def is_binary(path: Path) -> bool:
    """A NUL in the first 8 KiB is how git decides; match that, nothing fancier."""
    with path.open('rb') as fh:
        return b'\0' in fh.read(8192)


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '.git']
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if name in SKIPPED_BASENAMES or name.endswith(SKIPPED_SUFFIXES):
                continue
            yield path


def load_allowlist(path: Path | None) -> list[re.Pattern[str]]:
    if path is None:
        return []
    compiled: list[re.Pattern[str]] = []
    for lineno, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        try:
            compiled.append(re.compile(line))
        except re.error as exc:
            print(f'::error::{path}:{lineno}: not a valid regular expression: {line} ({exc})')
            sys.exit(2)
    return compiled


def suppresses(allowlist: list[re.Pattern[str]], relpath: str, text: str) -> bool:
    # A line matches either the finding's text or the file's path, so an
    # allowlist can exempt one bad-looking constant or one whole directory.
    return any(p.search(text) or p.search(relpath) for p in allowlist)


def scan(root: Path, patterns, allowlist: list[re.Pattern[str]]):
    findings, suppressed = [], 0
    # Redacted (runtime-identifier) patterns win over any static pattern that
    # would match the same text — otherwise the generic GUID pattern would echo
    # the tenant GUID in the very report that exists to keep it out of the log.
    redacted_res = [p for _, p, _, red in patterns if red]
    for path in iter_files(root):
        if is_binary(path):
            continue
        relpath = path.relative_to(root).as_posix()
        testish = bool(TESTISH_PATH.search(relpath))
        text = path.read_text(encoding='utf-8', errors='replace')
        for lineno, line in enumerate(text.splitlines(), 1):
            for pid, pattern, exempt_tests, redact in patterns:
                if exempt_tests and testish:
                    continue
                for m in pattern.finditer(line):
                    hit = m.group(0)
                    if suppresses(allowlist, relpath, hit):
                        suppressed += 1
                        continue
                    if not redact and any(p.search(hit) for p in redacted_res):
                        continue  # reported once, redacted, by its own pattern
                    shown = '(redacted)' if redact else hit
                    findings.append(f'{relpath}:{lineno}: [{pid}] {shown}')
    return findings, suppressed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', default='.', help='repository root to scan (default: cwd)')
    parser.add_argument('--allowlist', default='.github/leak-guard-allowlist.txt',
                        help='per-repo allowlist of regular expressions (text or path)')
    parser.add_argument('--entra-tenant-id', default='',
                        help='org Entra tenant GUID, from vars.ENTRA_TENANT_ID. Empty disarms the pattern.')
    parser.add_argument('--aws-account-id', default='',
                        help='org AWS account number, from vars.AWS_ACCOUNT_ID. Empty disarms the pattern.')
    parser.add_argument('--report-only', action='store_true',
                        help='log findings without failing (exit 0)')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    allowlist_path = Path(args.allowlist)
    if allowlist_path.is_file():
        patterns_list = load_allowlist(allowlist_path)
    elif args.allowlist != parser.get_default('allowlist'):
        # A MISSING default allowlist is fine (a clean repo needs none); a named
        # one that is not there is a mistake worth stopping for.
        print(f'::error::allowlist not found: {args.allowlist}')
        return 2
    else:
        patterns_list = []

    patterns = STATIC_PATTERNS + runtime_patterns(args.entra_tenant_id, args.aws_account_id)
    findings, suppressed = scan(root, patterns, patterns_list)
    for finding in findings:
        print(f'::error file={finding.split(":")[0]}::{finding}')
    # Names which patterns ran, never their values.
    armed = ', '.join(pid for pid, _, _, _ in patterns) or 'none'
    print(f'leak-guard: {len(findings)} finding(s), {suppressed} suppressed by allowlist, '
          f'{len(patterns_list)} allowlist pattern(s), patterns armed: {armed}, root={root}')
    if findings and not args.report_only:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
