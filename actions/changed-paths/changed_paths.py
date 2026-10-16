"""Decide whether a pull request's heavy CI jobs need to run. See action.yml for the contract.

Fails OPEN: every doubt is `run=true`. Only "every changed file is on the ignore list" turns it off.
"""

from __future__ import annotations

import os
import re
import sys


def rx(glob):
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif glob.startswith("**", i):
            out += ".*"; i += 2
        elif glob[i] == "*":
            out += "[^/]*"; i += 1
        elif glob[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(glob[i]); i += 1
    return re.compile("^" + out + "$")

def lines(name):
    return [l.strip() for l in os.environ.get(name, "").splitlines() if l.strip()]

files = sorted({f for f in os.environ["FILES"].splitlines() if f})
out = os.environ["GITHUB_OUTPUT"]

def emit(value, why):
    with open(out, "a") as fh:
        fh.write(f"run={value}\n")
    print(f"changed-paths: run={value} ({why})")
    sys.exit(0)

if not files:
    emit("true", "no changed files listed")
if len(files) >= 3000:
    emit("true", "3,000-file API ceiling reached")

def all_match(globs):
    compiled = [rx(g) for g in globs]
    return bool(compiled) and all(any(c.match(f) for c in compiled) for f in files)

head = os.environ.get("HEAD_REF", "")
for rule in lines("SKIP_HEADS"):
    prefix, _, globs = rule.partition("=")
    if prefix and head.startswith(prefix) and all_match([g.strip() for g in globs.split(",") if g.strip()]):
        emit("false", f"head branch {head!r} and every one of {len(files)} file(s) fits the {prefix!r} rule")

if all_match(lines("IGNORE")):
    emit("false", f"all {len(files)} changed file(s) are on the ignore list")
emit("true", f"{len(files)} changed file(s), at least one not ignorable")
