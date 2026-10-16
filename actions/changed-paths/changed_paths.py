"""Decide whether a pull request's heavy CI jobs need to run. See action.yml for the contract.

Fails OPEN: every doubt is `run=true`. Only "every changed file is provably ignorable" turns it off.

Environment (set by action.yml):
  FILES_JSON   one JSON object per line: {"filename": ..., "previous_filename": ..., "patch": ...}
  IGNORE       newline-separated globs; when EVERY changed file matches one, run=false
  SKIP_HEADS   newline-separated rules `<head-branch-prefix>@<author>[,<author>...]=<glob>[,<glob>...]`
               A rule applies only when the head branch starts with the prefix AND the pull request's author
               is one of the listed logins (a branch name is chosen by whoever opens the PR; the author is not).
               A glob written `version-only:<glob>` additionally requires that the file's diff changes nothing
               but `"version": ...` lines.
  HEAD_REF     the pull request's head branch
  AUTHOR       the pull request author's login, e.g. `qnsc-automation[bot]`
  GITHUB_OUTPUT
"""

from __future__ import annotations

import json
import os
import re
import sys

VERSION_ONLY = "version-only:"
VERSION_LINE = re.compile(r'^[+-]\s*"version"\s*:')


def rx(glob: str) -> re.Pattern[str]:
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += "[^/]*"
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile("^" + out + "$")


def lines(name: str) -> list[str]:
    return [line.strip() for line in os.environ.get(name, "").splitlines() if line.strip()]


def version_only(patch: str | None) -> bool:
    """True only when every added or removed line of the diff is a `"version"` line.

    A missing patch (GitHub omits it for large or binary files) is NOT version-only.
    """
    if not patch:
        return False
    changed = [ln for ln in patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    return bool(changed) and all(VERSION_LINE.match(ln) for ln in changed)


def parse_files(raw: str) -> list[dict]:
    entries: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        entries.append(json.loads(line))
    return entries


def main() -> None:
    out = os.environ["GITHUB_OUTPUT"]

    def emit(value: str, why: str) -> None:
        with open(out, "a") as fh:
            fh.write(f"run={value}\n")
        print(f"changed-paths: run={value} ({why})")
        sys.exit(0)

    entries = parse_files(os.environ.get("FILES_JSON", ""))
    if not entries:
        emit("true", "no changed files listed")
    if len(entries) >= 3000:
        emit("true", "3,000-file API ceiling reached")

    # A rename is two paths: the old one must be ignorable too. It carries no patch, so it can never be version-only.
    paths: list[tuple[str, str | None]] = []
    for e in entries:
        paths.append((e["filename"], e.get("patch")))
        if e.get("previous_filename"):
            paths.append((e["previous_filename"], None))

    def all_match(globs: list[str]) -> bool:
        compiled = [(g.startswith(VERSION_ONLY), rx(g.removeprefix(VERSION_ONLY))) for g in globs]
        if not compiled:
            return False
        for name, patch in paths:
            if not any(c.match(name) and (not needs_version or version_only(patch)) for needs_version, c in compiled):
                return False
        return True

    head = os.environ.get("HEAD_REF", "")
    author = os.environ.get("AUTHOR", "").casefold()
    for rule in lines("SKIP_HEADS"):
        selector, _, globs = rule.partition("=")
        prefix, at, authors = selector.partition("@")
        allowed = {a.strip().casefold() for a in authors.split(",") if a.strip()}
        if not (prefix and at and allowed):
            print(f"::warning::changed-paths: ignoring malformed skip-heads rule {rule!r} (need prefix@author=globs)")
            continue
        if not head.startswith(prefix) or author not in allowed:
            continue
        if all_match([g.strip() for g in globs.split(",") if g.strip()]):
            emit("false", f"{author} on {head!r}: every one of {len(paths)} path(s) fits the {prefix!r} rule")

    if all_match(lines("IGNORE")):
        emit("false", f"all {len(paths)} changed path(s) are on the ignore list")
    emit("true", f"{len(paths)} changed path(s), at least one not ignorable")


if __name__ == "__main__":
    main()
