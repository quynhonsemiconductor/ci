#!/usr/bin/env python3
"""Report where the product stack modules have diverged from each other.

WHY THIS EXISTS. Each product repo carries its own `infra/modules/stack` composition
module — rova 3,232 lines, opshub 2,539, qnsc-kb 1,096 — implementing one pattern three
times. The duplication is known and tracked in qnsc-infra/docs/product-service-extraction.md.
What was NOT tracked is that improvements land in SOME copies and not others, silently, and
the cost is real. Three examples found in a single audit on 2026-09-12:

  1. `cache.shared` / `cache.db_index` — the shared-develop-cache support — existed in
     rova's and qnsc-kb's modules and was ABSENT from opshub's. So opshub-develop
     provisioned its own ElastiCache node and paid ~$15/month for a cache serving services
     pinned at min_count = 0. ElastiCache cannot be stopped, so that billed 730 h/month.

  2. The cache/min_count precondition was a `validation` in rova and opshub and a `check`
     block in qnsc-kb. A violated check emits `Warning: Check block assertion failed` and
     the plan exits 0 (measured on OpenTofu 1.12.3), so qnsc-kb's guard permitted exactly
     the state it described — and there, the cache is the Celery broker.

  3. The Valkey `db_index` registry was inline in all three modules in three different
     states: rova's said "0 rally" after the product was renamed and omitted opshub,
     opshub's was complete, qnsc-kb's was absent.

Every one of those looked reasonable in the copy you happened to be reading. That is what
makes this class of divergence survive review, and why detecting it needs a tool rather than
discipline.

WHAT IT COMPARES. Two things, both cheap and both structural:

  * the SET of `module "..."` blocks each stack module declares — catches a whole capability
    present in one product and missing from another;
  * the ARGUMENT SET of the module calls listed in TRACKED_CALLS — catches an option added
    to one copy and not the others, which is finding (1) above.

WHAT IT DOES NOT COMPARE, deliberately: argument VALUES. Products legitimately differ there
(qnsc-kb is x86 because ClamAV ships no arm64 tag; rova and opshub are ARM64). Comparing
values would produce noise that trains people to ignore the report, which is the failure
mode pin_drift.py's own docstring warns about.

EXITS NON-ZERO ON DIVERGENCE, unlike pin_drift.py which reports and exits 0. Holding a
version pin back is a legitimate decision; a capability silently missing from one product is
not, and the measured cost of the last one was $15/month for an unknown number of months.
A red scheduled run is the notification. Add a deliberate difference to ACCEPTED below with
a reason rather than letting the report stay red.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

OWNER = "quynhonsemiconductor"

# Repos that carry an `infra/modules/stack`. Discovered rather than hardcoded would be
# nicer, but a repo without that path is simply skipped below, so a new product appears
# here with a one-line edit and never fails the run by being absent.
PRODUCT_REPOS = ["rova", "opshub", "qnsc-kb-backend"]

STACK_PATH = "infra/modules/stack"

# Module calls whose argument sets are compared. These are the ones where an option added to
# one product and not the others has cost money or degraded a control.
TRACKED_CALLS = ["api", "worker", "rds", "cache", "secrets"]

# Differences that are deliberate. Keyed by "<what>::<detail>", value is the reason.
# An entry here is a decision on the record, not a silenced finding.
ACCEPTED: dict[str, str] = {
    "api::options": "qnsc-kb only — FastAPI/uvicorn tuning with no NestJS equivalent",
    "api::task_secret_arns": "rova only — resolves per-connection SCM credentials at runtime",
    "worker::task_secret_arns": "rova only — same per-connection SCM credentials as the api",
    "module::app_bucket": "opshub only — uploads bucket; rova and qnsc-kb use Cloudflare R2",
    # qnsc-kb is x86_64 and cannot be ARM64: clavam/clamav publishes no arm64 tag, and the
    # malware scan sidecar is mandatory there. rova and opshub are both ARM64 (~20% cheaper
    # per vCPU-hour), so they pass cpu_architecture explicitly and qnsc-kb takes the default.
    "api::cpu_architecture": "qnsc-kb is x86 — clamav/clamav ships no arm64 tag",
    "worker::cpu_architecture": "qnsc-kb is x86 — clamav/clamav ships no arm64 tag",
    # qnsc-kb stores uploaded source documents in Cloudflare R2 (qnsc-kb-{develop,prod}-sources),
    # not S3, so its task role needs no S3 bucket grants.
    "api::s3_bucket_arns": "qnsc-kb uses Cloudflare R2 for object storage, not S3",
    "worker::s3_bucket_arns": "qnsc-kb uses Cloudflare R2 for object storage, not S3",
    # qnsc-kb's OTel is dormant by DESIGN, not missing by accident — and the distinction was
    # checked rather than assumed. Its app IS instrumented (pyproject.toml carries
    # opentelemetry-api/-sdk/-exporter-otlp-proto-http, and src/core/tracing.py builds an
    # OTLPSpanExporter) but gated on settings.OTEL_EXPORTER_OTLP_ENDPOINT, which .env.example
    # ships empty. opshub is in the same end state by a different route: it HAS the sidecar
    # modules with otlp_endpoint = "". So neither product emits telemetry today.
    #
    # The real difference is the cost of switching on: opshub sets a variable, qnsc-kb needs
    # the sidecar wiring written first. Closing that belongs in the product-service
    # extraction (qnsc-infra/docs/product-service-extraction.md), which gives all three
    # products identical sidecar wiring by construction — porting it into qnsc-kb's own
    # module now would write kb-specific code the extraction then replaces.
    "module::otel_agent_api": "qnsc-kb telemetry dormant by design; wiring lands with product-service",
    "module::otel_agent_worker": "qnsc-kb telemetry dormant by design; wiring lands with product-service",
    "module::firelens_agent_api": "qnsc-kb log routing lands with product-service",
    "module::firelens_agent_worker": "qnsc-kb log routing lands with product-service",
    "api::use_firelens": "follows module::firelens_agent_api",
    "worker::use_firelens": "follows module::firelens_agent_worker",
    # Grafana alert RULES query metrics that only arrive over OTLP. With qnsc-kb's telemetry
    # dormant, rules there would evaluate over no data and fire on absence. Correct order is
    # OTel first, then alerts. qnsc-kb does have module "observability" (CloudWatch alarms),
    # so its infrastructure alarms exist — it is application alerting that is absent.
    "module::alerts": "qnsc-kb has CloudWatch alarms; Grafana rules need OTLP data first",
    # rds.engine_version: the module default is "17" and every rova/opshub instance runs
    # 17.9, so they are pinned by the default rather than floating. qnsc-kb pins "16"
    # deliberately, to match the pgvector/pgvector:pg16 image used in development. Verified
    # against live AWS 2026-09-12.
    "rds::engine_version": "qnsc-kb pins 16 for pgvector:pg16; others take the module default 17",
    # Only qnsc-kb sends DKIM-signed mail from its own subdomain. rova and opshub send via
    # SES from noreply@qnsc.vn / opshub-noreply@qnsc.vn, whose DKIM records live in the
    # Cloudflare zone rather than a product stack.
    "module::dns_ses_dkim": "qnsc-kb signs its own subdomain; zone-level DKIM for the others",
}


def gh_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def clone(repo: str, dest: Path) -> Path | None:
    """Shallow clone, sparse to the stack module. Same approach as pin_drift.py."""
    target = dest / repo
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
         f"https://github.com/{OWNER}/{repo}.git", str(target)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(f"::warning::clone failed for {repo}: {result.stderr.strip()[:200]}")
        return None
    subprocess.run(["git", "-C", str(target), "sparse-checkout", "set", STACK_PATH],
                   capture_output=True, check=False)
    return target


def module_names(main_tf: str) -> set[str]:
    return set(re.findall(r'^module\s+"([a-z_0-9]+)"', main_tf, re.M))


def call_arguments(main_tf: str, call: str) -> set[str]:
    """Top-level argument names of one `module "<call>"` block."""
    match = re.search(rf'^module\s+"{re.escape(call)}"\s*\{{(.*?)^\}}', main_tf, re.M | re.S)
    if not match:
        return set()
    return set(re.findall(r'^\s{2,4}([a-z_0-9]+)\s*=', match.group(1), re.M))


def collect(root: Path) -> dict[str, object] | None:
    main_tf_path = root / STACK_PATH / "main.tf"
    if not main_tf_path.is_file():
        return None
    text = main_tf_path.read_text(encoding="utf-8")
    return {
        "modules": module_names(text),
        "calls": {call: call_arguments(text, call) for call in TRACKED_CALLS},
        "lines": text.count("\n") + 1,
    }


def main() -> int:
    local_root = os.environ.get("QNSC_LOCAL_ROOT")
    lines: list[str] = ["## Product stack module conformance", ""]
    facts: dict[str, dict[str, object]] = {}

    with tempfile.TemporaryDirectory() as tmp:
        for repo in PRODUCT_REPOS:
            if local_root:
                root = Path(local_root) / repo
            else:
                cloned = clone(repo, Path(tmp))
                if cloned is None:
                    continue
                root = cloned
            data = collect(root)
            if data is None:
                print(f"::warning::{repo} has no {STACK_PATH}/main.tf — skipped")
                continue
            facts[repo] = data

    if len(facts) < 2:
        lines.append("Fewer than two stack modules available — nothing to compare.")
        print("\n".join(lines))
        return 0

    lines.append("| product | stack lines | module blocks |")
    lines.append("| :--- | ---: | ---: |")
    for repo, data in facts.items():
        lines.append(f"| `{repo}` | {data['lines']:,} | {len(data['modules'])} |")
    lines.append("")

    findings = 0

    # ── Module-set divergence ────────────────────────────────────────────────
    everywhere = set.intersection(*(d["modules"] for d in facts.values()))
    anywhere = set.union(*(d["modules"] for d in facts.values()))
    partial = sorted(anywhere - everywhere)

    reported = []
    for name in partial:
        key = f"module::{name}"
        has = sorted(r for r, d in facts.items() if name in d["modules"])
        missing = sorted(r for r in facts if r not in has)
        if key in ACCEPTED:
            continue
        reported.append((name, has, missing))

    if reported:
        findings += len(reported)
        lines.append("### Module blocks present in some products, absent in others")
        lines.append("")
        lines.append("| module | present in | MISSING from |")
        lines.append("| :--- | :--- | :--- |")
        for name, has, missing in reported:
            lines.append(f"| `{name}` | {', '.join(has)} | **{', '.join(missing)}** |")
        lines.append("")

    # ── Argument-set divergence on tracked calls ─────────────────────────────
    arg_findings = []
    for call in TRACKED_CALLS:
        present = {r: d["calls"][call] for r, d in facts.items() if d["calls"][call]}
        if len(present) < 2:
            continue
        common = set.intersection(*present.values())
        union = set.union(*present.values())
        for arg in sorted(union - common):
            if f"{call}::{arg}" in ACCEPTED:
                continue
            has = sorted(r for r, a in present.items() if arg in a)
            missing = sorted(r for r in present if r not in has)
            arg_findings.append((call, arg, has, missing))

    if arg_findings:
        findings += len(arg_findings)
        lines.append("### Arguments passed in some products, absent in others")
        lines.append("")
        lines.append("| module call | argument | passed in | MISSING from |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for call, arg, has, missing in arg_findings:
            lines.append(f"| `{call}` | `{arg}` | {', '.join(has)} | **{', '.join(missing)}** |")
        lines.append("")

    if findings:
        lines.append(
            f"**{findings} divergence(s).** For each: port the capability to the products "
            "missing it, or record it in `ACCEPTED` in this script with a reason. A "
            "difference nobody has decided on is the one that costs money — see the module "
            "docstring for three that did."
        )
    else:
        lines.append("**No unexplained divergence.** The three compositions agree on structure.")

    if ACCEPTED:
        lines.append("")
        lines.append("<details><summary>Accepted differences</summary>")
        lines.append("")
        for key, reason in ACCEPTED.items():
            lines.append(f"- `{key}` — {reason}")
        lines.append("")
        lines.append("</details>")

    report = "\n".join(lines)
    print(report)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
