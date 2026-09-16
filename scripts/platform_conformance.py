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

`terraform validate`, `helm lint` and `helm unittest` each pass on all five,
because each file is individually valid. That is the point: **per-concern
directories are the right structure and they are exactly what lets this hide.**
The answer is not to reorganise the folders, it is to validate across them.

This replaces two ad-hoc scripts that were growing in two different repositories
— `gitops/scripts/check-size-agreement.py` and `infra/scripts/check_remote_state.py`
— on the principle that repo-local tooling stays local and CROSS-REPO CONTRACTS
LIVE HERE. It is also the successor `stack_conformance.py` was waiting for:
§17 retires that one with the ECS estate, and this is what takes over its job.

ADDING A CONTRACT SHOULD BE ADDING AN ENTRY TO `CONTRACTS`, never writing another
script. If a check does not fit that shape, the shape is probably wrong.

    ./platform_conformance.py --root ~/Desktop/qnsc
    ./platform_conformance.py --root ~/Desktop/qnsc --only size,services
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import subprocess
import sys
from typing import Callable, Iterator

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

    def products(self) -> Iterator[tuple[str, str, pathlib.Path, pathlib.Path | None]]:
        """(product, env, values file, infra stack or None).

        A product with no infra stack is NOT a failure: §17 migrates one at a
        time, so an absent stack is a migration that has not happened. Silence
        about it would be wrong too, so callers report it as `unpaired`.
        """
        for base in sorted(self.gitops.glob("values/*/base.yaml")):
            product = base.parent.name
            for envfile in sorted(base.parent.glob("*.yaml")):
                # `base` is the shared layer; `tags.<env>` is machine-owned and
                # holds nothing this tool checks. Only the human overlays name an
                # environment. (Caught by this tool listing `tags.dev` as a
                # product environment the moment the split landed.)
                if envfile.stem == "base" or envfile.stem.startswith("tags."):
                    continue
                # `live/<product>-<env>`, one level. EVERY stack in the estate
                # sits directly under live/ — bootstrap, cluster-prod, data-dev,
                # kb-dev — because every tool that enumerates stacks does it by
                # globbing a fixed depth: iac-lint's `dirs`, the plan detector's
                # `cut -d/ -f1-3`, and this join. A second depth means all three
                # have to agree forever, and on 2026-09-16 they did not: kb was
                # the one nested stack, `live/*/` never reached it, and a module
                # path pointing OUT of the repository and then a ref to a tag that
                # did not exist both reached main through it unseen.
                stack = self.live / f"{product}-{envfile.stem}"
                yield product, envfile.stem, envfile, stack if stack.is_dir() else None

    @staticmethod
    def merged(base: pathlib.Path, env: pathlib.Path) -> dict:
        """Helm deep-merges base then env before the chart sees anything, so any
        check reading one without the other reads a file that never renders."""
        out = yaml.safe_load(base.read_text()) or {}
        for k, v in (yaml.safe_load(env.read_text()) or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = {**out[k], **v}
            else:
                out[k] = v
        return out

    @staticmethod
    def uncommented(f: pathlib.Path) -> str:
        """`hcl()` for ONE file. Comments mention `source =` when explaining why a
        module is pinned where it is, and matching those is a false positive."""
        return re.sub(r"(?m)^\s*(#|//).*$", "", f.read_text(encoding="utf-8"))

    @staticmethod
    def hcl(stack: pathlib.Path) -> str:
        """Comments mention outputs and module arguments constantly, usually to
        explain why one is NOT used any more — matching them produced a false
        positive on runtime-prod's line 253 the first time this ran. `.terraform/`
        holds vendored modules whose references are not this repo's problem."""
        text = "".join(f.read_text(encoding="utf-8") for f in stack.glob("*.tf"))
        return re.sub(r"(?m)^\s*(#|//).*$", "", text)


@dataclasses.dataclass
class Finding:
    contract: str
    where: str
    detail: str


Check = Callable[[Estate], list[Finding]]


# ── Contracts ─────────────────────────────────────────────────────────────────

def check_size(e: Estate) -> list[Finding]:
    """§7c — the ONE fact declared in two repositories.

    Everything else crossing the boundary is derived from product, env and
    service on both sides and cannot drift. `size` genuinely can: OpenTofu picks
    an RDS instance class from it, the chart picks replica counts and PDBs, and
    neither reads the other at plan time.

    A disagreement means a product is PROTECTED at one tier and PROVISIONED at
    another, and neither file is obviously wrong — so this reports rather than
    picking a winner.
    """
    out = []
    for product, env, envfile, stack in e.products():
        if not stack:
            continue
        want = e.merged(envfile.parent / "base.yaml", envfile).get("size")
        found = re.search(r'^\s*size\s*=\s*"([a-z]+)"', e.hcl(stack), re.M)
        if not found:
            out.append(Finding("size", f"{product}/{env}", "infra stack declares no size"))
        elif found.group(1) != want:
            out.append(Finding("size", f"{product}/{env}",
                               f"gitops={want!r}  infra={found.group(1)!r}"))
    return out


def check_services(e: Estate) -> list[Finding]:
    """The chart annotates each ServiceAccount with an IRSA role ARN it DERIVES;
    `product-profile` creates one role per entry in its own `services` map.

    Neither reads the other. A service in the chart with no entry in the module
    gets a ServiceAccount pointing at a role that does not exist — and the pod
    starts, runs, and fails only when it first calls AWS. A service in the module
    with no chart entry is an unused role nobody notices.
    """
    out = []
    for product, env, envfile, stack in e.products():
        if not stack:
            continue
        chart = set((e.merged(envfile.parent / "base.yaml", envfile).get("services") or {}))
        block = re.search(r"services\s*=\s*\{(.*?)\n  \}", e.hcl(stack), re.S)
        if not block:
            out.append(Finding("services", f"{product}/{env}", "infra stack declares no services map"))
            continue
        infra = set(re.findall(r"^\s*(\w+)\s*=\s*\{", block.group(1), re.M))
        for missing in sorted(chart - infra):
            out.append(Finding("services", f"{product}/{env}",
                               f"{missing!r} has a ServiceAccount but NO IRSA role — it will fail on its first AWS call"))
        for extra in sorted(infra - chart):
            out.append(Finding("services", f"{product}/{env}",
                               f"{extra!r} has an IRSA role but no service — dead grant"))
    return out


def check_remote_state(e: Estate) -> list[Finding]:
    """Remote-state outputs resolve at PLAN time, so a name that does not exist
    is syntactically perfect and passes every check that does not touch AWS. The
    first `tofu plan` is otherwise the earliest anything says so — by which point
    someone is mid-migration with credentials loaded.
    """
    BLOCK = re.compile(r'data\s+"terraform_remote_state"\s+"(\w+)"\s*\{(.*?)\n\}', re.S)
    out = []
    for stack in sorted(p.parent for p in e.live.rglob("*/main.tf")
                        if ".terraform" not in p.parts):
        hcl = e.hcl(stack)
        targets = {}
        for alias, body in ((m.group(1), m.group(2)) for m in BLOCK.finditer(hcl)):
            key = re.search(r'key\s*=\s*"([^"]+)"', body)
            cand = e.live.joinpath(*key.group(1).split("/")[1:-1]) if key else None
            targets[alias] = cand if cand and cand.is_dir() else None

        for alias, name in sorted({(m.group(1), m.group(2))
                                   for m in re.finditer(r"remote_state\.(\w+)\.outputs\.(\w+)", hcl)}):
            target = targets.get(alias)
            if target is None:
                out.append(Finding("remote-state", str(stack.relative_to(e.live)),
                                   f"cannot resolve which stack {alias!r} points at"))
                continue
            have = {m.group(1) for m in re.finditer(r'^output\s+"(\w+)"', e.hcl(target), re.M)}
            if name not in have:
                out.append(Finding("remote-state", str(stack.relative_to(e.live)),
                                   f"reads {alias}.{name} — {target.name} does not output it"))
    return out


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


CONTRACTS: dict[str, tuple[str, Check]] = {
    "size":         ("§7c — the one fact declared twice", check_size),
    "services":     ("chart ServiceAccounts vs product-profile IRSA roles", check_services),
    "remote-state": ("stack reads vs stack outputs", check_remote_state),
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

    unpaired = [f"{p}/{v}" for p, v, _, s in estate.products() if s is None]
    if unpaired:
        print(f"\n  not yet migrated, so not compared: {', '.join(unpaired)}")
        print("  §17 migrates one product at a time — an absent stack is expected, not broken.")

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
