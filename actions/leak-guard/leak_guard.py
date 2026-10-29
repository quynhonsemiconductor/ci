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

The identifiers that would themselves be leaks if written here — the Entra
tenant GUID, the Azure subscription id and the AWS account number — are NOT in
this file and NOT in the action's defaults. Callers feed them at runtime from
org variables (`vars.ENTRA_TENANT_ID`, `vars.AZURE_SUBSCRIPTION_ID`,
`vars.AWS_ACCOUNT_ID`); an empty input disarms that one pattern (the summary
names which patterns ran), and a finding prints the file and line with the VALUE
REDACTED, because a public repo's Actions log is public too.

What it deliberately does NOT do: scan git history (gitleaks already does, for
secrets — this check is about the CURRENT tree), and guess at "suspicious" text
(anything not matched is fine, which is why the pattern list is short and exact).

The allowlist (policy 2026-10-29) has three entry kinds, one per line:
  `key:<regex>`   suppresses an IDENTIFIER finding (guid, entra-tenant) only
                  when the finding is the VALUE OF that key on its own line —
                  the text immediately before the match must end with
                  `<key regex>` + \\s*[:=]\\s*\"?\". E.g. `key:tenantId` suppresses
                  the guid in `tenantId: 0123...` but not the same guid in
                  prose. Tier-2 ids are public-by-design only where a config
                  line names them, so the scope is the key/value pair, never
                  the line at large, the file or the directory. Empty and
                  wildcard-only key regexes are refused.
  `/`-containing  a LITERAL single-file path, matched exactly. Regex
                  metacharacters are refused — a path entry is a filename, not
                  a pattern — as is any trailing `/` (directory scopes are
                  what the policy forbids). An entry containing BOTH a slash
                  and metacharacters (a CIDR such as 10 dot 0 dot 0 dot 0 slash 16) is
                  rejected as a disguised path pattern: allowlist the address
                  without the mask.
  any other regex suppresses NON-identifier findings (hostnames, emails,
                  addresses) when it matches the finding's text — and nothing
                  else: identifier findings are key-scoped only, and a text
                  regex that can match a GUID at all is refused at load, so
                  `.*` or `[0-9a-f-]+` can never stand in for a key scope.

The Azure subscription id is TIER 1 and cannot be suppressed by ANY entry:
a finding means the value is removed from the tree, never allowlisted. Its
findings — and every other identifier-shaped finding (guid, entra-tenant) —
print the id name and file:line with the value REDACTED, so a disarmed
runtime input cannot leak through the static guid pattern's report.

Runtime identifier inputs are stripped and validated: the tenant GUID and the
subscription id must be GUIDs, the account number all digits — a malformed
value exits 2 rather than arming a pattern that can never fire.

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


def runtime_patterns(entra_tenant_id: str, azure_subscription_id: str, aws_account_id: str):
    """The org's own identifiers, escaped into exact-match patterns.

    Redacted in every line of output: the report runs in a public repo's Actions
    log, and echoing the value to say "this value should not be here" would be
    the leak it is complaining about.
    """
    out: list[tuple[str, re.Pattern[str], bool, bool]] = []
    if entra_tenant_id:
        out.append(('entra-tenant', re.compile(rf'\b{re.escape(entra_tenant_id)}\b',
                                               re.IGNORECASE), False, True))
    if azure_subscription_id:
        out.append(('azure-subscription',
                    re.compile(rf'\b{re.escape(azure_subscription_id)}\b',
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


# Identifier findings (guid, entra-tenant, azure-subscription) are key-scoped
# ONLY: no text or file entry suppresses them. Named for the check, not for a
# behavior — azure-subscription is additionally unsuppressible outright.
IDENTIFIER_PIDS = frozenset({'guid', 'entra-tenant', 'azure-subscription'})
# A stand-in GUID for the load-time refusal of text entries broad enough to
# match identifiers. Fabricated, not a real id.
SAMPLE_GUID = '3f2504e0-4f89-11d3-9a0c-0305e82c3301'


def load_allowlist(path: Path | None):
    """Returns (values, paths, keys): text regexes, literal file paths, `key:` regexes.

    Policy (2026-10-29) closes two scopes: directories (an entry ending in `/`,
    or a path that is really a pattern) and whole-line key matches (a key entry
    must sit immediately before the finding as `key: value`).
    """
    if path is None:
        return [], [], []
    values: list[re.Pattern[str]] = []
    paths: list[str] = []
    keys: list[re.Pattern[str]] = []
    for lineno, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('key:'):
            body = line[4:].strip()
            if not body:
                print(f'::error::{path}:{lineno}: empty key: entry — a key scope must '
                      f'name the key it matches')
                sys.exit(2)
            try:
                pat = re.compile(body)
            except re.error as exc:
                print(f'::error::{path}:{lineno}: not a valid regular expression: {line} ({exc})')
                sys.exit(2)
            if pat.search('') is not None or pat.fullmatch('x') is not None:
                # A wildcard that matches everything (`.`, `.*`) exempts every
                # identifier on every key-shaped line; that is no scope.
                print(f'::error::{path}:{lineno}: key pattern matches empty or any single '
                      f'character — too broad to be a key scope: {line}')
                sys.exit(2)
            keys.append(pat)
            continue
        if '/' in line:
            # A LITERAL single file: no metacharacters, no trailing slash. Dots
            # are allowed (file names have them) and matched as themselves.
            bad = sorted(set(line) & PATH_FORBIDDEN)
            if line.endswith('/') or bad:
                why = 'whole directory' if line.endswith('/') else f'regex metacharacter(s) {"".join(bad)}'
                print(f'::error::{path}:{lineno}: path entries are LITERAL single files '
                      f'({why}); identifier policy 2026-10-29 — {line}')
                sys.exit(2)
            paths.append(line)
            continue
        try:
            pat = re.compile(line)
        except re.error as exc:
            print(f'::error::{path}:{lineno}: not a valid regular expression: {line} ({exc})')
            sys.exit(2)
        # A text entry that can match a GUID would suppress identifier findings
        # everywhere if text still applied to them — and identifier findings are
        # key-scoped only now. Refuse it at load so the intent cannot hide in a
        # broad regex: name the key, or leave the finding alone.
        if pat.search(SAMPLE_GUID):
            print(f'::error::{path}:{lineno}: text entry matches a GUID — identifier '
                  f'findings are key-scoped only; use key:<name> — {line}')
            sys.exit(2)
        values.append(pat)
    return values, paths, keys
def suppresses(pid, values, paths, relpath: str, text: str) -> bool:
    # Text entries match NON-identifier findings by value; path entries are
    # literal file names compared whole. Identifier findings (guid,
    # entra-tenant, azure-subscription) are key-scoped only — no text or file
    # entry touches them.
    if pid in IDENTIFIER_PIDS:
        return False
    return (any(p.search(text) for p in values)
            or relpath in paths)


def key_matches(keys, prefix: str) -> bool:
    # The finding must be the VALUE of the key: the text immediately before it
    # ends with the key, a joiner and an optional quote. The key regex is
    # wrapped in (?:...) so an alternation binds as the KEY and not as
    # key|joiner, and left-anchored with (?<![\w-]) so `key:Id` cannot match
    # the tail of `clientId:` — a key entry names a key, not a key's suffix.
    return any(re.search(r'(?<![\w-])(?:' + k.pattern + r')\s*[:=]\s*"?$', prefix)
               for k in keys)


# Identifier-shaped patterns whose findings a `key:` allowlist entry may
# suppress: the tier-2 ids that are public-by-design only where a config line
# names them as a key's value. The Azure subscription id is TIER 1 and is not
# key-scopable — or suppressible at all. Hostnames and emails are never
# key-scoped; their entries are exact text values.
KEY_SCOPABLE = frozenset({'guid', 'entra-tenant'})
# Findings whose VALUE is never printed: identifier-shaped, because a public
# repo's Actions log is public, and a disarmed runtime input must not leak via
# the static guid pattern's report.
REDACT_OUTPUT = frozenset({'guid', 'entra-tenant', 'azure-subscription'})
# The tier-1 id: no allowlist entry — text, path or key — may suppress it.
UNSUPPRESSIBLE = frozenset({'azure-subscription'})
# Path entries are LITERAL file names: every one of these would make the
# "path" a pattern, and a pattern that matches paths is a directory loophole
# in disguise.
PATH_FORBIDDEN = set('\\^$*+?()[]{}|')


def scan(root: Path, patterns, allowlist=None, keys=None):
    findings, suppressed = [], 0
    values, paths = allowlist if allowlist is not None else ([], [])
    keys = keys if keys is not None else []
    # Redacted (runtime-identifier) patterns win over any static pattern that
    # would match the same text — otherwise the generic GUID pattern would echo
    # the tenant GUID in the very report that exists to keep it out of the log.
    # The runtime (exact-literal) patterns are more specific than the generic
    # guid pattern: when both match the same text, only the runtime one reports.
    runtime_res = [p for _, p, _, red in patterns if red]
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
                    if pid in UNSUPPRESSIBLE:
                        pass  # tier 1: no allowlist can suppress it, by policy
                    elif suppresses(pid, values, paths, relpath, hit):
                        suppressed += 1
                        continue
                    elif pid in KEY_SCOPABLE and key_matches(keys, line[:m.start()]):
                        suppressed += 1
                        continue
                    if pid == 'guid' and any(p.search(hit) for p in runtime_res):
                        continue  # the exact runtime pattern reports this value instead
                    shown = '(redacted)' if (redact or pid in REDACT_OUTPUT) else hit
                    findings.append(f'{relpath}:{lineno}: [{pid}] {shown}')
    return findings, suppressed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', default='.', help='repository root to scan (default: cwd)')
    parser.add_argument('--allowlist', default='.github/leak-guard-allowlist.txt',
                        help='per-repo allowlist of regular expressions (text or path)')
    parser.add_argument('--entra-tenant-id', default='',
                        help='org Entra tenant GUID, from vars.ENTRA_TENANT_ID. Empty disarms the pattern.')
    parser.add_argument('--azure-subscription-id', default='',
                        help='org Azure subscription id (TIER 1), from vars.AZURE_SUBSCRIPTION_ID. '
                             'Empty disarms the pattern.')
    parser.add_argument('--aws-account-id', default='',
                        help='org AWS account number, from vars.AWS_ACCOUNT_ID. NOT armed by policy '
                             'since 2026-10-29; callers pass nothing.')
    parser.add_argument('--report-only', action='store_true',
                        help='log findings without failing (exit 0)')
    args = parser.parse_args(argv)

    def guid_input(name: str, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                                      r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', value):
            print(f'::error::{name} is not a GUID (tier-1/2 identifiers are GUIDs); '
                  f'refusing to arm a pattern that can never fire')
            raise SystemExit(2)
        return value

    entra_tenant_id = guid_input('--entra-tenant-id', args.entra_tenant_id)
    azure_subscription_id = guid_input('--azure-subscription-id', args.azure_subscription_id)
    aws_account_id = args.aws_account_id.strip()
    if aws_account_id and not aws_account_id.isdigit():
        print('::error::--aws-account-id is not a number; refusing to arm it')
        raise SystemExit(2)

    root = Path(args.root).resolve()
    allowlist_path = Path(args.allowlist)
    if allowlist_path.is_file():
        allowlists = load_allowlist(allowlist_path)
    elif args.allowlist != parser.get_default('allowlist'):
        # A MISSING default allowlist is fine (a clean repo needs none); a named
        # one that is not there is a mistake worth stopping for.
        print(f'::error::allowlist not found: {args.allowlist}')
        return 2
    else:
        allowlists = ([], [], [])

    patterns = STATIC_PATTERNS + runtime_patterns(entra_tenant_id,
                                                  azure_subscription_id,
                                                  aws_account_id)
    findings, suppressed = scan(root, patterns, (allowlists[0], allowlists[1]), allowlists[2])
    for finding in findings:
        print(f'::error file={finding.split(":")[0]}::{finding}')
    # Names which patterns ran, never their values.
    armed = ', '.join(pid for pid, _, _, _ in patterns) or 'none'
    entries = len(allowlists[0]) + len(allowlists[1]) + len(allowlists[2])
    print(f'leak-guard: {len(findings)} finding(s), {suppressed} suppressed by allowlist, '
          f'{entries} allowlist pattern(s), patterns armed: {armed}, root={root}')
    if findings and not args.report_only:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
