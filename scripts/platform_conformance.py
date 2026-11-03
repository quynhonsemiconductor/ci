#!/usr/bin/env python3
"""Check every contract that crosses a repository boundary.

WHY THIS EXISTS. A review on 2026-09-16 found FIVE bugs in one day, all the same
shape: a reference and its definition living in different files, each correct
alone, with nothing validating the pair.

  1. api and worker rendered with no `envFrom` at all — PgBouncer got the product
     secret, the migrator Job got the migrator secret, the applications got
     nothing. They would have started and failed on the first line that read
     DATABASE_URL, with the ExternalSecret beside them looking healthy.
  2. the KEDA request-rate trigger queried prometheus.platform.svc.cluster.local
     with no credentials. Nothing installs Prometheus and nothing will — §9i
     refuses to self-host LGTM. The trigger would never have fired, silently.
  3. platform/ referenced grafana-cloud, cloudflared and cluster-info. Nothing
     created any of them.
  4. five stacks read remote_state.network.outputs.kms_key_arn. It lives in
     `bootstrap`.
  5. the same stacks read private_route_table_ids, which no stack exports.

(4 and 5 were ECS-era stack facts, retired with those stacks; the remaining
contracts cover the same class of bug for the on-prem estate.)

`terraform validate`, `helm lint` and `helm unittest` each pass on all five,
because each file is individually valid. That is the point: **per-concern
directories are the right structure and they are exactly what lets this hide.**
The answer is not to reorganise the folders, it is to validate across them.

It replaced two ad-hoc scripts and the retired `stack_conformance.py`, all of
which compared the AWS estate that no longer exists. What is left is the two
contracts that still cross a boundary in the on-prem estate: a rendered
manifest's secret reference vs its creator, and a live stack's module source vs
a real tf-modules tag. The ECS-era `size`, `services` (IRSA roles) and
`remote-state` contracts went with the stacks that carried them.

ADDING A CONTRACT SHOULD BE ADDING AN ENTRY TO `CONTRACTS`, never writing another
script. If a check does not fit that shape, the shape is probably wrong.

    ./platform_conformance.py --root ~/Desktop/qnsc
    ./platform_conformance.py --root ~/Desktop/qnsc --only secret-refs
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import subprocess
import sys
from typing import Callable

try:
    import yaml
except ImportError:
    sys.exit("pyyaml required:  pip install pyyaml")


# ── The estate ────────────────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Estate:
    root: pathlib.Path

    @property
    def gitops(self) -> pathlib.Path:
        return self.root / "gitops"

    @property
    def live(self) -> pathlib.Path:
        return self.root / "infra" / "live"

    @property
    def tf_modules(self) -> pathlib.Path:
        return self.root / "tf-modules"

    def tags(self) -> set[str] | None:
        """Every tag in the tf-modules checkout, or None when it is not here.

        None is NOT a pass. `check_module_refs` reports it, because a silently
        unchecked contract is the failure mode this whole file exists for — the
        checkout is shallow by default and `git tag -l` on a shallow clone returns
        nothing, which would read as "every ref is broken" or, worse, be quietly
        skipped.
        """
        if not (self.tf_modules / ".git").exists():
            return None
        out = subprocess.run(["git", "-C", str(self.tf_modules), "tag", "-l"],
                             capture_output=True, text=True)
        if out.returncode != 0:
            return None
        return {t for t in out.stdout.split() if t}

    @staticmethod
    def uncommented(f: pathlib.Path) -> str:
        """`hcl()` for ONE file. Comments mention `source =` when explaining why a
        module is pinned where it is, and matching those is a false positive."""
        return re.sub(r"(?m)^\s*(#|//).*$", "", f.read_text(encoding="utf-8"))


@dataclasses.dataclass
class Finding:
    contract: str
    where: str
    detail: str


Check = Callable[[Estate], list[Finding]]


# ── Contracts ─────────────────────────────────────────────────────────────────

def check_secret_refs(e: Estate) -> list[Finding]:
    """Every `secretRef`/`secretKeyRef` in a rendered manifest or a platform
    manifest must have something that creates it.

    This is bug 1 and bug 3 from the review, generalised. Bug 1 was the opposite
    shape — a secret created and never referenced — which is why both directions
    are reported, but only the dangling REFERENCE fails: an unreferenced secret
    is waste, a missing one is an outage.
    """
    out = []
    created, referenced = set(), {}

    for f in list(e.gitops.glob("rendered/*/*.yaml")) + list(e.gitops.glob("platform/**/*.yaml")):
        for doc in (d for d in yaml.safe_load_all(f.read_text()) if isinstance(d, dict)):
            kind = doc.get("kind")
            meta = doc.get("metadata") or {}
            if kind in {"Secret", "ExternalSecret"}:
                created.add((doc.get("spec", {}).get("target", {}).get("name") or meta.get("name")))
            if kind == "ConfigMap":
                created.add(meta.get("name"))
            for ref in re.findall(r"'(?:secretRef|configMapRef|secretKeyRef|configMapKeyRef)':\s*\{'name':\s*'([^']+)'",
                                  str(doc)):
                referenced.setdefault(ref, set()).add(f.name)

    for name, files in sorted(referenced.items()):
        if name not in created:
            out.append(Finding("secret-refs", ", ".join(sorted(files)),
                               f"{name!r} is referenced but nothing creates it"))
    return out


def check_module_refs(e: Estate) -> list[Finding]:
    """Every `source` in a live stack must resolve — from a CI checkout, not a laptop.

    Both halves of this are bugs that reached main inside a week, in the same
    stack, and neither was catchable by anything that reads one repository:

      1. `source = "../../../tf-modules/modules/rds"` — a path OUT of the
         repository. It resolves on a machine that happens to have the two repos
         side by side and nowhere else, so `tofu validate` and tflint both PASSED
         locally while CI reported "the module directory does not exist or cannot
         be read" for every module in both data stacks.
      2. `?ref=product-profile-v1.0.0` — a tag nothing produces. The module was
         absent from release-please-config.json, so no `product-profile-v*` tag
         would ever have been cut. A ref to a tag that does not exist fails at
         `tofu init`, which is to say on the machine of whoever is mid-migration,
         not at review.

    A registry source (`hashicorp/...`) is somebody else's to resolve; only local
    paths and this org's git refs are checked.
    """
    SOURCE = re.compile(r'^\s*source\s*=\s*"([^"]+)"', re.M)
    GIT_REF = re.compile(r'^git::https://github\.com/quynhonsemiconductor/tf-modules\.git//'
                         r'modules/[\w-]+\?ref=(?P<ref>[\w.-]+)$')
    out: list[Finding] = []
    tags = e.tags()
    infra_root = e.live.parent

    for tf in sorted(p for p in e.live.rglob("*.tf") if ".terraform" not in p.parts):
        where = str(tf.relative_to(infra_root))
        for src in SOURCE.findall(e.uncommented(tf)):
            if src.startswith((".", "/")):
                resolved = (tf.parent / src).resolve()
                try:
                    resolved.relative_to(infra_root.resolve())
                except ValueError:
                    out.append(Finding("module-refs", where,
                                       f"{src!r} resolves OUTSIDE the repository — it works only on a "
                                       f"machine with the repos side by side, and CI checks out one"))
                continue

            m = GIT_REF.match(src)
            if not m:
                continue  # a registry module, or another org's — not this contract's
            ref = m.group("ref")
            if tags is None:
                out.append(Finding("module-refs", where,
                                   f"cannot verify {ref!r}: no tf-modules checkout beside infra "
                                   f"(check it out with fetch-depth: 0, or tags are absent)"))
            elif ref not in tags:
                out.append(Finding("module-refs", where,
                                   f"pins {ref!r} — no such tag in tf-modules. `tofu init` fails on "
                                   f"this, at apply time"))
    return out


# RETIRED 2026-10-16: `schedulable` (every rendered nodeSelector must be satisfiable by a node pool the estate creates). It
# read the EKS Auto Mode node pools (gitops/platform/compute, the cluster-* stacks), which were removed with the EKS stacks
# (infra#169, gitops#13) when the target moved to on-prem k3s; from 2026-10-14 it reported "NO node pool can provide it" for
# every workload, a finding about a cluster that no longer exists. A k3s equivalent needs an inventory of the real nodes'
# labels, which this estate does not declare anywhere to compare against; add it with that inventory, not before.
CONTRACTS: dict[str, tuple[str, Check]] = {
    "secret-refs":  ("§8 — references vs definitions", check_secret_refs),
    "module-refs":  ("live stack sources vs tf-modules tags", check_module_refs),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=pathlib.Path, required=True,
                    help="the directory holding gitops/, infra/, ci/, tf-modules/")
    ap.add_argument("--only", help="comma-separated contract names")
    args = ap.parse_args()

    estate = Estate(args.root.expanduser().resolve())
    if not estate.gitops.is_dir() or not estate.live.is_dir():
        return print(f"  {estate.root} does not look like the estate — expected gitops/ and infra/live/") or 2

    wanted = set(args.only.split(",")) if args.only else set(CONTRACTS)
    findings: list[Finding] = []

    for name, (why, check) in CONTRACTS.items():
        if name not in wanted:
            continue
        found = check(estate)
        findings += found
        print(f"  {'FAIL' if found else ' ok '}  {name:<14} {why}")

    if findings:
        print(f"\n  {len(findings)} FINDING(S)\n")
        for f in findings:
            print(f"    [{f.contract}] {f.where}\n      {f.detail}")
        print("""
  Every one of these is the same shape: a reference and its definition in
  different files, each individually valid. terraform validate, helm lint and
  helm unittest all pass. That is why this exists.""")
        return 1

    print("\n  every cross-repository contract holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
