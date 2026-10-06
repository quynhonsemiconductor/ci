#!/usr/bin/env python3
"""Measure a pull request the way a reviewer experiences it, and say so on it.

Lines of CODE are what a reviewer has to hold in their head, so that is what the
size label and the warnings count. Three other kinds of line are reported but not
counted:

  test     counting tests would penalise exactly the pull requests that add them
  docs     prose is read, not traced; a 363-line plan doc is not 363 lines of risk
  ignored  machine-written: lockfiles, generated clients, migration metadata,
           snapshots. Nobody reviews them, and a bump moves thousands of lines.

── WHY A WARNING AND NOT A GATE ─────────────────────────────────────────────

Size has legitimate exceptions — a mechanical rename, a codegen refresh, a
migration that is large because the schema is — and a hard limit teaches people
to route around it. Google's guidance on small changes, Kubernetes' `size/*`
labels and Danger's "Big PR" warning are all advisory for that reason.
`fail-above` exists for a later phase, with an override label, once the warnings
have shown where the line actually belongs.

── WHY THE THRESHOLDS ───────────────────────────────────────────────────────

Review effectiveness falls off past a few hundred lines (SmartBear/Cisco), and
on rova fourteen consecutive pull requests were 23–515 lines. The outlier, #653,
was 4,574 lines of code across ten user stories; its AI review covered 12–19 of
75 files per run and every run was partial. 2,500 is the same line the code
review workflow uses (`large_pr_lines`) to stop re-reviewing on every push.

Standard library only: this runs in repositories that install nothing for it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import PurePosixPath

MARKER = "<!-- qnsc-pr-size -->"

LOCKFILES = {
    "pnpm-lock.yaml", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "bun.lock",
    "bun.lockb", "poetry.lock", "uv.lock", "Pipfile.lock", "Cargo.lock", "go.sum",
    "pubspec.lock", ".terraform.lock.hcl", "composer.lock", "Gemfile.lock",
}
IGNORED = re.compile(
    r"(^|/)(generated|__generated__|__snapshots__|migrations/meta|vendor|dist)/"
    r"|\.(generated|gen|pb)\.[^/]+$|\.min\.(js|css)$|\.map$|\.snap$|(^|/)CHANGELOG\.md$"
)
TESTS = re.compile(
    r"(^|/)(__tests__|__mocks__|tests?|e2e|spec|testdata|fixtures)/"
    r"|\.(test|spec|e2e|e2e-spec)\.[cm]?[jt]sx?$"
    r"|_test\.(go|py|dart|rs)$|(^|/)test_[^/]*\.py$|_spec\.rb$|Tests?\.(java|kt|swift)$"
)
DOCS = re.compile(r"\.(md|mdx|rst|adoc|txt)$|(^|/)docs/|(^|/)(LICENSE|NOTICE)[^/]*$", re.I)

# Upper bound (exclusive) of CODE lines for each label; the last one is open-ended.
BUCKETS = [("XS", 10), ("S", 100), ("M", 400), ("L", 1000), ("XL", 2500), ("XXL", None)]
PREFIX = "size/"


def kind(path: str) -> str:
    if PurePosixPath(path).name in LOCKFILES or IGNORED.search(path):
        return "ignored"
    if TESTS.search(path):
        return "test"
    if DOCS.search(path):
        return "docs"
    return "code"


@dataclass
class Size:
    lines: dict[str, int] = field(default_factory=lambda: dict.fromkeys(
        ("code", "test", "docs", "ignored"), 0))
    files: dict[str, int] = field(default_factory=lambda: dict.fromkeys(
        ("code", "test", "docs", "ignored"), 0))
    largest: list[tuple[int, str]] = field(default_factory=list)  # code files only

    @property
    def code(self) -> int:
        return self.lines["code"]


def measure(files: list[dict]) -> Size:
    size = Size()
    for f in files:
        path = f.get("filename", "")
        changed = int(f.get("additions") or 0) + int(f.get("deletions") or 0)
        k = kind(path)
        size.lines[k] += changed
        size.files[k] += 1
        if k == "code" and changed:
            size.largest.append((changed, path))
    size.largest.sort(key=lambda t: (-t[0], t[1]))
    return size


def label_for(code: int) -> str:
    for name, upper in BUCKETS:
        if upper is None or code < upper:
            return PREFIX + name
    raise AssertionError("unreachable")


@dataclass
class Decision:
    label: str
    level: str      # none | warn | large | fail
    body: str       # comment body, empty when there is nothing to say
    fail: bool


def decide(size: Size, warn_above: int, large_above: int, fail_above: int,
           override: bool) -> Decision:
    label = label_for(size.code)
    if fail_above and size.code > fail_above and not override:
        level = "fail"
    elif large_above and size.code > large_above:
        level = "large"
    elif warn_above and size.code > warn_above:
        level = "warn"
    else:
        return Decision(label, "none", "", False)

    table = "\n".join([
        "| | lines | files |", "|---|---:|---:|",
        *(f"| {k}{' (counted)' if k == 'code' else ''} | {size.lines[k]:,} | {size.files[k]} |"
          for k in ("code", "test", "docs", "ignored")),
    ])
    top = "\n".join(f"- `{p}` ({n:,})" for n, p in size.largest[:5])
    headline = {
        "warn": f"📏 **This pull request changes {size.code:,} lines of code** (`{label}`). "
                "Review quality drops past a few hundred lines — consider splitting it.",
        "large": f"📏 **This pull request changes {size.code:,} lines of code** (`{label}`), "
                 f"more than {large_above:,}. It is too large to review well in one pass, by a "
                 "person or by the AI reviewer: the AI review runs when the pull request is "
                 "opened, reopened or marked ready for review, not on every push.",
        "fail": f"⛔ **This pull request changes {size.code:,} lines of code**, more than the "
                f"{fail_above:,} this repository allows. Split it, or add the "
                "override label with the reason in the description.",
    }[level]
    body = (f"{MARKER}\n{headline}\n\n{table}\n\nLargest code files:\n{top}\n\n"
            "**Splitting:** one pull request per user story, or per layer — migrations and domain "
            "first, then the API, then the UI — stacked so each one is reviewed against the last. "
            "Tests, docs and machine-written files are reported here but not counted.")
    return Decision(label, level, body, level == "fail")


def read_files(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure a pull request's size")
    parser.add_argument("--files", required=True, help="JSON lines, one GitHub PR file per line")
    parser.add_argument("--body-out", required=True)
    args = parser.parse_args(argv)

    files = read_files(args.files)
    size = measure(files)
    labels = {s.strip() for s in os.environ.get("PR_LABELS", "").split(",") if s.strip()}
    d = decide(size, _int(os.environ.get("WARN_ABOVE")), _int(os.environ.get("LARGE_ABOVE")),
               _int(os.environ.get("FAIL_ABOVE")),
               os.environ.get("OVERRIDE_LABEL", "") in labels)

    with open(args.body_out, "w", encoding="utf-8") as fh:
        fh.write(d.body)
    summary = " ".join(f"{k}={size.lines[k]}" for k in size.lines)
    print(f"label={d.label} level={d.level} {summary}")
    if d.level in ("warn", "large"):
        print(f"::warning::{size.code:,} lines of code changed ({d.label}); consider splitting")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"label={d.label}\nlevel={d.level}\nfail={str(d.fail).lower()}\n"
                     f"code_lines={size.code}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### PR size: `{d.label}`\n\n{summary}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
