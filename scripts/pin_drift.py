#!/usr/bin/env python3
"""Report where consumer repos disagree with each other, or with the newest release,
on a shared version pin.

WHY THIS EXISTS. On 2026-08-12 every rally infra PR went red:

    Error: reading Secrets Manager Secret Version (.../tunnel-token-tf-*):
    AccessDeniedException: not authorized to perform: secretsmanager:GetSecretValue

The fix already existed in qnsc-ci — `fix(infra-plan): plan without reading secret
values`, released in v1.7.2 — and qnsc-kb-backend was already on it. rally was on
v1.6.6, uniformly, across all 11 references. Nothing about rally was wrong. It was a
stale pin, and nothing anywhere reported that.

The same day showed the other half: rally was AHEAD on cf-tunnel while kb was ahead on
iam-oidc and secrets. Neither repo was canonical, so "copy the good one" had no answer.
That is what makes divergence expensive — not being behind, but nobody knowing which way.

A REPORT, NOT A GATE, deliberately. Holding a version back during a migration is a real
decision, and a failing build would be ignored or worked around rather than read. This
prints a table. Escalate only if the table gets ignored.

Coverage is DISCOVERED from the org, not listed here — see consumer_repos(). A new
product repo appears in the next run with no edit to this file.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path

OWNER = "quynhonsemiconductor"

# The two repos that DEFINE the shared versions, excluded because they are not consumers:
# qnsc-tf-modules holds the modules rather than pinning them, and qnsc-ci referencing its
# own actions would appear as a repository disagreeing with itself about nothing.
SOURCES = {"qnsc-ci", "qnsc-tf-modules"}

# `qnsc-ci/.github/workflows/security.yml@v1.7.2`, `qnsc-ci/actions/setup-tofu-aws@v1`
CI_PIN = re.compile(r"qnsc-ci/[^@\s]+@(v\d+(?:\.\d+){0,2})")
# `modules/ecr?ref=ecr-v2.0.0`
MODULE_PIN = re.compile(r"modules/[a-z0-9-]+\?ref=([a-z0-9-]+)-(v\d+\.\d+\.\d+)")
# `iam-oidc-v3.0.1` — a per-module release tag in qnsc-tf-modules
MODULE_TAG = re.compile(r"^([a-z0-9-]+)-(v\d+\.\d+\.\d+)$")
SEMVER_TAG = re.compile(r"^v\d+\.\d+\.\d+$")


def run(*args: str, cwd: str | None = None) -> str:
    """Run a command, and on failure say what failed and why.

    `check=True` alone raises CalledProcessError with the captured stderr hidden inside it,
    so a transient clone failure printed a traceback ending at the subprocess call and
    nothing about the network or the repository.
    """
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"pin-drift: `{' '.join(args)}` exited {result.returncode}\n"
            f"{result.stderr.strip() or '(no stderr)'}"
        )
    return result.stdout


def consumer_repos() -> tuple[list[str], list[str]]:
    """Every active repo in the org that could pin a shared version.

    DISCOVERED, NOT LISTED, and the first version of this file got that wrong. It named
    rally and qnsc-kb-backend; the org has a dozen active repos, and the one repo still on
    an old qnsc-ci pin — qnsc-kb-frontend — was the one the list omitted. A report whose
    coverage is hand-maintained has the same defect it exists to find, one level up. It
    would also have missed opshub, which shares this boilerplate by policy, and qnsc-infra,
    which consumes the terraform modules directly.

    Archived repos are excluded: rally-api, rally-infra, opshub-api and friends are frozen
    predecessors, so their pins are history rather than drift.

    PRIVATE repos are excluded too, and that is a real limitation rather than a choice —
    the job holds no cross-repo token, so it cannot clone them. It is reported in the
    output instead of being silently dropped, because a repo missing from a coverage report
    is exactly the failure this function was written to remove.
    """
    request = urllib.request.Request(
        f"https://api.github.com/orgs/{OWNER}/repos?per_page=100",
        headers={"Accept": "application/vnd.github+json"},
    )
    # Authenticate when a token is available: unauthenticated API calls are rate-limited
    # per IP, and GitHub-hosted runners share addresses, so an anonymous call can fail for
    # reasons that have nothing to do with this org.
    if token := os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=30) as response:
        repos = json.load(response)

    if len(repos) == 100:  # pragma: no cover - the org is nowhere near this
        print("pin-drift: 100 repos returned; pagination is now required", file=sys.stderr)

    active = [r for r in repos if not r["archived"] and r["name"] not in SOURCES]
    return (
        sorted(r["name"] for r in active if not r["private"]),
        sorted(r["name"] for r in active if r["private"]),
    )


def version_key(v: str) -> tuple[int, ...]:
    """Sort v1.10.0 above v1.9.0, and treat a truncated pin as its own lowest patch.

    Truncation matters: `@v1` is a floating pin, so it is not comparable to `v1.7.2` and
    must not be reported as "stale" — it is a different thing, and the table says so by
    printing it verbatim.
    """
    return tuple(int(p) for p in v.lstrip("v").split("."))


def tags(repo: str) -> list[str]:
    out = run("git", "ls-remote", "--tags", "--refs", f"https://github.com/{OWNER}/{repo}")
    return [line.rsplit("/", 1)[-1] for line in out.splitlines() if line]


def newest_releases() -> tuple[str, dict[str, str]]:
    ci = max((t for t in tags("qnsc-ci") if SEMVER_TAG.match(t)), key=version_key)
    modules: dict[str, str] = {}
    for tag in tags("qnsc-tf-modules"):
        m = MODULE_TAG.match(tag)
        if m and (
            m.group(1) not in modules
            or version_key(m.group(2)) > version_key(modules[m.group(1)])
        ):
            modules[m.group(1)] = m.group(2)
    return ci, modules


def pins_used(repo_dir: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Every qnsc-ci version and every terraform module version this repo pins.

    Sets, not single values: a repo pinning TWO qnsc-ci versions is itself the finding —
    that is how one reusable ends up a version behind on its own.
    """
    ci: set[str] = set()
    modules: dict[str, set[str]] = defaultdict(set)
    for path in list(repo_dir.rglob("*.yml")) + list(repo_dir.rglob("*.tf")):
        if ".git/" in str(path):
            continue
        text = path.read_text(errors="ignore")
        ci.update(CI_PIN.findall(text))
        for name, version in MODULE_PIN.findall(text):
            modules[name].add(version)
    return ci, modules


def classify(values: list[str], newest: str) -> str:
    """diverged beats stale: if the repos disagree, which one is behind is the lesser
    question and fixing the disagreement usually resolves both."""
    present = [v for v in values if v]
    if len({v for v in present}) > 1:
        return "**diverged**"
    if any(v != newest and v.count(".") == 2 for v in present):
        return "stale"
    return "ok"


def main() -> int:
    ci_latest, module_latest = newest_releases()

    candidates, unreadable = consumer_repos()
    used: dict[str, tuple[set[str], dict[str, set[str]]]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for repo in candidates:
            dest = Path(tmp) / repo
            run("git", "clone", "-q", "--depth", "1", f"https://github.com/{OWNER}/{repo}", str(dest))
            used[repo] = pins_used(dest)

    # A repo pinning nothing is not a consumer — product-docs and .github would otherwise
    # add empty columns that make the table wider and say less.
    REPOS = [r for r in candidates if used[r][0] or used[r][1]]
    skipped = [r for r in candidates if r not in REPOS]

    rows: list[tuple[str, list[str], str, str]] = []

    ci_values = [",".join(sorted(used[r][0], key=version_key)) for r in REPOS]
    rows.append(("qnsc-ci", ci_values, ci_latest, classify(ci_values, ci_latest)))

    for module in sorted(module_latest):
        values = [",".join(sorted(used[r][1].get(module, ()), key=version_key)) for r in REPOS]
        # Skip modules nobody pins: the catalogue is larger than any product's needs and
        # listing all of it buries the rows that matter.
        if any(values):
            rows.append((module, values, module_latest[module], classify(values, module_latest[module])))

    # ONE SECTION PER FINDING, not a repo-by-pin matrix. The matrix was fine for the two
    # repos this started with and became unreadable at ten: fifteen module rows against ten
    # columns is 150 cells of which most are "—", and a table nobody reads is the failure
    # mode this whole report was written to avoid.
    #
    # Grouping by VERSION rather than by repo also states the finding directly. "opshub is
    # on ecr v1.1.0 and everyone else is on v2.0.0" is the sentence someone acts on; a row
    # of ten cells makes the reader derive it.
    out = ["## Shared pin drift", ""]

    findings = [r for r in rows if r[3] != "ok"]
    if findings:
        for name, values, newest, status in findings:
            by_version: dict[str, list[str]] = defaultdict(list)
            for repo, value in zip(REPOS, values):
                if value:
                    by_version[value].append(repo)
            out.append(f"### {name} — {status}, newest `{newest}`")
            for version in sorted(by_version, key=lambda v: version_key(v.split(",")[0])):
                marker = "" if version == newest else "  ←"
                out.append(f"- `{version}`{marker} — {', '.join(by_version[version])}")
            out.append("")
        out += [
            "`diverged` = the repos disagree. `stale` = they agree but a newer release exists.",
            "",
            "Neither is automatically wrong. Holding a version back during a migration is",
            "legitimate; not knowing you are behind is not.",
            "",
        ]
    else:
        out += ["All shared pins agree and are current.", ""]

    current = [r[0] for r in rows if r[3] == "ok"]
    if current:
        out.append(f"Current everywhere: {', '.join(current)}.")

    out.append(f"Covered {len(REPOS)} of {len(candidates)} active public repos in {OWNER}.")
    if skipped:
        out.append(f"Pinned nothing, so not consumers: {', '.join(skipped)}.")
    if unreadable:
        # Named rather than omitted: this job holds no cross-repo token, so a private repo
        # cannot be cloned. Saying so is the difference between a known gap and the silent
        # one that made this report necessary.
        out.append(f"NOT COVERED (private, no token): {', '.join(unreadable)}.")

    report = "\n".join(out)
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(summary).write_text(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
