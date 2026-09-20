#!/usr/bin/env python3
"""Refuse a plan that destroys or replaces a data resource, unless it says so.

Task 0.3, §17b. This is the estate's answer to "nothing stops a green plan from
deleting a database", and it is deliberately NOT `lifecycle { prevent_destroy }`.

── WHY NOT prevent_destroy ──────────────────────────────────────────────────

Three reasons, all of them learned the hard way on 2026-09-19/20:

  1. IT CANNOT BE A VARIABLE ON THIS ESTATE. Every workflow pins OpenTofu 1.9.1
     (`TOFU_VERSION` in infra, rova, opshub, qnsc-kb-backend; `iac-lint`'s default
     in tf-modules; infra-template/.opentofu-version). Variables in a `lifecycle`
     block are a later feature — 1.12 accepts and enforces them, 1.9.1 rejects them
     at validate with "Variables not allowed". An attempt to ship it that way was
     reverted.

  2. HARDCODING `true` BLOCKS REPLACEMENT, NOT JUST DELETION, and this estate has
     documented operations that need replacement:
       infra/docs/rova-subnet-group-rebuild.md   an RDS instance replaced to
                                                 correct a subnet group name
       the secrets module's own comments         develop deletes secrets
                                                 immediately on teardown so a
                                                 destroy+redeploy does not hit
                                                 "secret scheduled for deletion"
     A protected resource turns each of those into edit-the-module, apply, do the
     work, edit it back — which is how a safety net becomes something people learn
     to switch off.

  3. IT LIVES IN THE WRONG REPOSITORY. Data resources are declared in `tf-modules`
     and consumed through pinned refs, so protecting them is a module release plus
     a caller bump in four repositories — and it protects by TYPE, forever, rather
     than by what a specific change is about to do.

── WHAT THIS DOES INSTEAD ───────────────────────────────────────────────────

It reads the plan — the actual proposed change — and fails if any data resource is
being deleted or replaced. Properties that fall out of that:

  * version-independent. It parses `tofu show -json`, which 1.9.1 emits happily.
  * it does not block anything. The subnet-group rebuild still works; the plan just
    has to declare that it is doing it.
  * it covers resources nobody has added yet, with no per-module plumbing.
  * it fails at PLAN time, in review, which is the gap `deletion_protection` leaves.
    §17b's 2026-09-14 incident happened WITH deletion_protection on: the destroy was
    authorised, protection was turned off first, in the same change, by someone who
    had read the plan and believed it.

── THE OVERRIDE IS A FILE, ON PURPOSE ───────────────────────────────────────

To destroy a data resource you add its address to `.allow-data-destroy` in the
stack directory, with a reason. Not a workflow input and not a PR label, because
both of those vanish from the record. A file is a diff someone reviews, and it has
to be removed afterwards — and this script reports a stale entry, so it is.

That is the same shape as the lesson in modules/.checkov.baseline: a suppression
keyed to something specific, that stops matching when the situation changes.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import sys
from collections.abc import Iterator

# ── What counts as data ──────────────────────────────────────────────────────
# A resource whose destruction loses something that cannot be rebuilt from this
# repository. NOT "expensive" or "important" — reproducible-from-git is the test,
# which is why an ECS service, a security group and a route table are absent: they
# are a re-apply away.
#
# `aws_db_subnet_group` and `aws_db_parameter_group` are deliberately NOT here.
# They hold no data, they point at it, and rova-subnet-group-rebuild.md is a
# rebuild of exactly one of them. Protect what holds data, not what points at it.
DATA_TYPES: frozenset[str] = frozenset({
    # relational
    "aws_db_instance",
    "aws_rds_cluster",
    "aws_rds_cluster_instance",
    "postgresql_database",
    # cache — ElastiCache has no deletion_protection at all, so a plan gate is the
    # ONLY thing standing between a green plan and a lost Celery queue (§5d).
    "aws_elasticache_serverless_cache",
    "aws_elasticache_replication_group",
    "aws_elasticache_cluster",
    # secrets — created empty by design (§8), values written out of band. Nothing
    # in state or git holds a copy, so a destroy is unrecoverable by this repo.
    "aws_secretsmanager_secret",
    # object storage and state
    "aws_s3_bucket",
    "aws_dynamodb_table",
    "aws_efs_file_system",
    # the snapshots that are the fallback for everything above
    "aws_db_snapshot",
    "aws_rds_cluster_snapshot",
})

DESTRUCTIVE = {"delete"}


@dataclasses.dataclass(frozen=True)
class Finding:
    address: str
    rtype: str
    actions: tuple[str, ...]

    @property
    def is_replace(self) -> bool:
        return "create" in self.actions and "delete" in self.actions

    @property
    def verb(self) -> str:
        return "REPLACE (destroy then create)" if self.is_replace else "DESTROY"


@dataclasses.dataclass(frozen=True)
class Allowance:
    address: str
    reason: str


def load_plan(path: pathlib.Path) -> dict:
    """Read a `tofu show -json` document.

    A plan with NO `resource_changes` key is not an empty plan — it is a document
    this script does not understand, and treating the two the same is how a guard
    reports success on data it never read. infra #129 and #132 are both that bug.
    """
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"  plan_guard: {path} is not valid JSON — {exc}\n"
                         f"  Produce it with: tofu show -json tfplan > plan.json")
    if not isinstance(doc, dict):
        raise SystemExit(f"  plan_guard: {path} is not a plan document (got {type(doc).__name__})")
    if "resource_changes" not in doc:
        # `format_version` present but no resource_changes means a plan with zero
        # changes at all, which OpenTofu does emit. Anything else is unreadable.
        if "format_version" not in doc:
            raise SystemExit(
                f"  plan_guard: {path} has neither `resource_changes` nor `format_version`.\n"
                f"  This is NOT an empty plan — it is a file this script could not read,\n"
                f"  and passing it would be a clean verdict on data nobody checked.")
    return doc


def findings(doc: dict) -> Iterator[Finding]:
    for rc in doc.get("resource_changes") or []:
        actions = tuple(rc.get("change", {}).get("actions") or [])
        if not DESTRUCTIVE.intersection(actions):
            continue
        rtype = rc.get("type") or ""
        if rtype not in DATA_TYPES:
            continue
        yield Finding(address=rc.get("address") or "<unknown>", rtype=rtype, actions=actions)


def read_allowances(path: pathlib.Path) -> list[Allowance]:
    """`.allow-data-destroy`: one address per line, `#` comments, reason after `--`.

        module.postgres.aws_db_instance.this  -- rova-subnet-group-rebuild.md step 3

    The reason is REQUIRED. An address with no reason is refused rather than
    accepted, because "someone added a line once" is not a decision anybody can
    review later.
    """
    if not path.exists():
        return []
    out: list[Allowance] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "--" not in line:
            raise SystemExit(
                f"  plan_guard: {path}:{lineno} has no reason.\n"
                f"    {raw.strip()}\n"
                f"  Write `<address>  -- why`. An allowance without a reason cannot be\n"
                f"  reviewed, and cannot be recognised as stale later.")
        addr, reason = line.split("--", 1)
        out.append(Allowance(address=addr.strip(), reason=reason.strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan_json", type=pathlib.Path,
                    help="output of `tofu show -json tfplan`")
    ap.add_argument("--stack-dir", type=pathlib.Path, default=None,
                    help="directory holding .allow-data-destroy (default: the plan's directory)")
    args = ap.parse_args()

    stack_dir = args.stack_dir or args.plan_json.parent
    allow_file = stack_dir / ".allow-data-destroy"

    doc = load_plan(args.plan_json)
    found = list(findings(doc))
    allowed = read_allowances(allow_file)
    allowed_addrs = {a.address for a in allowed}

    total = len(doc.get("resource_changes") or [])
    print(f"  plan_guard: {total} resource change(s) read from {args.plan_json}")

    unallowed = [f for f in found if f.address not in allowed_addrs]
    stale = sorted(allowed_addrs - {f.address for f in found})

    for f in found:
        mark = "allowed" if f.address in allowed_addrs else "REFUSED"
        print(f"    {mark:>7}  {f.verb:<28} {f.address}")

    if stale:
        # A WARNING, not a failure. The allowance did its job and the plan moved on;
        # leaving it costs nothing today and everything the next time this resource
        # is touched, which is exactly how the checkov baseline drifted.
        print(f"\n  STALE ALLOWANCES in {allow_file} — the plan does not destroy these.")
        print("  Remove them; an allowance that outlives its change is a standing permission.")
        for a in stale:
            print(f"    {a}")

    if not unallowed:
        if found:
            print(f"\n  {len(found)} data resource(s) destroyed, every one declared in "
                  f"{allow_file.name}. Allowed.")
        else:
            print("\n  no data resource is destroyed or replaced by this plan")
        return 0

    print(f"\n  REFUSING THIS PLAN — {len(unallowed)} data resource(s) would be lost\n")
    for f in unallowed:
        print(f"    {f.verb}  {f.address}")
        print(f"      type: {f.rtype}")
    print(f"""
  §17b: one Terraform state owning both a database and the services beside it
  already cost twelve minutes of downtime and four snapshots on 2026-09-14 — with
  `deletion_protection` ON, because the destroy was authorised and protection was
  turned off first, in the same change, by someone who had read the plan.

  This gate exists so that decision is made EXPLICITLY rather than inside a diff
  nobody reads to the end.

  If the destruction is intended, add each address to:

      {allow_file}

  one per line, with a reason after `--`:

      {unallowed[0].address}  -- why this must be destroyed

  Then remove the file in the same pull request that completes the work. A
  REPLACE is still a destroy: check whether a final snapshot is taken, and read
  `infra/docs/rova-subnet-group-rebuild.md` if this is a subnet-group rename.""")
    return 1


if __name__ == "__main__":
    sys.exit(main())
